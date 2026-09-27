"""
Convert NYC Mesh daily device dumps (JSON in daily zips) to the raw CML netCDF
`nycmesh_data_<start>_to_<end>.nc` — dims (time, cml_id), variables rsl, rsl_remote,
rsl_60g, rsl_60g_remote (dBm, float32, zlib 4), non-dim coord device_name(cml_id).

Ported from weather_reroute/nyc_mesh/box_to_netcdf_v3_compress.py, the script that
produced dataset/raw/full/nycmesh_data_20231029_to_20260430.nc. Output format is
unchanged. Changes:
  * reads local zips by default; Box is an optional source (`--box`, needs `boxsdk`
    and clientID_box.json / token_box.json) — its folder is chosen by the date's year
    (the original was pinned to the 2024 folder);
  * no global state; metadata CSV is an argument (the original expected
    mesh_metadata_2026-05-07.csv next to the script);
  * writes where you say and never deletes it; uploading to Box is opt-in (`--upload`).

Input: one zip per day named nycmesh-data-YYYY-MM-DD.zip holding per-device JSON
files `<device>-from-<...>.json`. Fields signal, remoteSignal, signal60g,
remoteSignal60g are lists of {x: epoch ms, y: dBm} — nested under "avg" from
2024-07-16 on, flat before (the "old format"). Devices are mapped to cml_id with the
link metadata CSV (columns cml_id, rx_name, tx_name, frequency; see
`build_device_to_cml_id_mapping`); unmapped devices are dropped. When two devices
map to one cml_id their samples share it (first value wins per time) and device_name
shows the last one listed — kept as in the original so outputs stay identical.

Usage (CLI):
    python nycmesh_to_netcdf.py 2024-01-01 2024-01-07 --zip-dir DIR --metadata links.csv --out DIR
    python nycmesh_to_netcdf.py 2024-01-01 2024-01-07 --box --metadata links.csv --out DIR [--upload]
Usage (import):
    from nycmesh_to_netcdf import process_date_range
    process_date_range(start, end, metadata_csv, out_dir, zip_dir=DIR)
"""
import argparse
import datetime
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import xarray as xr

# Box folders holding the daily zips, by year; and the NetCDF output folder
BOX_RAW_FOLDERS = {"2026": "359636063260", "2025": "334907267548", "2024": "335432315383",
                   "2023": "335432315383"}
BOX_OUTPUT_FOLDER = "343758566397"

# Data up to and including this date uses the old (flat, no "avg") JSON layout
OLD_FORMAT_LAST_DAY = datetime.date(2024, 7, 15)

# NetCDF compression settings applied to all data variables
NC_ENCODING = {"zlib": True, "complevel": 4, "dtype": "float32"}

# Raw JSON field names -> NetCDF variable names
SIGNAL_FIELD_RENAME = {
    "signal": "rsl",
    "signal60g": "rsl_60g",
    "remoteSignal": "rsl_remote",
    "remoteSignal60g": "rsl_60g_remote",
}


# ============================================================================
# Device -> cml_id mapping
# ============================================================================

def build_device_to_cml_id_mapping(meta_df: pd.DataFrame) -> dict:
    """device_name (rx_name) -> cml_id.

    Per device: the rx_name row with a non-null frequency wins; if its rx rows have no
    frequency, use a tx_name row for the same device (preferring one with frequency);
    otherwise None (dropped).
    """
    mapping: dict = {}
    rx_lookup = meta_df.set_index("rx_name")
    tx_lookup = meta_df.set_index("tx_name")
    for device_name in meta_df["rx_name"].unique():
        if pd.isna(device_name):
            continue
        rx_rows = rx_lookup.loc[[device_name]] if device_name in rx_lookup.index else pd.DataFrame()
        rx_with_freq = rx_rows[rx_rows["frequency"].notna()]
        rx_without_freq = rx_rows[rx_rows["frequency"].isna()]
        if not rx_with_freq.empty:
            mapping[device_name] = rx_with_freq.iloc[0]["cml_id"]
        elif not rx_without_freq.empty:
            tx_rows = tx_lookup.loc[[device_name]] if device_name in tx_lookup.index else pd.DataFrame()
            if not tx_rows.empty:
                tx_with_freq = tx_rows[tx_rows["frequency"].notna()]
                chosen = tx_with_freq if not tx_with_freq.empty else tx_rows
                mapping[device_name] = chosen.iloc[0]["cml_id"]
            else:
                mapping[device_name] = None
        else:
            mapping[device_name] = None
    return mapping


