"""
Utilities for loading and merging OpenSense netCDF files.

Supported formats
-----------------
flat (id, time)         — ASOS (e.g. asos_nyc_network.nc)
grouped per-station     — PWS  (e.g. pws_wu_network.nc)
"""

import glob
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import netCDF4 as nc4


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_pws_grouped(nc_path, verbose=True):
    """
    Load all groups from a grouped PWS netCDF4 file.

    Parameters
    ----------
    nc_path : str or Path
    verbose : bool

    Returns
    -------
    dict {station_id: xr.Dataset}
        Only groups that have a non-empty 'time' dimension are included.
    """
    nc_path = Path(nc_path)
    data = {}
    with nc4.Dataset(nc_path, 'r') as f:
        groups = list(f.groups.keys())
        # Root-level condition code→string lookup (WU merged files), if present.
        cond_lookup = None
        if 'condition_lookup_json' in f.ncattrs():
            try:
                import json
                cond_lookup = {int(k): v for k, v
                               in json.loads(f.condition_lookup_json).items()}
            except Exception:
                cond_lookup = None

    for sid in groups:
        try:
            ds = xr.open_dataset(nc_path, group=sid, engine='netcdf4')
            if 'time' in ds.sizes and ds.sizes['time'] > 0:
                if cond_lookup is not None and 'condition' in ds:
                    ds.attrs['condition_lookup'] = cond_lookup
                data[sid] = ds
        except Exception:
            pass

    if verbose:
        print(f"  Loaded: {nc_path.name} → {len(data)} stations")
    return data


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Station-level attributes that are constant per station (not time-varying).
# Across the two PWS files these names can appear as a coordinate in one group
# and as a data variable in another, causing xr.concat to raise a ValueError.
_STATION_SCALAR_VARS = {'elev', 'lat', 'lon', 'id'}


def _normalize_for_concat(ds):
    """
    Strip known station-level attributes from a Dataset before xr.concat.

    Problem: in pws_wu_os.nc 'elev' is stored as a coordinate (shape (1,),
    dim='id'), while in pws_wu_network.nc 'elev' is stored as a data variable
    (shape (1,)).  xr.concat raises ValueError when the same name is a coord
    in some datasets and a data var in others.

    This function drops 'elev', 'lat', 'lon', 'id' from wherever they live
    (data_vars or coords) and returns their scalar values so they can be
    re-attached after concat.

    Returns
    -------
    (clean_ds, saved_dict)
        clean_ds   : Dataset with station scalars removed
        saved_dict : {name: float} — pass to ds.assign_coords() after concat
    """
    saved = {}
    to_drop = []

    # Strip from data_vars (e.g. pws_wu_network.nc stores elev here)
    for name in _STATION_SCALAR_VARS:
        if name in ds.data_vars:
            try:
                saved[name] = float(ds[name].values.flat[0])
            except Exception:
                pass
            to_drop.append(name)

    # Strip from non-dimension coordinates (e.g. pws_wu_os.nc stores elev here)
    for name in list(ds.coords):
        if name in ds.dims:
            continue
        if name in _STATION_SCALAR_VARS and name not in to_drop:
            try:
                saved[name] = float(ds.coords[name].values.flat[0])
            except Exception:
                pass
            to_drop.append(name)

    clean = ds.drop_vars(to_drop, errors='ignore')
    return clean, saved


# ---------------------------------------------------------------------------
# Flat ASOS merge
# ---------------------------------------------------------------------------

