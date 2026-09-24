"""
Merge N OpenSense-PWS-v1.0 netCDF4 files (group-per-station convention).

All files must follow the OpenSense-PWS format:
  - One netCDF4 group per station
  - Dimensions: id (size 1), time
  - Required variables: time, id, lat, lon, rainfall_amount

Merge behaviour:
  - Station union: all stations from any file included
  - Overlap: later file in the list wins (keep-last)
  - Variable union: NaN-fill segments where a file lacks a variable
  - rainfall_rate: unified name for rainfall_rate / precip_rate_calculated

Usage (CLI):
    python merge_pws_opensense.py <file1> <file2> [<file3> ...] <output_dir>

Usage (import):
    from merge_pws_opensense import merge_opensense_pws
    merge_opensense_pws([file1, file2, file3], output_dir)
"""

import os
import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import netCDF4 as nc


EPOCH_UNITS = "seconds since 1970-01-01 00:00:00 UTC"

# Rename on read: source variable name -> canonical name
RENAME = {
    "precip_rate_calculated": "rainfall_rate",
}

# Coordinate variables (static per station, stored on the id dimension)
STATIC_VARS = {"lat", "lon", "elev"}

# Canonical units per variable (OpenSense PWS convention) — fallback when
# the source variable has no units attribute. Source attrs take precedence.
UNITS = {
    "rainfall_amount":   "mm",
    "rainfall_rate":     "mm h-1",
    "precip_rate":       "mm h-1",
    "temperature":       "degrees_celsius",
    "dew_point":         "degrees_celsius",
    "relative_humidity": "%",
    "wind_velocity":     "ms-1",
    "wind_gust":         "ms-1",
    "wind_direction":    "degrees",
    "air_pressure":      "hPa",
    "uv_index":          "",
    "solar_radiation":   "W m-2",
    "condition":         "",
}

# Variables stored as NC_STRING (not numeric)
STRING_VARS = {"condition"}

FILL_VALUE = np.float64(9.96921e+36)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_epoch(time_var):
    """Convert any netCDF4 time variable to a float64 array of UTC epoch seconds."""
    dates = nc.num2date(time_var[:], time_var.units,
                        only_use_cftime_datetimes=True)
    return nc.date2num(dates, EPOCH_UNITS).astype(np.float64)


def _get_static(group):
    """Return {lat, lon, elev} as floats from a station group (any present)."""
    static = {}
    for vname in STATIC_VARS:
        if vname in group.variables:
            arr = group.variables[vname][:]
            static[vname] = float(arr.flat[0])
    return static


def _get_var_attrs(group):
    """Return {canonical_name: attrs_dict} for all time-series variables in group."""
    attrs = {}
    for vname, var in group.variables.items():
        if vname in ("time", "id") or vname in STATIC_VARS:
            continue
        canonical = RENAME.get(vname, vname)
        attrs[canonical] = {k: getattr(var, k) for k in var.ncattrs()}
    return attrs


def _group_to_df(group):
    """
    Convert a station group to a DataFrame indexed by UTC epoch seconds.
    Columns are canonical variable names (RENAME applied).
    """
    time_epoch = _to_epoch(group.variables["time"])

    data = {}
    for vname, var in group.variables.items():
        if vname in ("time", "id") or vname in STATIC_VARS:
            continue

        canonical = RENAME.get(vname, vname)
        raw = var[:]

        # (id, time) shape → strip id dimension
        if raw.ndim == 2:
            raw = raw[0]

        if isinstance(raw, np.ma.MaskedArray):
            if canonical in STRING_VARS:
                raw = raw.filled("")
            else:
                raw = raw.filled(np.nan)

        data[canonical] = raw

    df = pd.DataFrame(data, index=time_epoch)
    df.index.name = "time"
    return df


