"""
Which OpenMesh dataset the repo reads: v1 (default, the ESSD record) or v2 (Zenodo 2.0.0).

    from analysis import datasets as D
    D.use('v2')              # switch every loader in the repo to Zenodo v2
    D.paths()                # the files of the active dataset
    ds = D.open_cml()        # its CML file, in one standard shape

The two datasets
----------------
v1 (default) — the ESSD record, public, 2023-10-29 → 2024-07-01, under dataset/raw/openmesh/:
    ds_openmesh.nc                   CML, 75 CMLs / 103 sublinks, 1 min, Zenodo 15287692
                                     (OpenMesh.zip; src/fetch_data/OpenMesh/openmesh.py)
    pws_wu_os.nc                     WU PWS, 37 stations, Zenodo 17508286 (PWS_NYC_WU.zip, optional)
    derived/asos_v1.nc             ASOS 1 min of one window, fetched from the public IEM API by
                                     `fetch_v1_asos(start, end)` (src/fetch_data/noaa_asos)
    derived/                         CML attenuation baselines of that window
                                     (python src/analysis/cml_baseline.py --dataset v1 --window …)
  v1 has no Mesonet, no airport WU file and no GHCN daily file.
v2 — Zenodo record 2.0.0 (https://doi.org/10.5281/zenodo.23283445), public, unpacked under
     dataset/raw/openmesh_v2/ (see `install_v2`):
    data/links/openmesh_links.nc     OpenSense CML, 359 CMLs / 732 sublinks, 2023-10-29 → 2026-05-31
    data/weather/asos/               5 ASOS stations, 1 min (OpenSense PWS, flat id × time)
    data/weather/ghcn/               7 GHCN-Daily stations
    data/weather/radar/              10 MRMS days
  v2 has no WU PWS or Mesonet: loaders return those networks empty.
'local': the maintainers' working files; not distributed.

Choosing
--------
The active dataset is, in order: `use(name)` in this session, else the environment
variable OPENMESH_DATASET, else 'v1'. Every loader that takes `dataset=None` follows it,
so a notebook switches with one knob. Folder overrides: OPENMESH_V1_DIR (the folder of
the v1 files, default dataset/raw/openmesh) and OPENMESH_V2_DIR (default
dataset/raw/openmesh_v2).

The CML files differ (ids, link count, sampling, variable names); `open_cml`,
`signal_level` and `sublink_table` hide that, so code written against one runs on the
other. cml_ids are not shared between the datasets: v1 '6' and v2 '6' are different paths.
"""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Dict, Optional, Union

import numpy as np
import pandas as pd
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ('v1', 'v2')                  # the distributed datasets
DATASETS = PUBLIC + ('local',)         # 'local': the maintainers' working files; not distributed
DEFAULT = 'v1'
V1_DOI = 'https://doi.org/10.5281/zenodo.15287692'
V1_PWS_DOI = 'https://doi.org/10.5281/zenodo.17508286'
V2_DOI = 'https://doi.org/10.5281/zenodo.23283445'
V1_PERIOD = ('2023-10-29', '2024-07-01')            # span of ds_openmesh.nc (UTC)
V1_ASOS_STATIONS = ('EWR', 'JFK', 'LGA', 'NYC', 'TEB')    # the 5 ASOS stations of v1 / v2
ESSD_PERIOD, ESSD_ASOS_STATIONS = V1_PERIOD, V1_ASOS_STATIONS   # old names

_active: Optional[str] = None

PathLike = Union[str, Path]


# ============================================================================
# Choosing the dataset
# ============================================================================

def use(name: str) -> str:
    """Make `name` ('v1' or 'v2') the dataset of every loader in this session."""
    global _active
    _active = _check(name)
    return _active


def active() -> str:
    """The dataset loaders read when not told otherwise."""
    return _active or _check(os.environ.get('OPENMESH_DATASET', DEFAULT))


