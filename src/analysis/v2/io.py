"""The v2 record, read through analysis.datasets (the repo's one reader of v1 and v2).

The names are those of the record's own `openmesh_tools` (tools/ in openmesh-2.0.0.zip), so
the record's notebooks run here unchanged apart from the import. The data folder is the
repo's v2 folder: dataset/raw/openmesh_v2/ (`analysis.datasets.install_v2`), or
OPENMESH_V2_DIR; OPENMESH_DATA (the record's variable) is honoured too.
"""
import os
from pathlib import Path

import pandas as pd
import xarray as xr

from analysis import datasets as D
from analysis.datasets import V2_ERA_END as ERA_END, V2_SIGNALS as SIGNALS, band_of, split_of

V2 = 'v2'


def set_data_dir(path):
    """Point the reader at an unpacked record (the folder that holds data/links/)."""
    candidate = Path(path).expanduser().resolve()
    if not (candidate / 'data' / 'links').is_dir():
        raise FileNotFoundError(f"{candidate} has no data/links/ folder: is this the OpenMesh v2 record?")
    os.environ['OPENMESH_V2_DIR'] = str(candidate)


def find_data(data=None):
    """The record folder: `data`, else OPENMESH_DATA, else the repo's v2 folder; None when absent."""
    explicit = data if data is not None else os.environ.get('OPENMESH_DATA')
    if explicit is not None:
        set_data_dir(explicit)
    root = D.v2_root()
    return root if (root / 'data' / 'links').is_dir() else None


def setup(data=None):
    """Start of every v2 notebook: switch the repo to v2, find the record (downloading and
    installing it from Zenodo on first use), set the plot style and the table display.
    Returns the record folder."""
    import warnings
    from .style import style
    for m in ('Mean of empty slice', 'All-NaN slice encountered', 'invalid value encountered',
              'Degrees of freedom'):
        warnings.filterwarnings('ignore', message=m, category=RuntimeWarning)  # empty windows and gaps
    D.use(V2)
    find_data(data)
    if data is None and 'OPENMESH_DATA' not in os.environ:
        D.ensure(V2)                          # downloads openmesh-2.0.0.zip from Zenodo when missing
    style()
    pd.set_option('display.width', 200)
    pd.set_option('display.max_columns', 30)
    return data_dir()


def data_dir():
    root = find_data()
    if root is None:
        D.paths(V2).require('cml')            # raises with the download / install_v2 hint
    return root


def open_links():
    """The whole link file, lazily (cml_id x sublink_id x time); shared: do not close it."""
    return D.open_cml(V2)


def sublink_meta():
    """links_metadata.csv: one row per sublink (ends, frequency, length, polarization, direction)."""
    return D.links_metadata(V2)


def link_meta(availability=False):
    """One row per cml_id (path): datasets.path_table of v2."""
    return D.path_table(V2, availability=availability)


def links(cml_ids=None, start=None, end=None, variables=SIGNALS, sublinks=None):
    """Signal levels for a selection, loaded into memory.
    cml_ids: list of ids, a band ('V60', 'K24', 'C5': paths whose highest radio is in it), or None."""
    ds = open_links()
    if isinstance(cml_ids, str):
        m = link_meta()
        ds = ds.sel(cml_id=list(m[m.band == cml_ids].cml_id))
    elif cml_ids is not None:
        ds = ds.sel(cml_id=[str(c) for c in cml_ids])
    if sublinks is not None:
        ds = ds.sel(sublink_id=list(sublinks))
    return ds[list(variables)].sel(time=slice(start, end)).load()


def aggregation_window():
    return D.aggregation_window(V2)


def hourly():
    """datasets.hourly_summary of v2 (reads the whole file: a few minutes)."""
    return D.hourly_summary(V2)


def asos(start=None, end=None, ids=None, only_ok=True):
    """ASOS 1-min stations (id x time); only_ok: rainfall_amount where rainfall_flag != 0 is NaN."""
    return D.open_asos(V2, only_ok=only_ok, start=start, end=end, ids=ids)


def asos_stations():
    return D.asos_stations(V2)


def radar_events():
    return D.radar_days(V2)


def radar(kind, day):
    """One MRMS day of the record: rainfall_amount_1h, rainfall_amount_15min, precip_flag."""
    return D.open_radar(day, 'mrms', V2)


def radar_kokx(kind, day):
    """The KOKX file of the same day, grid and 10-min stamps as radar(kind, day)."""
    return D.open_radar(day, 'kokx', V2)
