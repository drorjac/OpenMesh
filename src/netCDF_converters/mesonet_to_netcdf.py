"""
Convert NY Mesonet CSV files to OpenSense-PWS-v1.0-mesonet netCDF4 format.

Input:  directory containing per-station CSV files (e.g. BKLN.csv, MANH.csv).
Output: single netCDF4 file with one group per station.
        Filename: mesonet_{start}_{end}.nc in output_dir.

Format spec: dataset/formats/netCDF_mesonet.adoc

Usage (CLI):
    python mesonet_to_netcdf.py <input_dir> <output_dir>

Usage (import):
    from mesonet_to_netcdf import mesonet_to_netcdf
    mesonet_to_netcdf(input_dir, output_dir)
"""

import os
import glob
import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import netCDF4 as nc


EPOCH_UNITS = "seconds since 1970-01-01 00:00:00 UTC"
FILL_VALUE  = np.float64(9.96921e+36)

# Raw CSV column -> (canonical_name, units, long_name)
COLUMN_MAP = {
    "temp_2m [degC]":                        ("temperature",            "degrees_celsius", "air_temperature_at_2m"),
    "temp_9m [degC]":                        ("temperature_9m",         "degrees_celsius", "air_temperature_at_9m"),
    "apparent_temperature [degC]":           ("apparent_temperature",   "degrees_celsius", "apparent_temperature"),
    "relative_humidity [percent]":           ("relative_humidity",      "%",               "relative_humidity"),
    "dewpoint [degC]":                       ("dewpoint",               "degrees_celsius", "dewpoint_temperature"),
    "precip_incremental [mm]":               ("rainfall_amount",        "mm",              "rainfall_amount_per_time_unit"),
    "precip_local [mm]":                     ("precip_local",           "mm",              "local_precipitation_accumulation"),
    "precip_max_intensity [mm/min]":         ("precip_max_intensity",   "mm min-1",        "maximum_precipitation_intensity"),
    "precip_1hr [mm]":                       ("precip_1hr",             "mm",              "precipitation_last_1_hour"),
    "avg_wind_speed_prop [m/s]":             ("wind_velocity_prop",     "ms-1",            "average_wind_speed_propeller"),
    "max_wind_speed_prop [m/s]":             ("wind_speed_max_prop",    "ms-1",            "maximum_wind_speed_propeller"),
    "wind_speed_stddev_prop [m/s]":          ("wind_speed_std_prop",    "ms-1",            "wind_speed_standard_deviation_propeller"),
    "wind_direction_prop [degrees]":         ("wind_direction_prop",    "degrees",         "wind_direction_propeller"),
    "wind_direction_stddev_prop [degrees]":  ("wind_direction_std_prop","degrees",         "wind_direction_standard_deviation_propeller"),
    "avg_wind_speed_sonic [m/s]":            ("wind_velocity_sonic",    "ms-1",            "average_wind_speed_sonic"),
    "max_wind_speed_sonic [m/s]":            ("wind_speed_max_sonic",   "ms-1",            "maximum_wind_speed_sonic"),
    "wind_speed_stddev_sonic [m/s]":         ("wind_speed_std_sonic",   "ms-1",            "wind_speed_standard_deviation_sonic"),
    "wind_direction_sonic [degrees]":        ("wind_direction_sonic",   "degrees",         "wind_direction_sonic"),
    "wind_direction_stddev_sonic [degrees]": ("wind_direction_std_sonic","degrees",        "wind_direction_standard_deviation_sonic"),
    "avg_wind_speed_merge [m/s]":            ("wind_velocity",          "ms-1",            "average_wind_speed_merged"),
    "max_wind_speed_merge [m/s]":            ("wind_speed_max",         "ms-1",            "maximum_wind_speed_merged"),
    "wind_speed_stddev_merge [m/s]":         ("wind_speed_std",         "ms-1",            "wind_speed_standard_deviation_merged"),
    "wind_direction_merge [degrees]":        ("wind_direction",         "degrees",         "wind_direction_merged"),
    "wind_direction_stddev_merge [degrees]": ("wind_direction_std",     "degrees",         "wind_direction_standard_deviation_merged"),
    "solar_insolation [W/m^2]":              ("solar_insolation",       "W m-2",           "solar_insolation"),
    "station_pressure [mbar]":               ("air_pressure",           "hPa",             "station_pressure"),
    "snow_depth [cm]":                       ("snow_depth",             "cm",              "snow_depth"),
    "frozen_soil_05cm [bit]":                ("frozen_soil_05cm",       "1",               "frozen_soil_flag_at_5cm"),
    "frozen_soil_25cm [bit]":                ("frozen_soil_25cm",       "1",               "frozen_soil_flag_at_25cm"),
    "frozen_soil_50cm [bit]":                ("frozen_soil_50cm",       "1",               "frozen_soil_flag_at_50cm"),
    "soil_temp_05cm [degC]":                 ("soil_temperature_05cm",  "degrees_celsius", "soil_temperature_at_5cm"),
    "soil_temp_25cm [degC]":                 ("soil_temperature_25cm",  "degrees_celsius", "soil_temperature_at_25cm"),
    "soil_temp_50cm [degC]":                 ("soil_temperature_50cm",  "degrees_celsius", "soil_temperature_at_50cm"),
    "soil_moisture_05cm [m^3/m^3]":          ("soil_moisture_05cm",     "m3 m-3",          "volumetric_soil_moisture_at_5cm"),
    "soil_moisture_25cm [m^3/m^3]":          ("soil_moisture_25cm",     "m3 m-3",          "volumetric_soil_moisture_at_25cm"),
    "soil_moisture_50cm [m^3/m^3]":          ("soil_moisture_50cm",     "m3 m-3",          "volumetric_soil_moisture_at_50cm"),
}