def resolve(dataset: Optional[str] = None) -> str:
    """`dataset` if given, else the active one."""
    return _check(dataset) if dataset else active()


def _check(name: str) -> str:
    name = str(name).lower().strip()
    name = {'essd': 'v1'}.get(name, name)         # old name of v1, still accepted
    if name not in DATASETS:
        raise ValueError(f"dataset must be one of {PUBLIC}, got {name!r}")
    return name


def is_name(source) -> bool:
    """True when `source` names a dataset (rather than being a file path)."""
    if not isinstance(source, str):
        return False
    try:
        _check(source)
        return True
    except ValueError:
        return False


# ============================================================================
# Files
# ============================================================================

@dataclass(frozen=True)
class DatasetPaths:
    """Every file of one dataset. A field is None when the dataset has no such file."""
    name: str
    cml: Path                        # OpenSense CML file, full period
    cml_release: Path                # the CML file of the public release (v1: 75-link Zenodo 1.0.0)
    links_metadata: Path             # one row per sublink, of `cml_release`
    asos: Path
    pws: Optional[Path]              # WU PWS after QC
    pws_airport: Optional[Path]      # WU PWS with the airport WU stations merged in
    mesonet: Optional[Path]
    ghcn: Optional[Path]             # GHCN daily (read it with `load_ghcn`)
    radar_events: Path               # the repo's event catalog (shared by both datasets)
    baselines: Path                  # CML attenuation baselines, hourly (src/analysis/cml_baseline.py)
    baselines_10min: Path            # the same at 10 min
    derived: Path                    # folder for files built from this dataset

    def require(self, key: str) -> Path:
        """The path of `key`, or a clear error when the dataset lacks it or it is not on disk."""
        p = getattr(self, key)
        if p is None:
            raise FileNotFoundError(f"dataset {self.name!r} has no {key!r} file")
        if not Path(p).exists():
            if key in ('baselines', 'baselines_10min'):
                freq = ' --freq 10min' if key == 'baselines_10min' else ''
                hint = f"build it: python src/analysis/cml_baseline.py --dataset {self.name}{freq}"
            elif self.name == 'v1':
                if key == 'asos':
                    hint = "fetch it: analysis.datasets.fetch_v1_asos('<start>', '<end>')"
                elif key == 'pws':
                    hint = (f"download PWS_NYC_WU.zip from {V1_PWS_DOI}: "
                            "src/fetch_data/OpenMesh/openmesh.py run_pws_wu_pipeline(), "
                            "or set OPENMESH_V1_DIR")
                else:
                    hint = (f"download OpenMesh.zip from {V1_DOI}: "
                            "src/fetch_data/OpenMesh/openmesh.py run_openmesh_pipeline(), "
                            "or set OPENMESH_V1_DIR")
            elif self.name == 'v2':
                hint = (f"download openmesh-2.0.0.zip from {V2_DOI}, then "
                        "run analysis.datasets.install_v2('<path to openmesh-2.0.0.zip>') "
                        "or set OPENMESH_V2_DIR")
            elif key == 'cml_release':
                hint = (f"download OpenMesh.zip from {V1_DOI} into "
                        "dataset/raw/openmesh/, or set OPENMESH_V1_DIR")
            else:
                hint = ("'local' is the maintainers' working files, not distributed; "
                        "use the public datasets: D.use('v1') or D.use('v2')")
            raise FileNotFoundError(f"{key} file of dataset {self.name!r} not found: {p}\n  {hint}")
        return Path(p)

    def available(self) -> Dict[str, bool]:
        """{file key: exists on disk} — a quick check of a setup."""
        return {f.name: getattr(self, f.name) is not None and Path(getattr(self, f.name)).exists()
                for f in fields(self) if f.name not in ('name', 'derived')}


