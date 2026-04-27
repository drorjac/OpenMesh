"""
pws_loader.py - Load OpenMesh PWS NetCDF groups into xarray.
"""
from __future__ import annotations
from pathlib import Path
import netCDF4 as nc
import numpy as np
import pandas as pd
import xarray as xr

PWS_RAIN_VAR = "rainfall_amount"


def load_pws_file(
    pws_path: Path | str,
    meta_path: Path | str | None = None,
) -> tuple[nc.Dataset, pd.DataFrame]:
    """Open PWS NetCDF4 group file and load station metadata."""
    pws_path = Path(pws_path)
    ds_pws_nc = nc.Dataset(str(pws_path), "r")

    if meta_path is not None:
        meta_path = Path(meta_path)
        if not meta_path.exists():
            print(f"WARNING: pws_metadata.csv not found at {meta_path}")
            meta_path = None
    else:
        candidates = [
            pws_path.parent / "pws_metadata.csv",
            pws_path.parent.parent / "pws_metadata.csv",
            *list(pws_path.parent.parent.rglob("pws_metadata.csv")),
        ]
        meta_path = next((p for p in candidates if p.exists()), None)

    if meta_path is not None:
        pws_meta = pd.read_csv(meta_path)
        print(f"PWS metadata : {len(pws_meta)} stations  <- {meta_path.name}")
    else:
        pws_meta = pd.DataFrame()
        print("WARNING: pws_metadata.csv not found - coordinates will be NaN.")

    print(f"PWS file : {len(ds_pws_nc.groups)} station groups  <- {pws_path.name}")
    return ds_pws_nc, pws_meta


def read_pws_groups(ds_nc: nc.Dataset) -> dict[str, xr.Dataset]:
    """Convert netCDF4 group-per-station PWS file to dict of xarray Datasets."""
    pws_data: dict[str, xr.Dataset] = {}
    for station_id in ds_nc.groups.keys():
        try:
            station_ds = xr.open_dataset(
                ds_nc.filepath(), group=station_id, engine="netcdf4"
            )
            pws_data[station_id] = station_ds
        except Exception as exc:
            print(f"  Could not load {station_id}: {exc}")
    print(f"Loaded {len(pws_data)} PWS stations.")
    return pws_data


def stack_pws_to_dataset(
    pws_dict: dict[str, xr.Dataset],
    pws_meta: pd.DataFrame,
    var: str = PWS_RAIN_VAR,
) -> xr.Dataset:
    """Stack per-station PWS dict into a single (id, time) xr.Dataset."""
    all_times = sorted({
        t for ds in pws_dict.values()
        for t in pd.DatetimeIndex(ds.time.values)
    })
    time_index = pd.DatetimeIndex(all_times)
    station_ids = list(pws_dict.keys())

    rain_arr = np.full((len(station_ids), len(time_index)), np.nan)
    for i, sid in enumerate(station_ids):
        vals = pws_dict[sid][var].to_series()
        vals = vals[~vals.index.duplicated(keep="first")]
        rain_arr[i] = vals.reindex(time_index).values

    lons, lats = [], []
    for sid in station_ids:
        if not pws_meta.empty:
            row = pws_meta[pws_meta["Station ID"].str.upper() == sid.upper()]
            lons.append(float(row["Longitude"].values[0]) if len(row) else np.nan)
            lats.append(float(row["Latitude"].values[0])  if len(row) else np.nan)
        else:
            lons.append(np.nan)
            lats.append(np.nan)

    return xr.Dataset(
        {var: (["id", "time"], rain_arr, {"units": "mm", "long_name": "rainfall amount"})},
        coords={
            "id" : (["id"], station_ids),
            "time": (["time"], time_index),
            "lon" : (["id"], lons),
            "lat" : (["id"], lats),
        },
        attrs={"source": "Weather Underground PWS via OpenMesh dataset"},
    )
