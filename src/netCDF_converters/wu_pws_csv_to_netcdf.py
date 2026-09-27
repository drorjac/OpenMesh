"""
OPTIONAL converter — the default WU converter is wu_pws_csv_to_opensense.py (the one
behind the published Zenodo file). Use this one for the 2025-2026 scrape format, which
adds the airport stations (KNYC/KLGA/KJFK) and a `Condition` column.

Convert scraped Weather Underground CSVs (PWS and airport stations) to one
OpenSense-PWS-v1.0 netCDF4 file with one group per station.

Ported from weather_reroute/weather/csv_to_netcdf_v3.py — the script that produced
dataset/raw/full/pws_wu_network.nc (2026-04-24) and pws_data_new.nc (2026-05-22).
Changes: CLI arguments instead of env vars; DST handling valid for any year (was
hard-coded to 2024-2026, same result there); metadata may be the scrape metadata
(`Station Id`, feet) or dataset/meta/pws_metadata.csv (`Station ID`, metres).

Input:  a folder of CSVs named <STATION>_<anything>.csv (several files per station
        are concatenated). PWS columns: Datetime, Precip. Rate., Precip. Accum.,
        Temperature, Dew Point, Humidity, Wind, Speed, Gust, Pressure, UV, Solar.
        Airport (KNYC/KLGA/KJFK) columns: Datetime, Temperature, Dew Point, Humidity,
        Wind, Wind Speed, Wind Gust, Pressure, Precip., Condition. Local time
        (America/New_York), imperial units.
Output: metric units, UTC seconds since 1970. NOTE: `rainfall_amount` holds WU's
        running daily accumulation (mm); `analysis.pws_qc` detects this and
        differences it to per-interval rain. `precip_rate_calculated` is derived
        from it (mm/h).

Usage (CLI):
    python wu_pws_csv_to_netcdf.py <input_dir> <metadata_csv> <output.nc> [--elev-units m]
Usage (import):
    from wu_pws_csv_to_netcdf import convert_wu_csv_dir
    convert_wu_csv_dir(input_dir, metadata_csv, output_nc)
"""

import argparse
import os
import re
from collections import defaultdict
from datetime import datetime

import netCDF4 as nc
import numpy as np
import pandas as pd


#Airport Station Constants - should not need any changes
#Airport stations do not have elevation, just lat and lon information
AIRPORT_COORDS = {
    "KNYC": (40.78, -73.97),
    "KLGA": (40.76, -73.86),
    "KJFK": (40.70, -73.80),
}
AIRPORT_IDS = set(AIRPORT_COORDS.keys())


#NaN is used as the fill value for all missing numeric data.
FILL_VALUE = float("nan")


#data scraped from weather underground contains units, clean values before conversion
_NUMERIC_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)")
#for each column:
def clean_numeric(series):

    def _extract(val):
        if pd.isna(val):
            return np.nan
        #data should be in the form of the regex specified
        m = _NUMERIC_RE.match(str(val))
        #only capture the numerical value in the data field and convert to float
        return float(m.group(1)) if m else np.nan

    return series.apply(_extract)


#unit conversion helper functions
#does conversion based on cleaned data

def fahrenheit_to_celsius(series):
    return (clean_numeric(series) - 32.0) * 5.0 / 9.0


def inches_to_mm(series):
    return clean_numeric(series) * 25.4


def mph_to_ms(series):
    return clean_numeric(series) * 0.44704


def inhg_to_hpa(series):
    return clean_numeric(series) * 33.8639