def v1_root() -> Path:
    """The folder of the v1 files (ds_openmesh.nc, pws_wu_os.nc, derived/)."""
    return Path(os.environ.get('OPENMESH_V1_DIR', REPO_ROOT / 'dataset' / 'raw' / 'openmesh')).expanduser()


def local_root() -> Path:
    """The folder of the 'local' working files (paper/, outputs/)."""
    return Path(os.environ.get('OPENMESH_LOCAL_DIR', REPO_ROOT / 'dataset' / 'raw' / 'full')).expanduser()


def v2_root() -> Path:
    """The unpacked v2 record (the folder holding data/links/). Accepts the parent of
    openmesh-<version>/ too, so OPENMESH_V2_DIR may point at either."""
    base = Path(os.environ.get('OPENMESH_V2_DIR', REPO_ROOT / 'dataset' / 'raw' / 'openmesh_v2')).expanduser()
    if (base / 'data' / 'links').is_dir():
        return base
    inner = sorted(base.glob('openmesh-*/data/links'))
    return inner[-1].parents[1] if inner else base


def paths(dataset: Optional[str] = None) -> DatasetPaths:
    """The files of `dataset` (default: the active one)."""
    name = resolve(dataset)
    events = REPO_ROOT / 'dataset' / 'meta' / 'radar_events.csv'
    if name == 'local':
        full = local_root()
        out = full / 'outputs'
        return DatasetPaths(
            name='local',
            cml=full / 'paper' / 'ds_opensense_cml.nc',
            cml_release=v1_root() / 'ds_openmesh.nc',
            links_metadata=REPO_ROOT / 'dataset' / 'meta' / 'links_metadata.csv',
            asos=out / 'asos_2023-10-01_2026-04-23.nc',
            pws=out / 'pws_wu_merged_2023-10-29_2026-04-24_qc.nc',
            pws_airport=out / 'pws_wu_merged_2023-06-07_2026-04-24_qc.nc',
            mesonet=out / 'mesonet_2023-08-01_2026-03-04.nc',
            ghcn=out / 'noaa_daily_2023-10-29_2026-04-24_combined.csv',
            radar_events=events,
            baselines=out / 'cml_attenuation_baselines.nc',
            baselines_10min=out / 'cml_attenuation_baselines_10min.nc',
            derived=out,
        )
    if name == 'v1':
        rel = v1_root()
        derived = rel / 'derived'
        return DatasetPaths(
            name='v1',
            cml=rel / 'ds_openmesh.nc',
            cml_release=rel / 'ds_openmesh.nc',
            links_metadata=REPO_ROOT / 'dataset' / 'meta' / 'links_metadata.csv',
            asos=derived / 'asos_v1.nc',
            pws=rel / 'pws_wu_os.nc',
            pws_airport=None,
            mesonet=None,
            ghcn=None,
            radar_events=events,
            baselines=derived / 'cml_attenuation_baselines.nc',
            baselines_10min=derived / 'cml_attenuation_baselines_10min.nc',
            derived=derived,
        )
    root = v2_root()
    data = root / 'data'
    derived = REPO_ROOT / 'dataset' / 'raw' / 'openmesh_v2' / 'derived'
    return DatasetPaths(
        name='v2',
        cml=data / 'links' / 'openmesh_links.nc',
        cml_release=data / 'links' / 'openmesh_links.nc',
        links_metadata=data / 'links' / 'links_metadata.csv',
        asos=data / 'weather' / 'asos' / 'openmesh_asos.nc',
        pws=None,
        pws_airport=None,
        mesonet=None,
        ghcn=data / 'weather' / 'ghcn' / 'ghcn_daily.csv',
        radar_events=events,
        baselines=derived / 'cml_attenuation_baselines.nc',
        baselines_10min=derived / 'cml_attenuation_baselines_10min.nc',
        derived=derived,
    )