# Static coordinate columns in the CSV (same value for all rows)
STATIC_COLS = {
    "latitude [degrees_north]":  ("lat",  "degrees_in_WGS84_projection", "latitude"),
    "longitude [degrees_east]":  ("lon",  "degrees_in_WGS84_projection", "longitude"),
    "elevation [m]":             ("elev", "metres_above_sea",             "ground_elevation_above_sea_level"),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_time(series):
    """
    Parse mesonet time strings ("2023-08-01 00:00:00 UTC") to UTC epoch seconds.
    Returns a float64 numpy array.
    """
    clean = series.str.replace(" UTC", "", regex=False)
    dt = pd.to_datetime(clean, utc=True)
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    return (dt - epoch).dt.total_seconds().values


def _read_csv(path):
    """
    Read a mesonet CSV and return (station_id, time_epoch, static_dict, data_df).

    data_df: DataFrame with canonical column names, indexed by epoch seconds.
    static_dict: {canonical_name: float} for lat, lon, elev.
    """
    df = pd.read_csv(path)

    station_id = str(df["station"].iloc[0])
    time_epoch = _parse_time(df["time"])

    # Static coords (take first row — same for all rows)
    static = {}
    for raw_col, (canonical, units, long_name) in STATIC_COLS.items():
        if raw_col in df.columns:
            static[canonical] = (float(df[raw_col].iloc[0]), units, long_name)

    # Time-series data
    data = {}
    for raw_col, (canonical, units, long_name) in COLUMN_MAP.items():
        if raw_col in df.columns:
            data[canonical] = df[raw_col].values.astype(np.float64)

    data_df = pd.DataFrame(data, index=time_epoch)
    data_df.index.name = "time"

    return station_id, data_df, static


def _write_group(out_ds, station_id, df, static):
    """Write one station into a new netCDF4 group."""
    grp = out_ds.createGroup(station_id)
    n_time = len(df)

    grp.createDimension("id", 1)
    grp.createDimension("time", n_time)

    # Time
    t_var = grp.createVariable("time", np.float64, ("time",))
    t_var.units = EPOCH_UNITS
    t_var.long_name = "time_utc"
    t_var[:] = df.index.values

    # Station ID
    id_var = grp.createVariable("id", str, ("id",))
    id_var.long_name = "personal_weather_station_identifier"
    id_var[0] = station_id

    # Static coordinate variables
    for canonical, (value, units, long_name) in static.items():
        v = grp.createVariable(canonical, np.float64, ("id",))
        v.units = units
        v.long_name = long_name
        v[0] = value

    # Time-series variables
    # Build a reverse lookup: canonical -> (units, long_name) from COLUMN_MAP
    meta = {canonical: (units, long_name) for _, (canonical, units, long_name) in COLUMN_MAP.items()}

    for col in df.columns:
        v = grp.createVariable(col, np.float64, ("id", "time"), fill_value=FILL_VALUE)
        v[0, :] = df[col].values
        if col in meta:
            v.units = meta[col][0]
            v.long_name = meta[col][1]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def mesonet_to_netcdf(input_dir, output_dir):
    """
    Convert NY Mesonet CSV files to a single OpenSense-PWS-v1.0-mesonet netCDF4 file.

    Parameters
    ----------
    input_dir : str
        Directory containing per-station CSV files (e.g. BKLN.csv).
    output_dir : str
        Directory for the output file. Created if absent.

    Returns
    -------
    str
        Path to the output file.
    """
    csv_files = sorted(glob.glob(os.path.join(input_dir, "*.csv")))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {input_dir}")

    os.makedirs(output_dir, exist_ok=True)

    print(f"Found {len(csv_files)} CSV files: {[os.path.basename(f) for f in csv_files]}")

    # Read all stations
    stations = {}
    all_times = []
    for path in csv_files:
        station_id, df, static = _read_csv(path)
        stations[station_id] = (df, static)
        if len(df):
            all_times += [df.index.min(), df.index.max()]
        print(f"  {station_id}: {len(df)} rows  "
              f"{pd.Timestamp(df.index.min(), unit='s', tz='UTC').date()} → "
              f"{pd.Timestamp(df.index.max(), unit='s', tz='UTC').date()}")

    # Output filename from overall time range
    t_min = pd.Timestamp(min(all_times), unit="s", tz="UTC")
    t_max = pd.Timestamp(max(all_times), unit="s", tz="UTC")
    start_str = t_min.strftime("%Y-%m-%d")
    end_str   = t_max.strftime("%Y-%m-%d")
    out_path  = os.path.join(output_dir, f"mesonet_{start_str}_{end_str}.nc")

    # Write output
    out_ds = nc.Dataset(out_path, "w", format="NETCDF4")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_ds.title              = "NY Mesonet Urban Weather Data — NYC"
    out_ds.institution        = "New York State Mesonet"
    out_ds.source             = f"NY Mesonet 5-min CSV files, input_dir={os.path.abspath(input_dir)}"
    out_ds.Conventions        = "OpenSense-PWS-v1.0-mesonet"
    out_ds.naming_convention  = "OpenSense-PWS"
    out_ds.license            = "https://www.nysmesonet.org/about/data"
    out_ds.reference          = "https://www.nysmesonet.org/"
    out_ds.date_created       = now_str[:10]
    out_ds.start_date         = start_str
    out_ds.end_date           = end_str
    out_ds.history            = (
        f"{now_str}: Converted from CSV using mesonet_to_netcdf.py. "
        "Format spec: dataset/formats/netCDF_mesonet.adoc."
    )
    out_ds.comment            = (
        "5-minute resolution. wind_velocity/wind_direction use the merged sensor "
        "(best available of propeller and sonic). air_pressure in hPa (source unit "
        "mbar, numerically equivalent). All timestamps UTC."
    )

    for station_id, (df, static) in stations.items():
        _write_group(out_ds, station_id, df, static)

    out_ds.close()

    size_mb = os.path.getsize(out_path) / 1e6
    print(f"\nWrote : {out_path}")
    print(f"Period: {start_str} → {end_str}")
    print(f"Groups: {len(stations)} stations")
    print(f"Size  : {size_mb:.1f} MB")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert NY Mesonet CSV files to OpenSense-PWS netCDF4.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  python mesonet_to_netcdf.py \\\n"
            "    dataset/raw/mesonet/ \\\n"
            "    dataset/raw/full/outputs/"
        ),
    )
    parser.add_argument("input_dir",  help="Directory containing mesonet CSV files")
    parser.add_argument("output_dir", help="Output directory (created if absent)")
    args = parser.parse_args()
    mesonet_to_netcdf(args.input_dir, args.output_dir)


if __name__ == "__main__":
    main()