def merge_flat_asos(file1, file2, output_path=None, verbose=True):
    """
    Merge two flat (id, time) ASOS netCDF files by station ID.

    Handles same-station and partial-overlap cases (union of station sets).
    Duplicate timestamps are deduplicated (first occurrence kept) and the
    result is sorted chronologically.

    Parameters
    ----------
    file1, file2 : str or Path
    output_path  : str or Path, optional
        If given, saves the merged dataset (zlib-compressed, level 4).
    verbose : bool

    Returns
    -------
    xr.Dataset  with dims (id, time)
    """
    file1, file2 = Path(file1), Path(file2)
    ds1 = xr.open_dataset(file1)
    ds2 = xr.open_dataset(file2)

    ids1 = list(ds1.id.values.astype(str))
    ids2 = list(ds2.id.values.astype(str))
    all_ids = sorted(set(ids1) | set(ids2))

    if verbose:
        t0_1, t1_1 = pd.to_datetime(ds1.time.values[[0, -1]])
        t0_2, t1_2 = pd.to_datetime(ds2.time.values[[0, -1]])
        print(f"File 1: {file1.name}  stations={ids1}  {t0_1.date()}→{t1_1.date()}")
        print(f"File 2: {file2.name}  stations={ids2}  {t0_2.date()}→{t1_2.date()}")
        print(f"Union : {all_ids}")

    # Per-station merge along time
    merged_per_station = {}
    for sid in all_ids:
        parts = []
        if sid in ids1:
            parts.append(ds1.sel(id=sid))
        if sid in ids2:
            parts.append(ds2.sel(id=sid))
        if len(parts) == 1:
            merged_per_station[sid] = parts[0]
        else:
            combined = xr.concat(parts, dim='time')
            _, idx = np.unique(combined.time, return_index=True)
            merged_per_station[sid] = combined.isel(time=idx).sortby('time')

    # Build unified time axis (union of all stations).
    # np.unique on the concatenated datetime64 array is ~100x faster than
    # building a Python set of Timestamp objects for multi-million-step inputs.
    all_times = pd.DatetimeIndex(np.unique(np.concatenate(
        [ds.time.values for ds in merged_per_station.values()]
    )))

    ref_ds = ds1 if ds1.data_vars else ds2
    all_vars = list(ref_ds.data_vars)

    # Reindex each station to the common time axis (NaN-fill gaps)
    data_arrays = {}
    for vname in all_vars:
        arrays = []
        attrs = ref_ds[vname].attrs
        for sid in all_ids:
            if sid in merged_per_station and vname in merged_per_station[sid]:
                arr = merged_per_station[sid][vname].reindex(time=all_times).values
            else:
                arr = np.full(len(all_times), np.nan)
            arrays.append(arr)
        data_arrays[vname] = xr.DataArray(
            np.array(arrays, dtype=float), dims=['id', 'time'], attrs=attrs
        )

    def _scalar(sid, coord):
        for ds in [ds1, ds2]:
            if sid in ds.id.values.astype(str):
                v = ds.sel(id=sid)[coord]
                return float(v) if v.ndim == 0 else float(v.values.flat[0])
        return np.nan

    merged_ds = xr.Dataset(
        data_arrays,
        coords={
            'id'  : np.array(all_ids),
            'time': all_times,
            'lat' : ('id', [_scalar(s, 'lat')  for s in all_ids]),
            'lon' : ('id', [_scalar(s, 'lon')  for s in all_ids]),
            'elev': ('id', [_scalar(s, 'elev') for s in all_ids]),
        },
        attrs={**ref_ds.attrs, 'merged_from': f"{file1.name} + {file2.name}"},
    )

    if verbose:
        t0 = pd.Timestamp(merged_ds.time.values[0])
        t1 = pd.Timestamp(merged_ds.time.values[-1])
        print(f"\nMerged → {len(all_ids)} stations, {len(all_times):,} steps  "
              f"({t0.date()}→{t1.date()})")

    if output_path:
        enc = {v: {'zlib': True, 'complevel': 4} for v in data_arrays}
        merged_ds.to_netcdf(output_path, encoding=enc)
        if verbose:
            print(f"Saved: {output_path}")

    return merged_ds


# ---------------------------------------------------------------------------
# Grouped PWS merge + save
# ---------------------------------------------------------------------------

def save_grouped_pws(merged_dict, output_path, verbose=True):
    """
    Write a {station_id: xr.Dataset} dict to a grouped netCDF4 file.

    Output follows OpenSense-PWS-v1.0 conventions:
    one group per station, dims=(id=1, time=N).

    Parameters
    ----------
    merged_dict : dict {str: xr.Dataset}
    output_path : str or Path
    verbose     : bool
    """
    output_path = Path(output_path)
    epoch = np.datetime64('1970-01-01T00:00:00')

    with nc4.Dataset(output_path, 'w', format='NETCDF4') as root:
        root.Conventions = 'OpenSense-PWS-v1.0'
        root.source      = 'save_grouped_pws (netcdf_utils.py)'
        for sid, ds in merged_dict.items():
            grp = root.createGroup(sid)
            grp.createDimension('time', len(ds.time))
            grp.createDimension('id', 1)

            tv           = grp.createVariable('time', 'f8', ('time',))
            tv.units     = 'seconds since 1970-01-01 00:00:00 UTC'
            tv.calendar  = 'standard'
            tv[:]        = (ds.time.values.astype('datetime64[s]') - epoch).astype(float)

            for vname in ds.data_vars:
                arr  = ds[vname].values
                dims = ('id', 'time') if arr.ndim == 2 else ('time',)
                v = grp.createVariable(vname, 'f4', dims,
                                       zlib=True, complevel=4,
                                       fill_value=np.float32(np.nan))
                for k, val in ds[vname].attrs.items():
                    setattr(v, k, val)
                v[:] = arr

    if verbose:
        print(f"Saved: {output_path}  ({output_path.stat().st_size / 1e6:.1f} MB)")


def _find_latest(output_dir, pattern):
    """Return the most recently modified file matching glob pattern, or None."""
    matches = glob.glob(str(Path(output_dir) / pattern))
    return Path(max(matches, key=lambda p: Path(p).stat().st_mtime)) if matches else None