def describe(dataset: Optional[str] = None) -> pd.DataFrame:
    """Table of the dataset's files and whether each is on disk."""
    p = paths(dataset)
    rows = [(f.name, getattr(p, f.name), p.available().get(f.name))
            for f in fields(p) if f.name not in ('name', 'derived')]
    return pd.DataFrame(rows, columns=['file', 'path', 'on_disk']).set_index('file')


def install_v2(source: PathLike, dest: Optional[PathLike] = None) -> Path:
    """Unpack the Zenodo v2 zip (openmesh-2.0.0.zip) into dataset/raw/openmesh_v2/.

    `source` may also be an already unpacked openmesh-<version>/ folder: it is then
    linked, not copied. Returns the record folder (the one holding data/links/).
    """
    source = Path(source).expanduser().resolve()
    dest = Path(dest).expanduser() if dest else REPO_ROOT / 'dataset' / 'raw' / 'openmesh_v2'
    dest.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if not (source / 'data' / 'links').is_dir():
            raise FileNotFoundError(f"{source} has no data/links/: not an OpenMesh v2 record")
        link = dest / source.name
        if not link.exists():
            link.symlink_to(source, target_is_directory=True)
        return link
    with zipfile.ZipFile(source) as z:
        top = {n.split('/')[0] for n in z.namelist()}
        z.extractall(dest)
    record = dest / sorted(top)[0] if len(top) == 1 else dest
    if not (record / 'data' / 'links').is_dir():
        raise FileNotFoundError(f"unpacked {source.name} but found no data/links/ under {record}")
    return record


def fetch_v1_asos(start, end, *, stations=V1_ASOS_STATIONS, overwrite: bool = False,
                  verbose: bool = False) -> Path:
    """ASOS 1-min data of [start, end] (UTC days, inclusive) as the v1 ASOS file.

    Fetches from the public IEM API with src/fetch_data/noaa_asos (CSV under
    dataset/raw/fetched/asos/v1/), converts it with src/netCDF_converters/asos_to_netcdf.py
    and installs the result as `paths('v1').asos`. Skipped when that file already
    covers the window (`overwrite=True` fetches again). One window at a time: a new
    window replaces the file. Returns the file path.
    """
    import shutil
    import sys
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    dest = paths('v1').asos
    if dest.exists() and not overwrite:
        a, b = asos_window(dest)
        if a <= start and b >= end:
            return dest
    src = REPO_ROOT / 'src'
    for d in (src / 'fetch_data', src / 'netCDF_converters'):
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))
    from noaa_asos.asos_fetch import fetch_and_save_asos
    from asos_to_netcdf import asos_to_netcdf
    work = REPO_ROOT / 'dataset' / 'raw' / 'fetched' / 'asos' / 'v1'
    s, e = f'{start:%Y-%m-%d}', f'{end:%Y-%m-%d}'
    fetch_and_save_asos(s, e, stations=list(stations), fetched_dir=work,
                        overwrite=overwrite, verbose=verbose)
    nc_path = Path(asos_to_netcdf(str(work / f'ASOS_standard_{s}_{e}.csv'), str(work)))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(nc_path, dest)
    return dest


fetch_essd_asos = fetch_v1_asos     # old name


def asos_window(path: PathLike) -> tuple:
    """(first day, last day) of an ASOS netCDF written by asos_to_netcdf (file attributes)."""
    with xr.open_dataset(path) as ds:
        return pd.Timestamp(ds.attrs['start_date']), pd.Timestamp(ds.attrs['end_date'])


# ============================================================================
# CML: one standard shape for every OpenSense CML file
# ============================================================================

def cml_format(ds: xr.Dataset) -> str:
    """'opensense-v2' (rsl + rsl_avg/rsl_max, network stamps), 'opensense' (single rsl),
    or 'nycmesh-raw' (the 8 s UISP cube: cml_id × time, no sublinks)."""
    if 'sublink_id' not in ds.dims:
        return 'nycmesh-raw'
    return 'opensense-v2' if 'rsl_avg' in ds.data_vars else 'opensense'


