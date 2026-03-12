"""
OpenMesh Setup — Standalone functions to download, load, and sample both Zenodo datasets.

Datasets:
    1. OpenMesh (wireless links + metadata + PWS sample):  Zenodo 15287692
    2. PWS Weather Underground (full ~8 months):            Zenodo 17508286

Usage:
    from OpenMesh_setup import download_all, load_links, load_pws, create_sample

    # Download both ZIPs and extract
    download_all()

    # Load wireless links
    ds_links, links_meta = load_links()

    # Load PWS (sample or full)
    pws_data = load_pws(sample=True)

    # Create a time-sliced sample of all datasets
    sample = create_sample('2024-01-15', '2024-01-30')
"""

import os
import requests
import zipfile
import tempfile
import shutil
from pathlib import Path

import xarray as xr
import pandas as pd
import netCDF4 as nc
import numpy as np
from tqdm.auto import tqdm


# =============================================================================
# Configuration
# =============================================================================

# Zenodo URLs
OPENMESH_URL = "https://zenodo.org/records/15287692/files/OpenMesh.zip?download=1"
PWS_WU_URL = "https://zenodo.org/records/17508286/files/PWS_NYC_WU.zip?download=1"

# Default paths (relative to this file → dataset/)
_DATASET_DIR = Path(__file__).resolve().parent.parent.parent  # dataset/
_ARCHIVED_DIR = _DATASET_DIR / "archived" / "openmesh"
_RAW_DIR = _DATASET_DIR / "raw" / "openmesh"
_META_DIR = _DATASET_DIR / "meta"


# =============================================================================
# Download Functions
# =============================================================================

def _download_file(url, output_path):
    """Download a file with progress bar. Skips if already exists."""
    output_path = Path(output_path)
    if output_path.exists():
        print(f"  Already exists: {output_path.name}")
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading {output_path.name}...")

    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()
    total = int(response.headers.get('content-length', 0))

    with open(output_path, 'wb') as f:
        with tqdm(total=total, unit='B', unit_scale=True, desc=output_path.name) as pbar:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    pbar.update(len(chunk))

    print(f"  Done: {output_path.name} ({output_path.stat().st_size / 1e6:.1f} MB)")
    return output_path


def download_openmesh(archive_dir=None):
    """
    Download OpenMesh.zip from Zenodo and extract:
      - *.nc  → dataset/raw/openmesh/
      - *.csv → dataset/meta/

    Returns
    -------
    dict with keys 'zip', 'nc_files', 'csv_files'
    """
    archive_dir = Path(archive_dir) if archive_dir else _ARCHIVED_DIR
    zip_path = _download_file(OPENMESH_URL, archive_dir / "OpenMesh.zip")

    # Check if already extracted
    links_file = _RAW_DIR / "ds_openmesh.nc"
    if links_file.exists():
        nc_files = list(_RAW_DIR.glob("*.nc"))
        csv_files = list(_META_DIR.glob("*.csv"))
        print(f"  Already extracted: {len(nc_files)} NetCDF, {len(csv_files)} CSV files")
        return {'zip': zip_path, 'nc_files': nc_files, 'csv_files': csv_files}

    # Extract
    _RAW_DIR.mkdir(parents=True, exist_ok=True)
    _META_DIR.mkdir(parents=True, exist_ok=True)

    nc_files, csv_files = [], []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for member in zf.namelist():
            if member.endswith('/'):
                continue
            name = Path(member).name
            data = zf.read(member)
            if name.endswith('.nc'):
                dest = _RAW_DIR / name
                dest.write_bytes(data)
                nc_files.append(dest)
            elif name.endswith('.csv'):
                dest = _META_DIR / name
                dest.write_bytes(data)
                csv_files.append(dest)

    print(f"  Extracted: {len(nc_files)} NetCDF → {_RAW_DIR}")
    print(f"  Extracted: {len(csv_files)} CSV    → {_META_DIR}")
    return {'zip': zip_path, 'nc_files': nc_files, 'csv_files': csv_files}