#weather underground uses compass points (both short form and spelled out) for wind direction but convention requires degrees
def cardinal_to_degrees(value):
    #dictionary that maps compass points to degrees
    mapping = {
        #abbreviations
        "N":         0.0,  "NNE":       22.5, "NE":        45.0, "ENE":       67.5,
        "E":        90.0,  "ESE":      112.5, "SE":       135.0, "SSE":      157.5,
        "S":       180.0,  "SSW":      202.5, "SW":       225.0, "WSW":      247.5,
        "W":       270.0,  "WNW":      292.5, "NW":       315.0, "NNW":      337.5,

        #full spelling
        "NORTH":     0.0,  "NORTH-NORTHEAST": 22.5,
        "NORTHEAST": 45.0, "EAST-NORTHEAST":  67.5,
        "EAST":     90.0,  "EAST-SOUTHEAST": 112.5,
        "SOUTHEAST":135.0, "SOUTH-SOUTHEAST":157.5,
        "SOUTH":   180.0,  "SOUTH-SOUTHWEST":202.5,
        "SOUTHWEST":225.0, "WEST-SOUTHWEST":  247.5,
        "WEST":    270.0,  "WEST-NORTHWEST":  292.5,
        "NORTHWEST":315.0, "NORTH-NORTHWEST": 337.5,

        #some data fields would also use "CALM" or "VAR" to describe wind.
        # "CALM" is treated as 0 degrees, while "VAR" and "VARIABLE" are treated as NaN (missing).
        "CALM": 0.0, "VAR": np.nan, "VARIABLE": np.nan, "": np.nan,
    }
    if pd.isna(value):
        return np.nan
    return mapping.get(str(value).strip().upper(), np.nan)


#convert local time (EST/EDT) to UTC unix time
def eastern_to_utc(dt_series):
    #string format in csv file is standard datetime
    parsed = pd.to_datetime(dt_series)

    #the only ambiguous local times are the repeated 01:xx hour on the fall-back day;
    #read them as daylight time (EDT, the first occurrence). This is what the original
    #2024-2026 hard-coded mask did, generalised to any year.
    localized = parsed.dt.tz_localize(
        "America/New_York",
        ambiguous=np.ones(len(parsed), dtype=bool),
        nonexistent="shift_forward"
    )

    #convert to UTC
    utc_dt = localized.dt.tz_convert("UTC")

    #convert to Unix time
    return utc_dt.apply(lambda x: x.timestamp() if pd.notnull(x) else np.nan).values.astype(np.float64)

#generate additional column of data by calculating precipitation rate from precip accum
#calculation is done after time conversion and data cleaning
def calc_precip_rate_from_accum(time_epoch_arr, precip_accum_arr, max_gap_hours=2.0):
    t = np.asarray(time_epoch_arr, dtype=np.float64)
    a = np.asarray(precip_accum_arr, dtype=np.float64)

    n = len(t)
    #create new rate array based on data size
    rate = np.full(n, np.nan, dtype=np.float64)

    #at least 2 points needed to calculate a rate
    if n < 2:
        return rate

    #find change in accum and change in time (hrs)
    #will have length n-1
    delta_accum = np.diff(a)
    delta_t_h   = np.diff(t) / 3600.0

    #allow small negative tolerance but clip to 0 to prevent negative rates
    delta_accum = np.where((delta_accum >= -1e-5) & (delta_accum < 0), 0.0, delta_accum)

    #time and accum should only be increasing
    #the time gap between the 2 data points should not be too large (set as max 2 hrs)
    valid = (delta_accum >= 0.0) & (delta_t_h > 0.0) & (delta_t_h <= max_gap_hours)

    #calculate precipitation rate for valid cases
    rate[1:][valid] = delta_accum[valid] / delta_t_h[valid]

    return rate


#file processing methods

#airport and pws stations have different formats
#only 3 valid airport station ids (KNYC, KJFK, KLGA) hardcoded above
def detect_station_type(station_id):
    return "airport" if station_id in AIRPORT_IDS else "pws"

#the naming convention for the csv files is that the station id is the first string up to the first underscore
#eg. KNYNEWYO1841_2026-01-01_to_2026
def extract_station_id(filename):
    return os.path.basename(filename).split("_")[0]

