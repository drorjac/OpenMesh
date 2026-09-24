"""
Scan the netCDF files in dataset/raw/full/{outputs,} and emit a unified
weather-station metadata table:

  - station_id
  - network (ASOS / PWS_WU / Mesonet)
  - subnetwork (e.g. NY_ASOS / NJ_ASOS / CT_ASOS), where known
  - lat, lon, elev
  - first_obs, last_obs (UTC)
  - n_samples (length of the time axis)
  - n_variables
  - source_file

Writes both JSON and CSV to dataset/meta/:
  - stations_full.json
  - stations_full.csv

Usage:
    python src/netCDF_converters/build_stations_metadata.py
"""

import os
import json
from pathlib import Path

import numpy as np
import pandas as pd
import netCDF4 as nc


REPO_ROOT = Path(__file__).resolve().parents[2]
FULL_DIR  = REPO_ROOT / "dataset" / "raw" / "full"
OUT_DIR   = REPO_ROOT / "dataset" / "raw" / "full" / "outputs"
META_DIR  = REPO_ROOT / "dataset" / "meta"

EPOCH_UNITS = "seconds since 1970-01-01 00:00:00 UTC"

SOURCES = [
    # (path, network_label)
    (OUT_DIR / "asos_2023-10-01_2026-04-23.nc",                       "ASOS"),
    (OUT_DIR / "pws_wu_merged_2023-10-29_2026-04-24_qc.nc",           "PWS_WU"),
    (OUT_DIR / "mesonet_2023-08-01_2026-03-04.nc",                    "Mesonet"),
]


def _static(group, name):
    if name not in group.variables:
        return None
    arr = group.variables[name][:]
    if isinstance(arr, np.ma.MaskedArray) and arr.mask.all():
        return None
    val = float(arr.flat[0])
    return None if np.isnan(val) else val


def _time_range(group):
    if "time" not in group.variables:
        return None, None, 0
    tvar = group.variables["time"]
    raw = tvar[:]
    if len(raw) == 0:
        return None, None, 0
    dates = nc.num2date(raw, tvar.units, only_use_cftime_datetimes=True)
    epoch = nc.date2num(dates, EPOCH_UNITS)
    t0 = pd.Timestamp(int(epoch.min()), unit="s", tz="UTC")
    t1 = pd.Timestamp(int(epoch.max()), unit="s", tz="UTC")
    return t0.isoformat(), t1.isoformat(), int(len(raw))


def _asos_subnetwork_lookup():
    csv = META_DIR / "ASOS_stations.csv"
    if not csv.exists():
        return {}
    df = pd.read_csv(csv)
    out = {}
    for _, row in df.iterrows():
        sid = str(row["Station ID"]).strip()
        short = sid[1:] if len(sid) == 4 and sid.startswith("K") else sid
        out[short] = row["Network"]
        out[sid]   = row["Network"]
    return out


def collect():
    asos_sub = _asos_subnetwork_lookup()
    rows = []
    for path, network in SOURCES:
        if not path.exists():
            print(f"[skip] missing {path}")
            continue
        ds = nc.Dataset(path, "r")
        for sid, g in ds.groups.items():
            t0, t1, n = _time_range(g)
            rows.append({
                "station_id":  sid,
                "network":     network,
                "subnetwork":  asos_sub.get(sid) if network == "ASOS" else None,
                "lat":         _static(g, "lat"),
                "lon":         _static(g, "lon"),
                "elev":        _static(g, "elev"),
                "first_obs":   t0,
                "last_obs":    t1,
                "n_samples":   n,
                "n_variables": len([v for v in g.variables if v not in ("time", "id")]),
                "source_file": path.name,
            })
        print(f"  {path.name:55s} → {len(ds.groups):>3d} stations")
        ds.close()
    return rows


def write(rows):
    META_DIR.mkdir(parents=True, exist_ok=True)
    json_path = META_DIR / "stations_full.json"
    csv_path  = META_DIR / "stations_full.csv"

    with open(json_path, "w") as f:
        json.dump(rows, f, indent=2, sort_keys=False)

    pd.DataFrame(rows).to_csv(csv_path, index=False)

    print(f"\nWrote {json_path}  ({len(rows)} stations)")
    print(f"Wrote {csv_path}")


def main():
    rows = collect()
    write(rows)
    df = pd.DataFrame(rows)
    print("\nPer-network counts:")
    print(df["network"].value_counts().to_string())


if __name__ == "__main__":
    main()
