"""
Convert NOAA ASOS 1-min CSV files to OpenSense-PWS-v1.0-asos netCDF4 format.

Input:  a single ASOS CSV (e.g. ASOS_standard_2023-10-29_2026-04-24.csv) produced
        by src/fetch_data/noaa_asos/asos_fetch.py, plus dataset/meta/ASOS_stations.csv
        for lat/lon/elev lookup.
Output: single netCDF4 file with one group per station.
        Filename: asos_{start}_{end}.nc in output_dir.

Layout: matches mesonet_to_netcdf.py and the OpenSense PWS samples
        (pws_wu_os.nc, pws_opensense_sample_jan.nc) — one netCDF4 group per
        station, dim id=1 inside each.

Format spec: dataset/formats/netCDF_PWS.adoc
Mapping:     dataset/formats/format_mapping.md (ASOS section)

Usage (CLI):
    python asos_to_netcdf.py <input_csv> <output_dir> [--stations-csv PATH]

Usage (import):
    from asos_to_netcdf import asos_to_netcdf
    asos_to_netcdf(input_csv, output_dir)
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import netCDF4 as nc

# Pull the canonical precip_type → category map from the fetcher so the
# converter and the fetch step stay in sync (one source of truth).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fetch_data"))
from noaa_asos.asos_fetch import PTYPE_MAP, PRECIP_CATEGORIES  # noqa: E402


EPOCH_UNITS = "seconds since 1970-01-01 00:00:00 UTC"
FILL_VALUE  = np.float64(9.96921e+36)

DEFAULT_STATIONS_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "dataset", "meta", "ASOS_stations.csv")

# Raw CSV column -> (canonical_name, units, long_name)
# Numeric time-series variables. Spec-required variables are listed first;
# the rest are ASOS extras kept verbatim (per user request).
COLUMN_MAP = {
    "temperature":         ("temperature",         "degrees_celsius", "air_temperature"),
    "dewpoint":            ("dewpoint",            "degrees_celsius", "dewpoint_temperature"),
    "wind_speed":          ("wind_velocity",       "ms-1",            "wind_speed"),
    "wind_direction":      ("wind_direction",      "degrees",         "wind_direction"),
    "wind_gust":           ("wind_gust",           "ms-1",            "wind_gust_speed"),
    "wind_gust_direction": ("wind_gust_direction", "degrees",         "wind_gust_direction"),
    "precip_amount":       ("rainfall_amount",     "mm",              "rainfall_amount_per_time_unit"),
    "precip_rate":         ("rainfall_rate",       "mm h-1",          "instantaneous_rainfall_rate"),
}

# String/categorical time-series variables (ASOS extras).
STRING_COLUMN_MAP = {
    "precip_type":     ("precip_type",     "1", "precipitation_type_code"),
    "precip_category": ("precip_category", "1", "precipitation_category"),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_stations(stations_csv):
    """
    Return {station_id_3letter: (lat, lon, elev_m)}.
    The CSV has 4-letter ICAO ids (e.g. KJFK); the data CSV uses 3-letter (JFK).
    """
    df = pd.read_csv(stations_csv)
    out = {}
    for _, row in df.iterrows():
        sid = str(row["Station ID"]).strip()
        short = sid[1:] if len(sid) == 4 and sid.startswith("K") else sid
        out[short] = (
            float(row["Latitude"]),
            float(row["Longitude"]),
            float(row["Elevation"]),
        )
    return out


def _parse_time(series):
    """Parse 'YYYY-MM-DD HH:MM:SS' strings to UTC epoch seconds (float64)."""
    dt = pd.to_datetime(series, utc=True)
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    return (dt - epoch).dt.total_seconds().values


def _station_frame(df_station):
    """
    Given a single-station slice, return a DataFrame indexed by epoch seconds
    with canonical column names.
    """
    time_epoch = _parse_time(df_station["datetime"])

    data = {}
    for raw_col, (canonical, _u, _ln) in COLUMN_MAP.items():
        if raw_col in df_station.columns:
            data[canonical] = pd.to_numeric(df_station[raw_col], errors="coerce") \
                                .values.astype(np.float64)

    for raw_col, (canonical, _u, _ln) in STRING_COLUMN_MAP.items():
        if raw_col in df_station.columns:
            data[canonical] = df_station[raw_col].astype(object).where(
                df_station[raw_col].notna(), ""
            ).values

    out = pd.DataFrame(data, index=time_epoch)
    out.index.name = "time"
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def _write_group(out_ds, station_id, df, static, network):
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
    id_var.long_name = "asos_station_identifier"
    id_var[0] = station_id

    # Static coords
    lat, lon, elev = static
    for name, value, units, long_name in [
        ("lat",  lat,  "degrees_in_WGS84_projection", "latitude"),
        ("lon",  lon,  "degrees_in_WGS84_projection", "longitude"),
        ("elev", elev, "metres_above_sea",            "ground_elevation_above_sea_level"),
    ]:
        v = grp.createVariable(name, np.float64, ("id",))
        v.units = units
        v.long_name = long_name
        v[0] = value

    if network is not None:
        grp.network = network

    # Numeric time-series
    numeric_meta = {canon: (u, ln) for _, (canon, u, ln) in COLUMN_MAP.items()}
    for col, (units, long_name) in numeric_meta.items():
        if col not in df.columns:
            continue
        v = grp.createVariable(col, np.float64, ("id", "time"), fill_value=FILL_VALUE)
        v.units = units
        v.long_name = long_name
        v[0, :] = df[col].values.astype(np.float64)

    # String time-series
    string_meta = {canon: (u, ln) for _, (canon, u, ln) in STRING_COLUMN_MAP.items()}
    for col, (units, long_name) in string_meta.items():
        if col not in df.columns:
            continue
        v = grp.createVariable(col, str, ("id", "time"))
        v.units = units
        v.long_name = long_name
        vals = df[col].astype(str).tolist()
        for i, s in enumerate(vals):
            v[0, i] = s


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def asos_to_netcdf(input_csv, output_dir, stations_csv=DEFAULT_STATIONS_CSV):
    """
    Convert an ASOS 1-min CSV to an OpenSense-PWS-v1.0-asos netCDF4 file
    (one netCDF4 group per station).

    Parameters
    ----------
    input_csv : str
        Path to the ASOS CSV (as produced by asos_fetch.py).
    output_dir : str
        Directory for the output file. Created if absent.
    stations_csv : str, optional
        Path to ASOS_stations.csv (lat/lon/elev lookup).
        Defaults to dataset/meta/ASOS_stations.csv.

    Returns
    -------
    str
        Path to the output file.
    """
    os.makedirs(output_dir, exist_ok=True)

    print(f"Reading stations metadata: {stations_csv}")
    stations_meta = _load_stations(stations_csv)
    print(f"  {len(stations_meta)} stations in metadata")

    print(f"Reading ASOS CSV: {input_csv}")
    df = pd.read_csv(input_csv, dtype={"station_id": str})
    print(f"  {len(df):,} rows, stations: {sorted(df['station_id'].dropna().unique())}")

    stations = {}
    all_times = []
    for sid, grp_df in df.groupby("station_id", sort=True):
        if sid not in stations_meta:
            print(f"  WARNING: station {sid} not in {os.path.basename(stations_csv)} — skipped")
            continue
        sdf = _station_frame(grp_df)
        if len(sdf) == 0:
            continue
        stations[sid] = sdf
        all_times += [sdf.index.min(), sdf.index.max()]
        print(f"  {sid}: {len(sdf):,} rows  "
              f"{pd.Timestamp(sdf.index.min(), unit='s', tz='UTC').date()} → "
              f"{pd.Timestamp(sdf.index.max(), unit='s', tz='UTC').date()}")

    if not stations:
        raise RuntimeError("No usable station data found.")

    t_min = pd.Timestamp(min(all_times), unit="s", tz="UTC")
    t_max = pd.Timestamp(max(all_times), unit="s", tz="UTC")
    start_str = t_min.strftime("%Y-%m-%d")
    end_str   = t_max.strftime("%Y-%m-%d")
    out_path  = os.path.join(output_dir, f"asos_{start_str}_{end_str}.nc")

    out_ds = nc.Dataset(out_path, "w", format="NETCDF4")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_ds.title              = "NOAA ASOS 1-min Weather Data — NYC Metro Area"
    out_ds.institution        = "NOAA / Iowa Environmental Mesonet (IEM)"
    out_ds.source             = "NOAA ASOS 1-min via Iowa Environmental Mesonet (IEM)"
    out_ds.Conventions        = "OpenSense-PWS-v1.0-asos"
    out_ds.naming_convention  = "OpenSense-PWS"
    out_ds.license            = "Public domain (NOAA)"
    out_ds.reference          = "https://mesonet.agron.iastate.edu/request/asos/1min.phtml"
    out_ds.date_created       = now_str[:10]
    out_ds.start_date         = start_str
    out_ds.end_date           = end_str
    out_ds.history            = (
        f"{now_str}: Converted from {os.path.basename(input_csv)} using "
        f"asos_to_netcdf.py. Format spec: dataset/formats/netCDF_PWS.adoc; "
        f"mapping: dataset/formats/format_mapping.md."
    )
    out_ds.comment            = (
        "ASOS stations in the NYC metro area. 1-minute resolution. "
        "rainfall_amount is mm per 1-minute observation. wind_velocity in m/s, "
        "wind_direction in degrees from N. Extras beyond OpenSense PWS spec: "
        "dewpoint, wind_gust, wind_gust_direction, rainfall_rate, precip_type, "
        "precip_category. All timestamps UTC."
    )

    # Embed the precip_type → category lookup so the netCDF is self-contained.
    precip_lookup = {
        "ptype_to_category": dict(PTYPE_MAP),
        "category_descriptions": dict(PRECIP_CATEGORIES),
    }
    out_ds.precip_lookup_json = json.dumps(precip_lookup)

    # Sidecar JSON, named to match the netCDF (mirrors the WU QC pattern).
    lookup_path = os.path.join(output_dir, f"asos_{start_str}_{end_str}_precip_lookup.json")
    with open(lookup_path, "w") as f:
        json.dump(precip_lookup, f, indent=2, sort_keys=True)
    out_ds.precip_lookup_file = os.path.basename(lookup_path)

    # Try to attach a network label per group (NY_ASOS / NJ_ASOS / CT_ASOS).
    stations_df = pd.read_csv(stations_csv)
    stations_df["short"] = stations_df["Station ID"].str.replace(r"^K", "", regex=True)
    network_lookup = dict(zip(stations_df["short"], stations_df["Network"]))

    for sid, sdf in stations.items():
        _write_group(out_ds, sid, sdf, stations_meta[sid], network_lookup.get(sid))

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
        description="Convert NOAA ASOS 1-min CSV to OpenSense-PWS netCDF4.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  python asos_to_netcdf.py \\\n"
            "    dataset/raw/fetched/asos/ASOS_standard_2023-10-29_2026-04-24.csv \\\n"
            "    dataset/raw/full/outputs/"
        ),
    )
    parser.add_argument("input_csv",  help="ASOS CSV file (from asos_fetch.py)")
    parser.add_argument("output_dir", help="Output directory (created if absent)")
    parser.add_argument("--stations-csv", default=DEFAULT_STATIONS_CSV,
                        help=f"ASOS stations metadata CSV (default: {DEFAULT_STATIONS_CSV})")
    args = parser.parse_args()
    asos_to_netcdf(args.input_csv, args.output_dir, args.stations_csv)


if __name__ == "__main__":
    main()