#separate csv readers for each file type
#read and convert data for pws stations
def read_pws_csv(filepath):
    """
    PWS format columns:
    Datetime | Precip. Rate. | Precip. Accum. | Temperature | Dew Point |
    Humidity | Wind | Speed | Gust | Pressure | UV | Solar
    """
    df = pd.read_csv(filepath)

    #convert data based to match required convention
    return pd.DataFrame({
        "time_utc_epoch":      eastern_to_utc(df["Datetime"]),
        "precip_rate":         inches_to_mm(df["Precip. Rate."]),
        "rainfall_amount":        inches_to_mm(df["Precip. Accum."]),
        "temperature":         fahrenheit_to_celsius(df["Temperature"]),
        "dew_point":           fahrenheit_to_celsius(df["Dew Point"]),
        "relative_humidity":   clean_numeric(df["Humidity"]),
        "wind_direction":      df["Wind"].apply(cardinal_to_degrees),
        "wind_velocity":       mph_to_ms(df["Speed"]),
        "wind_gust":           mph_to_ms(df["Gust"]),
        "air_pressure":        inhg_to_hpa(df["Pressure"]),
        "uv_index":            clean_numeric(df["UV"]),
        "solar_radiation":     clean_numeric(df["Solar"]),
        #condition not present for pws stations
        "condition":           np.nan,
    })

#read and convert data for airport stations
def read_airport_csv(filepath):
    """
    Airport format columns:
    Datetime | Temperature | Dew Point | Humidity | Wind | Wind Speed |
    Wind Gust | Pressure | Precip. | Condition
    """
    df = pd.read_csv(filepath)

    #convert data to match convention
    return pd.DataFrame({
        "time_utc_epoch":      eastern_to_utc(df["Datetime"]),
        "rainfall_amount":        inches_to_mm(df["Precip."]),
        #airport data only has precipitation column, no precip rate
        "precip_rate":         np.nan,                        
        "temperature":         fahrenheit_to_celsius(df["Temperature"]),
        "dew_point":           fahrenheit_to_celsius(df["Dew Point"]),
        "relative_humidity":   clean_numeric(df["Humidity"]),
        "wind_direction":      df["Wind"].apply(cardinal_to_degrees),
        "wind_velocity":       mph_to_ms(df["Wind Speed"]),
        "wind_gust":           mph_to_ms(df["Wind Gust"]),
        "air_pressure":        inhg_to_hpa(df["Pressure"]),
        #uv index and solar radiation are absent from airport stations
        "uv_index":            np.nan,
        "solar_radiation":     np.nan,
        "condition":           df["Condition"].astype(str),
    })


#fetch metadata for pws/airport stations
def load_metadata(metadata_path, elev_units="ft"):
    """Station id -> lat, lon, elev (m). Accepts the WU scrape metadata
    (`Station Id`, elevation in feet) or dataset/meta/pws_metadata.csv
    (`Station ID`, elevation in metres: pass elev_units="m")."""
    meta = pd.read_csv(metadata_path)
    FT_TO_M = 0.3048 if elev_units == "ft" else 1.0
    #strip whitespace and BOM characters (if any)
    meta.columns = [c.strip().lstrip('\ufeff') for c in meta.columns]
    id_col = "Station Id" if "Station Id" in meta.columns else "Station ID"
    result = {}

    for _, row in meta.iterrows():
        sid = str(row[id_col]).strip()
        if sid in AIRPORT_IDS:
            continue  #airports handled separately below
        try:
            elev_ft = float(row["Elevation"]) if not pd.isna(row["Elevation"]) else np.nan
        except (ValueError, TypeError):
            elev_ft = np.nan  #stations which do not have elevation data will have 'Error' entry -> treat as missing data
        result[sid] = {
            "lat":  float(row["Latitude"]),
            "lon":  float(row["Longitude"]),
            "elev": elev_ft * FT_TO_M if not np.isnan(elev_ft) else np.nan,
        }

    #airport stations only have lat/lon
    for aid, (lat, lon) in AIRPORT_COORDS.items():
        result[aid] = {"lat": lat, "lon": lon, "elev": np.nan}

    return result