def _merge_groups(groups):
    """
    Merge N station groups for the same station ID, in priority order:
    later entries in `groups` win on any overlapping timestamps (keep-last).

    Returns (merged_df, static_dict, var_attrs_dict).
    """
    dfs = [_group_to_df(g) for g in groups]

    # For each df, drop rows whose timestamps appear in any later df.
    pruned = []
    for i, df in enumerate(dfs):
        later_times = set()
        for later in dfs[i + 1:]:
            later_times |= set(later.index)
        pruned.append(df.loc[~df.index.isin(later_times)] if later_times else df)

    merged = pd.concat(pruned).sort_index() if pruned else pd.DataFrame()

    # Static coords + var attrs: later groups overwrite earlier ones.
    static = {}
    var_attrs = {}
    for g in groups:
        static.update(_get_static(g))
        var_attrs.update(_get_var_attrs(g))

    return merged, static, var_attrs


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def _write_group(out_ds, station_id, df, static, var_attrs):
    """Write one merged station into a new group in out_ds."""
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
    _STATIC_META = {
        "lat":  ("degrees_in_WGS84_projection", "latitude"),
        "lon":  ("degrees_in_WGS84_projection", "longitude"),
        "elev": ("metres_above_sea",             "ground_elevation_above_sea_level"),
    }
    for vname, (units, long_name) in _STATIC_META.items():
        if vname in static:
            v = grp.createVariable(vname, np.float64, ("id",))
            v.units = units
            v.long_name = long_name
            v[0] = static[vname]

    # Time-series variables
    for col in df.columns:
        is_string = col in STRING_VARS or df[col].dtype == object

        if is_string:
            v = grp.createVariable(col, str, ("id", "time"))
            vals = df[col].fillna("").astype(str).tolist()
            for i, s in enumerate(vals):
                v[0, i] = s
        else:
            v = grp.createVariable(col, np.float64, ("id", "time"),
                                   fill_value=FILL_VALUE)
            v[0, :] = df[col].values.astype(np.float64)

        # Attributes: from source files, then ensure units
        for k, val in var_attrs.get(col, {}).items():
            if k != "_FillValue":
                setattr(v, k, val)
        if not hasattr(v, "units") and col in UNITS:
            v.units = UNITS[col]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def merge_opensense_pws(files, output_dir):
    """
    Merge N OpenSense-PWS-v1.0 netCDF4 files into one.

    Parameters
    ----------
    files : list[str]
        Paths to input files in priority order — later files win on overlap.
        Must contain at least one path.
    output_dir : str
        Directory for the output file. Created if absent.

    Returns
    -------
    str
        Path to the output file.
    """
    if isinstance(files, (str, bytes)) or len(files) < 1:
        raise ValueError("merge_opensense_pws expects a list of >= 1 file paths")

    os.makedirs(output_dir, exist_ok=True)

    datasets = [nc.Dataset(f, "r") for f in files]
    station_sets = [set(ds.groups.keys()) for ds in datasets]
    all_stations = sorted(set().union(*station_sets))

    for f, s in zip(files, station_sets):
        print(f"{os.path.basename(f)}: {len(s)} stations")
    print(f"Union: {len(all_stations)} stations total")

    # Stations present in each pairwise/N-wise intersection — just a quick summary
    in_all = sorted(set.intersection(*station_sets)) if station_sets else []
    print(f"  in all inputs : {len(in_all)}")
    for i, (f, s) in enumerate(zip(files, station_sets)):
        others = set().union(*(station_sets[:i] + station_sets[i + 1:])) if len(station_sets) > 1 else set()
        only = sorted(s - others)
        print(f"  only in {os.path.basename(f)} : {len(only)}")

    # --- Merge all station groups ---
    groups_out = {}
    all_times = []

    for sid in all_stations:
        present_groups = [ds.groups[sid] for ds in datasets if sid in ds.groups]
        df, static, var_attrs = _merge_groups(present_groups)
        groups_out[sid] = (df, static, var_attrs)
        if len(df):
            all_times += [df.index.min(), df.index.max()]

    # --- Build output filename from overall time range ---
    t_start = nc.num2date(min(all_times), EPOCH_UNITS)
    t_end   = nc.num2date(max(all_times), EPOCH_UNITS)
    start_str = f"{t_start.year:04d}-{t_start.month:02d}-{t_start.day:02d}"
    end_str   = f"{t_end.year:04d}-{t_end.month:02d}-{t_end.day:02d}"
    out_path = os.path.join(output_dir, f"pws_wu_merged_{start_str}_{end_str}.nc")

    # --- Write output ---
    out_ds = nc.Dataset(out_path, "w", format="NETCDF4")

    # Global attributes: each input overwrites previous (last file wins).
    for ds in datasets:
        for k in ds.ncattrs():
            setattr(out_ds, k, getattr(ds, k))

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_ds.title = "Weather Underground PWS Data — Merged"
    out_ds.Conventions = "OpenSense-PWS-v1.0"
    out_ds.date_created = now_str[:10]
    out_ds.start_date = start_str
    out_ds.end_date = end_str
    sources = ", ".join(f"'{os.path.basename(f)}'" for f in files)
    out_ds.history = (
        f"{now_str}: Merged {len(files)} files: {sources} "
        f"via merge_pws_opensense.py "
        f"(overlap policy: keep-last / later file wins)."
    )

    for sid, (df, static, var_attrs) in groups_out.items():
        _write_group(out_ds, sid, df, static, var_attrs)

    for ds in datasets:
        ds.close()
    out_ds.close()

    size_mb = os.path.getsize(out_path) / 1e6
    print(f"\nWrote : {out_path}")
    print(f"Period: {start_str} → {end_str}")
    print(f"Groups: {len(all_stations)} stations")
    print(f"Size  : {size_mb:.1f} MB")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Merge N OpenSense-PWS-v1.0 netCDF4 files (later wins on overlap).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  python merge_pws_opensense.py \\\n"
            "    dataset/raw/full/pws_wu_os.nc \\\n"
            "    dataset/raw/full/pws_wu_network.nc \\\n"
            "    dataset/raw/full/pws_data_new.nc \\\n"
            "    dataset/raw/full/outputs/"
        ),
    )
    parser.add_argument(
        "paths", nargs="+",
        help="Two or more input files followed by the output directory. "
             "Files are in priority order; the last file wins on overlap.",
    )
    args = parser.parse_args()
    if len(args.paths) < 3:
        parser.error("need at least two input files and one output directory")
    *input_files, output_dir = args.paths
    merge_opensense_pws(input_files, output_dir)


if __name__ == "__main__":
    main()