def download_pws_wu(archive_dir=None):
    """
    Download PWS_NYC_WU.zip from Zenodo and extract pws_wu_os.nc.

    Returns
    -------
    Path to pws_wu_os.nc
    """
    archive_dir = Path(archive_dir) if archive_dir else _ARCHIVED_DIR
    zip_path = _download_file(PWS_WU_URL, archive_dir / "PWS_NYC_WU.zip")

    output = _RAW_DIR / "pws_wu_os.nc"
    if output.exists():
        print(f"  Already extracted: {output.name}")
        return output

    _RAW_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for name in zf.namelist():
            if name.endswith("pws_wu_os.nc"):
                output.write_bytes(zf.read(name))
                print(f"  Extracted: {output.name} ({output.stat().st_size / 1e6:.1f} MB)")
                return output

    raise FileNotFoundError("pws_wu_os.nc not found in ZIP")


def download_all():
    """Download and extract both Zenodo datasets."""
    print("=" * 60)
    print("1/2  OpenMesh (wireless links + PWS sample)")
    print("=" * 60)
    download_openmesh()

    print()
    print("=" * 60)
    print("2/2  PWS Weather Underground (full dataset)")
    print("=" * 60)
    download_pws_wu()

    print()
    print("Done. Data in:")
    print(f"  NetCDF:   {_RAW_DIR}")
    print(f"  Metadata: {_META_DIR}")


# =============================================================================
# Load Functions
# =============================================================================

def load_links(raw_dir=None, meta_dir=None):
    """
    Load wireless links dataset and metadata.

    Returns
    -------
    ds_links : xarray.Dataset
        RSL time series (dims: cml_id × sublink_id × time)
    links_meta : pandas.DataFrame
        Link coordinates, frequency, polarization
    """
    raw_dir = Path(raw_dir) if raw_dir else _RAW_DIR
    meta_dir = Path(meta_dir) if meta_dir else _META_DIR

    links_file = raw_dir / "ds_openmesh.nc"
    meta_file = meta_dir / "links_metadata.csv"

    if not links_file.exists():
        raise FileNotFoundError(
            f"Links file not found: {links_file}\n"
            f"Run download_openmesh() or download_all() first."
        )

    ds = xr.open_dataset(links_file)

    links_meta = None
    if meta_file.exists():
        links_meta = pd.read_csv(meta_file)

    n_links = len(ds.cml_id)
    t0 = str(ds.time.values[0])[:10]
    t1 = str(ds.time.values[-1])[:10]
    print(f"Loaded links: {n_links} links, {len(ds.time)} timesteps ({t0} to {t1})")
    return ds, links_meta


def load_pws(sample=True, raw_dir=None, meta_dir=None):
    """
    Load PWS (Personal Weather Stations) data.

    Parameters
    ----------
    sample : bool
        True  → pws_opensense_sample_jan.nc  (January sample, from OpenMesh.zip)
        False → pws_wu_os.nc                 (full ~8 months, from PWS_NYC_WU.zip)
    raw_dir : Path, optional
    meta_dir : Path, optional

    Returns
    -------
    pws_data : dict[str, xarray.Dataset]
        Station ID → xarray Dataset with 'time' and 'rainfall_amount'
    pws_meta : pandas.DataFrame or None
        Station metadata (lat, lon, elevation)
    """
    raw_dir = Path(raw_dir) if raw_dir else _RAW_DIR
    meta_dir = Path(meta_dir) if meta_dir else _META_DIR

    filename = "pws_opensense_sample_jan.nc" if sample else "pws_wu_os.nc"
    pws_file = raw_dir / filename

    if not pws_file.exists():
        source = "download_openmesh()" if sample else "download_pws_wu()"
        raise FileNotFoundError(
            f"PWS file not found: {pws_file}\nRun {source} or download_all() first."
        )

    # Load station groups
    with nc.Dataset(pws_file, 'r') as nf:
        group_names = list(nf.groups.keys())

    pws_data = {}
    for station_id in group_names:
        ds = xr.open_dataset(pws_file, group=station_id, engine='netcdf4')
        pws_data[station_id] = _normalize_pws(ds)

    # Load metadata
    meta_file = meta_dir / "pws_metadata.csv"
    pws_meta = pd.read_csv(meta_file) if meta_file.exists() else None

    label = "sample" if sample else "full"
    print(f"Loaded PWS ({label}): {len(pws_data)} stations from {filename}")
    return pws_data, pws_meta


def _normalize_pws(ds):
    """Normalize a single-station PWS dataset: standardize time coord and rainfall var name."""
    ds = ds.copy(deep=False)

    # Normalize time coordinate
    for name in ['datetime', 't']:
        if name in ds.coords and 'time' not in ds.coords:
            ds = ds.rename({name: 'time'})
            break

    # Normalize rainfall variable
    for alias in ['precip', 'rainfall', 'precipitation', 'rainfall_mm']:
        if alias in ds.data_vars and 'rainfall_amount' not in ds.data_vars:
            ds = ds.rename({alias: 'rainfall_amount'})
            break

    return ds.squeeze()