#Data variable catalogue : (long_name, units, required, is_string)
VARIABLE_META = {
    "rainfall_amount":         ("rainfall_amount_per_time_unit",   "mm",              True,  False),
    "precip_rate":             ("precipitation_rate",              "mm",              False, False),
    "precip_rate_calculated":  ("calculated_precipitation_rate",   "mm h-1",          False, False),
    "temperature":             ("air_temperature",                 "degrees_celsius", False, False),
    "dew_point":               ("dew_point_temperature",           "degrees_celsius", False, False),
    "relative_humidity":       ("relative_humidity",               "%",               False, False),
    "wind_direction":          ("wind_direction",                  "degrees",         False, False),
    "wind_velocity":           ("wind_velocity",                   "ms-1",            False, False),
    "wind_gust":               ("wind_gust_velocity",              "ms-1",            False, False),
    "air_pressure":            ("air_pressure",                    "hPa",             False, False),
    "uv_index":                ("ultraviolet_index",               "",                False, False),
    "solar_radiation":         ("solar_radiation",                 "W m-2",           False, False),
    "condition":               ("weather_condition_description",   "",                False, True),
}

#writes a single station's data into a pre-created netCDF group
def write_station_group(grp, df, station_id, lat, lon, elev):
    """
    Dimensions (per PWS netCDF spec):
        time  — UNLIMITED (spec: "unlimited size, enforce UTC seconds since 1970-01-01")
        id    — size 1 per group (one station per group)

    Coordinate variables (per spec):
        time(time)  f8   units = seconds since 1970-01-01 00:00:00 UTC
                         long_name = "time_utc", _FillValue = NaN
        id(id)      str  long_name = "personal_weather_station_identifier"

    Auxiliary coordinate variables (per spec):
        lat(id)     f8   units = degrees_north,  long_name = "latitude"
        lon(id)     f8   units = degrees_east,   long_name = "longitude"
        elev(id)    f8   units = metres_above_sea, long_name = "ground_elevation_above_sea_level"

    Data variables all carry:
        dimensions  = (id, time)
        coordinates = "lat lon"
        _FillValue  = NaN
    """
    #sort by time to ensure correct order to derive precip rate
    df = df.sort_values("time_utc_epoch").reset_index(drop=True)

    #compute precip rate
    accum_col = df["rainfall_amount"].values if "rainfall_amount" in df.columns else None
    if accum_col is not None and not np.all(np.isnan(accum_col.astype(float))):
        df["precip_rate_calculated"] = calc_precip_rate_from_accum(
            df["time_utc_epoch"].values, accum_col.astype(float)
        )
    else:
        df["precip_rate_calculated"] = np.nan

    #set dimensions
    n_time = len(df)
    grp.createDimension("id",   1)       # one station per group, listed first
    grp.createDimension("time", n_time)  # fixed size, matching sample file

    has_condition = (
        "condition" in df.columns
        and not all(str(v) in ("nan", "None", "") for v in df["condition"])
    )

    #coordinate variables
    #store time as a double, seconds since 1970-01-01 00:00:00 UTC
    time_var = grp.createVariable("time", "f8", ("time",))
    time_var.units = "seconds since 1970-01-01 00:00:00 UTC"
    time_var.long_name = "time_utc"
    time_var[:] = df["time_utc_epoch"].values.astype(np.float64)

    #store station id as a string
    id_var = grp.createVariable("id", str, ("id",))
    id_var.long_name = "personal_weather_station_identifier"
    id_var[0] = station_id

    #auxilary coordinate variables
    #store lat and lon as doubles
    lat_var = grp.createVariable("lat", "f8", ("id",), fill_value=FILL_VALUE)
    lat_var.units = "degrees_in_WGS84_projection"
    lat_var.long_name = "latitude"
    lat_var[0] = lat
    lon_var = grp.createVariable("lon", "f8", ("id",), fill_value=FILL_VALUE)
    lon_var.units = "degrees_in_WGS84_projection"
    lon_var.long_name = "longitude"
    lon_var[0] = lon

    #store elevation for personal pws stations (if available)
    if not np.isnan(elev):
        elev_var = grp.createVariable("elev", "f8", ("id",), fill_value=FILL_VALUE)
        elev_var.units = "metres_above_sea"
        elev_var.long_name = "ground_elevation_above_sea_level"
        elev_var[0] = elev

    #iterate through data variables and write to netCDF
    for varname, (long_name, units, required, is_string) in VARIABLE_META.items():
        if varname not in df.columns:
            continue

        col = df[varname]

        if is_string:
            #skip condition for pws stations
            if not has_condition:
                continue
            v = grp.createVariable(varname, str, ("time",))
            v.long_name = long_name
            v.coordinates = "lat lon"
            #data is stored as a string, with empty string as fill value for missing data   
            v[:] = col.fillna("").astype(str).values

        else:
            #store as double, with NaN as the fill value for missing data
            numeric = pd.to_numeric(col, errors="coerce").values.astype(np.float64)
            #skip optional variables that are entirely absent for this station type
            if np.all(np.isnan(numeric)) and not required:
                continue
            
            v = grp.createVariable(varname, "f8", ("id", "time"), fill_value=FILL_VALUE)
            v.long_name = long_name
            v.coordinates = "lat lon"
            if units:
                v.units = units
            v[0, :] = numeric