def _invert(mapping: dict) -> dict:
    return {cml_id: dev for dev, cml_id in mapping.items() if cml_id is not None}


# ============================================================================
# Parsing
# ============================================================================

def parse_json_dir(extract_dir, mapping: dict, old_format: bool) -> list:
    """All device JSON files in `extract_dir` -> list of
    {time, device_name, cml_id, variable, value} records."""
    records = []
    for json_file in Path(extract_dir).glob("*.json"):
        with open(json_file) as f:
            data = json.load(f)
        device_name = json_file.stem.split("-from-")[0]
        cml_id = mapping.get(device_name, np.nan)
        for var_name in SIGNAL_FIELD_RENAME:
            field = data.get(var_name)
            if field is None:
                continue
            if old_format:
                points = field
            elif isinstance(field, dict) and "avg" in field:
                points = field["avg"]
            else:
                continue
            if not isinstance(points, list):
                continue
            for p in points:
                if "x" in p and "y" in p:
                    records.append({"time": pd.to_datetime(p["x"], unit="ms"), "device_name": device_name,
                                    "cml_id": cml_id, "variable": var_name, "value": p["y"]})
    return records


def records_to_dataset(records: list) -> Optional[xr.Dataset]:
    """Records -> Dataset (time, cml_id), float32, renamed variables; None if empty.
    device_name is attached later from the mapping (a single source of truth)."""
    df = pd.DataFrame(records).dropna(subset=["cml_id"])
    if df.empty:
        return None
    pivot = df.pivot_table(index=["time", "cml_id"], columns="variable", values="value", aggfunc="first")
    pivot.columns.name = None
    ds = pivot.to_xarray()
    ds = ds.rename({k: v for k, v in SIGNAL_FIELD_RENAME.items() if k in ds})
    for v in ds.data_vars:
        ds[v] = ds[v].astype(np.float32)
    return ds


def _attach_device_name(ds: xr.Dataset, cml_to_device: dict) -> xr.Dataset:
    return ds.assign_coords(device_name=("cml_id", [cml_to_device.get(c, "") for c in ds.cml_id.values]))


def append_to_netcdf(records: list, netcdf_path, cml_to_device: dict) -> bool:
    """Append one day's records to `netcdf_path`, creating it if absent.
    Concatenates on time with an outer join on cml_id (data_vars='minimal', so a
    variable missing on one day is not padded across the whole record)."""
    if not records:
        return True
    ds_new = records_to_dataset(records)
    if ds_new is None:
        print("  No mappable data in this batch, skipping.")
        return True
    netcdf_path = Path(netcdf_path)
    if netcdf_path.exists():
        ds_old = xr.load_dataset(netcdf_path)
        ds_old = ds_old.drop_vars("device_name", errors="ignore")
        ds_new = ds_new.drop_vars("device_name", errors="ignore")
        ds = xr.concat([ds_old, ds_new], dim="time", data_vars="minimal", coords="minimal", join="outer")
        ds_old.close()
        ds = _attach_device_name(ds, cml_to_device)
        encoding = {v: NC_ENCODING.copy() for v in ds.data_vars}
        tmp = netcdf_path.with_name("temp_" + netcdf_path.name)
        try:
            ds.to_netcdf(tmp, format="NETCDF4", encoding=encoding)
            ds.close()
            os.replace(tmp, netcdf_path)
        finally:
            if tmp.exists():
                tmp.unlink()
    else:
        ds = _attach_device_name(ds_new, cml_to_device)
        ds.attrs.update({"title": "NYC Mesh Signal Data",
                         "description": "Signal strength measurements from NYC Mesh network",
                         "created": datetime.datetime.now().isoformat(),
                         "history": "written by src/netCDF_converters/nycmesh_to_netcdf.py"})
        ds.to_netcdf(netcdf_path, format="NETCDF4",
                     encoding={v: NC_ENCODING.copy() for v in ds.data_vars})
        ds.close()
    return True


# ============================================================================
# Sources: local zips or Box
# ============================================================================

def _extract(zip_path: Path) -> Path:
    tmp = Path(tempfile.mkdtemp())
    out = tmp / "extracted"
    out.mkdir()
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out)
    return out


def local_day(zip_dir, day: datetime.date) -> Path:
    """Extract nycmesh-data-<day>.zip from `zip_dir`; returns the extract folder."""
    zp = Path(zip_dir) / f"nycmesh-data-{day:%Y-%m-%d}.zip"
    if not zp.exists():
        raise FileNotFoundError(f"No zip file found for date {day:%Y-%m-%d} in {zip_dir}")
    return _extract(zp)