def load_metadata(meta_dir=None):
    """
    Load all metadata files.

    Returns
    -------
    dict with keys 'links', 'pws', 'asos' (each a DataFrame or None)
    """
    meta_dir = Path(meta_dir) if meta_dir else _META_DIR
    result = {}
    for name, filename in [('links', 'links_metadata.csv'),
                           ('pws', 'pws_metadata.csv'),
                           ('asos', 'ASOS_stations.csv')]:
        path = meta_dir / filename
        result[name] = pd.read_csv(path) if path.exists() else None
    return result


# =============================================================================
# Sample Dataset (time-sliced)
# =============================================================================

def create_sample(start_date, end_date, pws_sample=True):
    """
    Load all datasets and slice to a specific time period.

    Parameters
    ----------
    start_date : str
        Start date, e.g. '2024-01-15'
    end_date : str
        End date, e.g. '2024-01-30'
    pws_sample : bool
        True = use PWS sample (January), False = use full PWS

    Returns
    -------
    dict with keys:
        'links'      : xarray.Dataset  — wireless links RSL for the period
        'links_meta' : DataFrame       — link metadata
        'pws'        : dict            — {station_id: xarray.Dataset} sliced
        'pws_meta'   : DataFrame       — PWS metadata
        'start'      : str
        'end'        : str
    """
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    # Load links
    ds_links, links_meta = load_links()
    ds_links_slice = ds_links.sel(time=slice(start, end))

    n_times = len(ds_links_slice.time)
    if n_times == 0:
        link_range = f"{str(ds_links.time.values[0])[:10]} to {str(ds_links.time.values[-1])[:10]}"
        raise ValueError(
            f"No link data in {start_date} – {end_date}. "
            f"Available range: {link_range}"
        )

    # Load PWS
    pws_data, pws_meta = load_pws(sample=pws_sample)
    pws_sliced = {}
    for sid, ds in pws_data.items():
        if 'time' in ds.coords:
            sliced = ds.sel(time=slice(start, end))
            if len(sliced.time) > 0:
                pws_sliced[sid] = sliced

    print(f"\nSample period: {start_date} to {end_date}")
    print(f"  Links: {len(ds_links_slice.cml_id)} links, {n_times} timesteps")
    print(f"  PWS:   {len(pws_sliced)}/{len(pws_data)} stations with data in period")

    return {
        'links': ds_links_slice,
        'links_meta': links_meta,
        'pws': pws_sliced,
        'pws_meta': pws_meta,
        'start': start_date,
        'end': end_date,
    }


# =============================================================================
# Quick Summary
# =============================================================================

def print_summary(ds_links=None, pws_data=None):
    """Print a quick summary of loaded datasets."""
    print("=" * 60)
    print("OpenMesh Dataset Summary")
    print("=" * 60)

    if ds_links is not None:
        t0 = str(ds_links.time.values[0])[:19]
        t1 = str(ds_links.time.values[-1])[:19]
        res = pd.Timedelta(ds_links.time.diff('time').median().values)
        print(f"\nWireless Links:")
        print(f"  Links:      {len(ds_links.cml_id)}")
        print(f"  Sublinks:   {len(ds_links.sublink_id)}")
        print(f"  Timesteps:  {len(ds_links.time):,}")
        print(f"  Period:     {t0} → {t1}")
        print(f"  Resolution: {res}")
        print(f"  Variable:   rsl (Received Signal Level, dBm)")

    if pws_data is not None:
        stations = list(pws_data.keys())
        n = len(stations)
        # Get time range from first station
        ds0 = pws_data[stations[0]]
        if 'time' in ds0.coords and len(ds0.time) > 0:
            t0 = str(ds0.time.values[0])[:19]
            t1 = str(ds0.time.values[-1])[:19]
            print(f"\nPersonal Weather Stations:")
            print(f"  Stations:   {n}")
            print(f"  Period:     {t0} → {t1}")
            rain_var = 'rainfall_amount' if 'rainfall_amount' in ds0 else list(ds0.data_vars)[0]
            print(f"  Variable:   {rain_var}")

    print("=" * 60)