def standardize_cml(ds: xr.Dataset) -> xr.Dataset:
    """Bring an OpenSense CML Dataset to the shape the repo's code expects.

    - `polarization` (OpenSense spelling; v1's `polarisation` is renamed);
    - cml_id and sublink_id as str; frequency in MHz, length in m (both files already are).
    Lazy: no signal values are read. For the signal itself use `signal_level`, which
    also covers v2's switch from `rsl` to `rsl_avg` in 2025-04.
    """
    if cml_format(ds) == 'nycmesh-raw':
        raise ValueError("the raw nycmesh cube is not an OpenSense CML file; use nycmesh_utils.open_nycmesh")
    if 'polarisation' in ds.variables and 'polarization' not in ds.variables:
        ds = ds.rename({'polarisation': 'polarization'})
    if ds['cml_id'].dtype.kind != 'U' or ds['sublink_id'].dtype.kind != 'U':
        ds = ds.assign_coords(cml_id=ds.cml_id.astype(str), sublink_id=ds.sublink_id.astype(str))
    return ds


def signal_level(ds: xr.Dataset) -> xr.DataArray:
    """The received signal level (dBm) of a CML Dataset or selection, at every stamp.

    v1 files have one variable, `rsl`. In v2 the network stored an instantaneous `rsl`
    up to 2025-04-21 and only the window mean `rsl_avg` after it, so the level is rsl
    where present, else rsl_avg. Select first (cml_id, sublink_id, time), then call
    this: it reads the values of what it is given.
    """
    level = ds['rsl']
    if 'rsl_avg' in ds.data_vars:
        level = level.fillna(ds['rsl_avg'])
        level.attrs = {**ds['rsl'].attrs, 'long_name': 'received signal level',
                       'comment': 'rsl where stored (instantaneous, to 2025-04-21), else rsl_avg'}
    return level


# One handle per file, shared: opening the same netCDF again and again (v2's
# openmesh_links.nc in particular) ends in "NetCDF: HDF error". Do not close it.
_OPEN: Dict[tuple, xr.Dataset] = {}


def open_cml(source: Union[None, str, PathLike] = None, *, release: bool = False,
             chunks=None) -> xr.Dataset:
    """Open a CML file in the standard shape (see `standardize_cml`).

    source  : None → the active dataset; 'v1' / 'v2' → that dataset; or a path.
    release : take the dataset's public-release file instead of its CML file
              (the same file for v1 and v2).
    The file is opened once per session and shared between calls: do not close it.
    """
    if source is None or is_name(source):
        p = paths(source)
        path = p.require('cml_release' if release else 'cml')
    else:
        path = Path(source)
    key = (str(Path(path).resolve()), repr(chunks))
    if key not in _OPEN:
        ds = xr.open_dataset(path, chunks=chunks)
        ds.attrs.setdefault('source_file', path.name)
        _OPEN[key] = ds
    return standardize_cml(_OPEN[key])


def time_is_sorted(ds: xr.Dataset) -> bool:
    """False for a CML file whose time axis wraps (stamps out of order)."""
    return bool(ds.indexes['time'].is_monotonic_increasing)


def sublink_table(ds: xr.Dataset) -> pd.DataFrame:
    """One row per configured sublink (finite frequency): position (ci, si), ids,
    frequency (MHz), length (m), polarization, ends. Works on any OpenSense CML file."""
    ds = standardize_cml(ds) if 'polarisation' in ds.variables else ds
    freq = ds['frequency'].values
    length = np.broadcast_to(ds['length'].values, (freq.shape[0],))
    pol = ds['polarization'].values if 'polarization' in ds.variables else np.full(freq.shape, '')
    cml_ids = ds['cml_id'].values.astype(str)
    sub_ids = ds['sublink_id'].values.astype(str)
    ci, si = np.where(np.isfinite(freq))
    return pd.DataFrame(dict(
        ci=ci, si=si, cml_id=cml_ids[ci], sublink_id=sub_ids[si],
        sublink=[f"{c}::{s}" for c, s in zip(cml_ids[ci], sub_ids[si])],
        frequency=freq[ci, si].astype(float), length=length[ci].astype(float),
        polarization=np.asarray(pol)[ci, si].astype(str),
        site_0_lat=ds['site_0_lat'].values[ci], site_0_lon=ds['site_0_lon'].values[ci],
        site_1_lat=ds['site_1_lat'].values[ci], site_1_lon=ds['site_1_lon'].values[ci],
    ))