def _box_client(creds_dir="."):
    from boxsdk import Client, OAuth2          # optional dependency: pip install boxsdk
    creds_dir = Path(creds_dir)
    cid = json.loads((creds_dir / "clientID_box.json").read_text())
    tok = json.loads((creds_dir / "token_box.json").read_text())

    def store(access_token, refresh_token):
        (creds_dir / "token_box.json").write_text(json.dumps(
            {"access_token": str(access_token), "refresh_token": str(refresh_token)}, indent=4))

    return Client(OAuth2(client_id=cid["client_id"], client_secret=cid["client_secret"],
                         access_token=tok["access_token"], refresh_token=tok["refresh_token"],
                         store_tokens=store))


def box_day(day: datetime.date, client, folders: dict = BOX_RAW_FOLDERS) -> Path:
    """Download and extract nycmesh-data-<day>.zip from the Box folder for its year."""
    folder = folders.get(str(day.year))
    if folder is None:
        raise FileNotFoundError(f"No Box folder configured for {day.year}")
    name = f"nycmesh-data-{day:%Y-%m-%d}.zip"
    for item in client.folder(folder).get_items():
        if item.name == name:
            tmp = Path(tempfile.mkdtemp())
            zp = tmp / name
            with open(zp, "wb") as f:
                client.file(item.id).get().download_to(f)
            out = _extract(zp)
            zp.unlink()
            return out
    raise FileNotFoundError(f"No zip file found for date {day:%Y-%m-%d} in Box folder {folder}")


# ============================================================================
# Driver
# ============================================================================

def process_date_range(start, end, metadata_csv, out_dir=".", *, zip_dir=None, box: bool = False,
                       box_creds_dir=".", upload: bool = False) -> Optional[Path]:
    """Convert every day in [start, end] into out_dir/nycmesh_data_<s>_to_<e>.nc.
    Source: local `zip_dir`, or Box with `box=True`. Missing days are skipped with a
    warning. Returns the output path, or None when no day had data."""
    start, end = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    if (zip_dir is None) == (not box):
        raise ValueError("give exactly one source: zip_dir=... or box=True")
    out = Path(out_dir) / f"nycmesh_data_{start:%Y%m%d}_to_{end:%Y%m%d}.nc"
    out.parent.mkdir(parents=True, exist_ok=True)
    mapping = build_device_to_cml_id_mapping(pd.read_csv(metadata_csv))
    cml_to_device = _invert(mapping)
    client = _box_client(box_creds_dir) if box or upload else None
    total = 0
    day = start
    while day <= end:
        old = day <= OLD_FORMAT_LAST_DAY
        extract_dir = None
        try:
            extract_dir = box_day(day, client) if box else local_day(zip_dir, day)
            records = parse_json_dir(extract_dir, mapping, old_format=old)
            if records:
                append_to_netcdf(records, out, cml_to_device)
                total += len(records)
            print(f"  {day} ({'old' if old else 'new'} format): {len(records):,} data points")
        except FileNotFoundError as e:
            print(f"  Warning: {e}")
        finally:
            if extract_dir is not None and extract_dir.parent.exists():
                shutil.rmtree(extract_dir.parent)
        day += datetime.timedelta(days=1)
    if total == 0:
        print("No data found for any of the specified dates")
        return None
    print(f"Wrote {out} ({total:,} data points)")
    if upload:
        client.folder(BOX_OUTPUT_FOLDER).upload(str(out))
        print(f"Uploaded to Box folder {BOX_OUTPUT_FOLDER} (local copy kept)")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("start", help="YYYY-MM-DD")
    ap.add_argument("end", nargs="?", help="YYYY-MM-DD (default: start + 6 days)")
    ap.add_argument("--metadata", required=True, help="link metadata CSV (cml_id, rx_name, tx_name, frequency)")
    ap.add_argument("--out", default=".", help="output folder (default: current)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--zip-dir", help="folder with nycmesh-data-YYYY-MM-DD.zip files")
    src.add_argument("--box", action="store_true", help="download the daily zips from Box")
    ap.add_argument("--box-creds", default=".", help="folder with clientID_box.json and token_box.json")
    ap.add_argument("--upload", action="store_true", help="also upload the result to Box")
    a = ap.parse_args()
    end = a.end or (pd.Timestamp(a.start) + pd.Timedelta(days=6)).strftime("%Y-%m-%d")
    process_date_range(a.start, end, a.metadata, a.out, zip_dir=a.zip_dir, box=a.box,
                       box_creds_dir=a.box_creds, upload=a.upload)


if __name__ == "__main__":
    main()