def load_full_weather_data(full_dir=None, verbose=True):
    """
    Load all full-period compiled weather datasets.

    Looks in dataset/raw/full/ for the ASOS network file and in
    dataset/raw/full/outputs/ for the latest WU-merged and mesonet files.

    Parameters
    ----------
    full_dir : str or Path, optional
        Path to dataset/raw/full/. Defaults to the standard project location.
    verbose : bool

    Returns
    -------
    dict with keys:
        'asos'    : xr.Dataset               flat (id, time) — ASOS stations
        'pws'     : dict {sid: xr.Dataset}   WU PWS merged groups
        'mesonet' : dict {sid: xr.Dataset}   NY Mesonet groups
    Any key is None if its file is not found.
    """
    if full_dir is None:
        full_dir = Path(__file__).parent.parent.parent / 'dataset' / 'raw' / 'full'
    full_dir    = Path(full_dir)
    outputs_dir = full_dir / 'outputs'

    result = {'asos': None, 'pws': None, 'mesonet': None}

    # --- ASOS (flat) ---
    asos_path = full_dir / 'asos_nyc_network.nc'
    if asos_path.exists():
        result['asos'] = xr.open_dataset(asos_path, engine='netcdf4')
        if verbose:
            ds = result['asos']
            ids   = list(ds.id.values.astype(str))
            t0, t1 = pd.Timestamp(ds.time.values[0]), pd.Timestamp(ds.time.values[-1])
            print(f"  ASOS    : {len(ids)} stations  {t0.date()} → {t1.date()}"
                  f"  ({ds.sizes['time']:,} steps)")
    else:
        if verbose:
            print(f"  ASOS    : NOT FOUND ({asos_path})")

    # --- WU PWS merged (grouped) ---
    pws_path = _find_latest(outputs_dir, 'pws_wu_merged_*.nc')
    if pws_path:
        result['pws'] = load_pws_grouped(pws_path, verbose=False)
        if verbose:
            n = len(result['pws'])
            print(f"  PWS     : {n} stations  [{pws_path.name}]")
    else:
        if verbose:
            print(f"  PWS     : NOT FOUND (no pws_wu_merged_*.nc in {outputs_dir})")

    # --- Mesonet (grouped, same format as PWS) ---
    meso_path = _find_latest(outputs_dir, 'mesonet_*.nc')
    if meso_path:
        result['mesonet'] = load_pws_grouped(meso_path, verbose=False)
        if verbose:
            n   = len(result['mesonet'])
            sid = list(result['mesonet'].keys())
            print(f"  Mesonet : {n} stations {sid}  [{meso_path.name}]")
    else:
        if verbose:
            print(f"  Mesonet : NOT FOUND (no mesonet_*.nc in {outputs_dir})")

    return result


def merge_grouped_pws(file1, file2, output_path=None, verbose=True):
    """
    Merge two grouped PWS netCDF4 files by station name.

    For stations present in both files: concatenates time axes, removes
    duplicate timestamps (first kept), sorts chronologically.
    For stations in only one file: kept as-is.

    Handles the case where 'elev' (and other scalar coords) appear as
    coordinates in some groups and as data variables in others, which
    would otherwise cause xr.concat to raise a ValueError.

    Parameters
    ----------
    file1, file2 : str or Path
    output_path  : str or Path, optional
        If given, writes a grouped netCDF4 file via save_grouped_pws().
    verbose : bool

    Returns
    -------
    dict {station_id: xr.Dataset}
    """
    file1, file2 = Path(file1), Path(file2)

    with nc4.Dataset(file1) as f1, nc4.Dataset(file2) as f2:
        groups1 = set(f1.groups.keys())
        groups2 = set(f2.groups.keys())

    all_group_ids = sorted(groups1 | groups2)

    if verbose:
        print(f"File 1: {file1.name} — {len(groups1)} groups")
        print(f"File 2: {file2.name} — {len(groups2)} groups")
        print(f"Union : {len(all_group_ids)} unique stations  "
              f"(shared={len(groups1 & groups2)}, "
              f"only-1={len(groups1 - groups2)}, "
              f"only-2={len(groups2 - groups1)})")

    merged = {}
    for sid in all_group_ids:
        parts = []
        for fpath, gset in [(file1, groups1), (file2, groups2)]:
            if sid in gset:
                try:
                    ds = xr.open_dataset(fpath, group=sid, engine='netcdf4')
                    if 'time' in ds.sizes and ds.sizes['time'] > 0:
                        parts.append(ds)
                except Exception:
                    pass

        if not parts:
            continue
        if len(parts) == 1:
            merged[sid] = parts[0]
        else:
            # Normalise each part: remove station-level attrs that live in
            # different places (coord vs data_var) across the two files.
            clean_parts, saved_scalars = [], {}
            for p in parts:
                clean, scalars = _normalize_for_concat(p)
                clean_parts.append(clean)
                saved_scalars.update(scalars)

            combined = xr.concat(clean_parts, dim='time')
            _, idx    = np.unique(combined.time, return_index=True)
            result    = combined.isel(time=idx).sortby('time')

            if saved_scalars:
                result = result.assign_coords(saved_scalars)
            merged[sid] = result

    if verbose:
        total_obs = sum(ds.dims['time'] for ds in merged.values())
        all_t     = np.concatenate([ds.time.values for ds in merged.values()])
        print(f"\nMerged → {len(merged)} stations, {total_obs:,} total obs  "
              f"({pd.Timestamp(all_t.min()).date()}→{pd.Timestamp(all_t.max()).date()})")

    if output_path:
        save_grouped_pws(merged, output_path, verbose=verbose)

    return merged