def links_metadata(dataset: Optional[str] = None) -> pd.DataFrame:
    """The dataset's per-sublink metadata CSV (cml_id as str, frequency MHz, length m,
    polarization). v2 adds `direction` (A: site_0 → site_1)."""
    p = paths(dataset).require('links_metadata')
    df = pd.read_csv(p, dtype={'cml_id': str})
    return df.loc[:, ~df.columns.str.startswith('Unnamed')]


# ============================================================================
# Weather
# ============================================================================

GHCN_COLUMNS = ['datetime', 'station_id', 'lat', 'lon', 'elev', 'precip_amount', 'snowfall',
                'snow_depth', 'temperature_max', 'temperature_min', 'temperature']


def load_ghcn(dataset: Optional[str] = None) -> pd.DataFrame:
    """GHCN daily as one table, whichever dataset:
    datetime (local day), station_id (GHCN id), lat, lon, elev, precip_amount (mm),
    snowfall (cm), snow_depth (cm), temperature_max / _min / mean (°C).
    v2 keeps its extra columns (network, asos_id, day_start_utc, day_end_utc).
    v1 has no GHCN file: an empty table with these columns."""
    p = paths(dataset)
    if p.ghcn is None:
        return pd.DataFrame(columns=GHCN_COLUMNS)
    path = p.require('ghcn')
    if p.name == 'local':
        return pd.read_csv(path, parse_dates=['datetime'])
    d = pd.read_csv(path, parse_dates=['date'])
    st = pd.read_csv(path.parent / 'ghcn_stations.csv').set_index('ghcn_id')
    out = pd.DataFrame({
        'datetime': d['date'], 'station_id': d['ghcn_id'],
        'lat': d['ghcn_id'].map(st['lat']), 'lon': d['ghcn_id'].map(st['lon']),
        'elev': d['ghcn_id'].map(st['elev']),
        'precip_amount': d['precipitation_mm'],
        'snowfall': d['snowfall_mm'] / 10.0,            # mm → cm
        'snow_depth': d['snow_depth_mm'] / 10.0,
        'temperature_max': d['tmax_c'], 'temperature_min': d['tmin_c'],
        'temperature': (d['tmax_c'] + d['tmin_c']) / 2,
    })
    extra = d[['network', 'asos_id', 'day_start_utc', 'day_end_utc']]
    return pd.concat([out, extra], axis=1)


def load_weather(dataset: Optional[str] = None, *, pws: Optional[str] = 'qc',
                 mesonet: bool = True, **kw):
    """The weather networks of a dataset, as `nycmesh_utils.load_weather_networks` returns
    them: {'ASOS', 'WU PWS', 'Mesonet'} → {station: Dataset}. v1 has ASOS (the fetched
    window) and WU PWS; v2 has ASOS only.

    pws     : 'qc' (the radar comparison's file), 'airport' (with the airport WU stations,
              used for the precipitation-phase cascade) or None (skip).
    mesonet : False skips the Mesonet file.
    Extra keywords go to load_weather_networks.
    """
    from analysis.nycmesh_utils import load_weather_networks
    p = paths(dataset)
    pws_nc = {'qc': p.pws, 'airport': p.pws_airport, None: None}[pws]
    return load_weather_networks(p.require('asos'), pws_nc, p.mesonet if mesonet else None, **kw)