#process all files and write to netCDF
def convert_wu_csv_dir(input_dir, metadata_csv, output_nc, elev_units="ft", verbose=True):
    """Every <STATION>_*.csv in `input_dir` -> one grouped netCDF at `output_nc`."""
    input_dir = str(input_dir)
    os.makedirs(os.path.dirname(os.path.abspath(output_nc)), exist_ok=True)
    metadata = load_metadata(metadata_csv, elev_units)
    csv_files = [f for f in os.listdir(input_dir) if f.lower().endswith(".csv")]
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {input_dir}")

    #group csv files from the same station together
    station_files = defaultdict(list)
    for fname in csv_files:
        station_files[extract_station_id(fname)].append(os.path.join(input_dir, fname))
    if verbose:
        print(f"Found {len(station_files)} station(s): {sorted(station_files.keys())}\n")

    written, skipped = [], []
    with nc.Dataset(output_nc, "w", format="NETCDF4") as ds:
        ds.Conventions = "OpenSense-PWS-v1.0"
        ds.title = "Weather Underground PWS Data"
        ds.history = (f"Created {datetime.now().astimezone().isoformat()} by "
                      "src/netCDF_converters/wu_pws_csv_to_netcdf.py")

        for station_id, filepaths in sorted(station_files.items()):
            stype = detect_station_type(station_id)
            frames = []
            for fp in sorted(filepaths):
                try:
                    reader = read_airport_csv if stype == "airport" else read_pws_csv
                    frames.append(reader(fp))
                except Exception as e:
                    print(f"    WARNING: could not read {os.path.basename(fp)}: {e}")
            if not frames:
                skipped.append((station_id, "no readable files"))
                continue
            df = pd.concat(frames, ignore_index=True)
            df = df.drop_duplicates(subset="time_utc_epoch", keep="last")
            if station_id not in metadata:
                skipped.append((station_id, "no coordinates in metadata"))
                continue
            m = metadata[station_id]
            grp = ds.createGroup(station_id)
            write_station_group(grp, df, station_id, m["lat"], m["lon"], m["elev"])
            written.append(station_id)
            if verbose:
                print(f"  [{stype:7s}] {station_id}: {len(df)} time steps")

    if verbose:
        print(f"\nWrote {len(written)} station group(s) -> {output_nc}")
        for sid, why in skipped:
            print(f"  skipped {sid}: {why}")
    return output_nc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_dir", help="folder with <STATION>_*.csv files")
    ap.add_argument("metadata_csv", help="station metadata (Station Id/ID, Latitude, Longitude, Elevation)")
    ap.add_argument("output_nc", help="output netCDF path")
    ap.add_argument("--elev-units", choices=["ft", "m"], default="ft",
                    help="units of the metadata Elevation column (default ft, as scraped)")
    a = ap.parse_args()
    convert_wu_csv_dir(a.input_dir, a.metadata_csv, a.output_nc, a.elev_units)


if __name__ == "__main__":
    main()
