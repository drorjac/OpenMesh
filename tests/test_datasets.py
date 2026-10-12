"""analysis.datasets: choosing v1/v2, and reading both CML / ASOS / GHCN layouts the same way.

Small synthetic files mimic the two CML layouts: the v1 one (`polarisation`, single `rsl`,
here with an unsorted time axis) and v2 (Zenodo 2.0.0: `polarization`, rsl + rsl_avg/rsl_max,
flat ASOS with rainfall_flag, GHCN in mm).
"""
import zipfile

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from analysis import datasets as D
from analysis.nycmesh_utils import _asos_code_phase, load_weather_networks


def _cml(n_cml, subs, times, *, v2):
    shape = (n_cml, len(subs), len(times))
    freq = np.full((n_cml, len(subs)), np.nan)
    freq[:, :2] = 68_000.0
    ds = xr.Dataset(
        {'rsl': (('cml_id', 'sublink_id', 'time'), np.full(shape, -50.0, np.float32))},
        coords=dict(cml_id=[str(i + 1) for i in range(n_cml)], sublink_id=subs, time=times,
                    frequency=(('cml_id', 'sublink_id'), freq),
                    length=('cml_id', np.linspace(500, 3000, n_cml)),
                    site_0_lat=('cml_id', np.full(n_cml, 40.7)), site_0_lon=('cml_id', np.full(n_cml, -74.0)),
                    site_1_lat=('cml_id', np.full(n_cml, 40.72)), site_1_lon=('cml_id', np.full(n_cml, -73.98))))
    pol = np.full((n_cml, len(subs)), 'vertical')
    if v2:
        ds['rsl'][:, :, len(times) // 2:] = np.nan            # instantaneous era ends
        ds['rsl_avg'] = xr.full_like(ds['rsl'], -60.0)
        ds['rsl_max'] = xr.full_like(ds['rsl'], -55.0)
        ds = ds.assign_coords(polarization=(('cml_id', 'sublink_id'), pol))
    else:
        ds = ds.assign_coords(polarisation=(('cml_id', 'sublink_id'), pol))
    return ds


@pytest.fixture
def v2_record(tmp_path):
    """A minimal unpacked v2 record: data/links, data/weather/asos, data/weather/ghcn."""
    root = tmp_path / 'openmesh-2.0.0'
    (root / 'data' / 'links').mkdir(parents=True)
    times = pd.date_range('2025-04-20', periods=6, freq='1h')
    _cml(3, ['sublink_1', 'sublink_2', 'sublink_3', 'sublink_4'], times, v2=True).to_netcdf(
        root / 'data' / 'links' / 'openmesh_links.nc')
    pd.DataFrame({'cml_id': ['1', '1'], 'sublink_id': ['sublink_1', 'sublink_2'], 'frequency': [68000, 68000],
                  'length': [500, 500], 'polarization': ['vertical'] * 2, 'direction': ['A', 'B']}
                 ).to_csv(root / 'data' / 'links' / 'links_metadata.csv', index=False)
    asos = root / 'data' / 'weather' / 'asos'
    asos.mkdir(parents=True)
    t = pd.date_range('2026-02-22', periods=4, freq='1min')
    xr.Dataset(
        {'rainfall_amount': (('id', 'time'), np.array([[0.2, 0.3, 9.0, 0.1], [0.0, 0.0, 0.0, 0.0]])),
         'rainfall_flag': (('id', 'time'), np.array([[0, 0, 1, 0], [0, 0, 0, -1]], np.int8)),
         'temperature': (('id', 'time'), np.full((2, 4), -1.0)),
         'dew_point': (('id', 'time'), np.full((2, 4), -2.0)),
         'precip_category': (('id', 'time'), np.array([['snow', 'snow', 'ice', 'mix'], ['dry'] * 4]))},
        coords=dict(id=['LGA', 'JFK'], time=t)).to_netcdf(asos / 'openmesh_asos.nc')
    ghcn = root / 'data' / 'weather' / 'ghcn'
    ghcn.mkdir(parents=True)
    pd.DataFrame({'date': ['2026-02-23'], 'ghcn_id': ['USW00014732'], 'asos_id': ['LGA'],
                  'network': ['NWS first-order'], 'day_start_utc': ['2026-02-23 05:00'],
                  'day_end_utc': ['2026-02-24 05:00'], 'precipitation_mm': [43.0], 'snowfall_mm': [533.0],
                  'snow_depth_mm': [300.0], 'tmax_c': [0.0], 'tmin_c': [-4.0]}).to_csv(ghcn / 'ghcn_daily.csv',
                                                                                     index=False)
    pd.DataFrame({'ghcn_id': ['USW00014732'], 'asos_id': ['LGA'], 'network': ['NWS first-order'],
                  'name': ['LAGUARDIA'], 'lat': [40.78], 'lon': [-73.88], 'elev': [3.0]}
                 ).to_csv(ghcn / 'ghcn_stations.csv', index=False)
    return root


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv('OPENMESH_DATASET', raising=False)
    monkeypatch.setattr(D, '_active', None)
    D._OPEN.clear()
    yield
    for ds in D._OPEN.values():
        ds.close()
    D._OPEN.clear()


# ---- choosing --------------------------------------------------------------

def test_default_is_v1_and_switches(monkeypatch):
    assert D.active() == 'v1'
    monkeypatch.setenv('OPENMESH_DATASET', 'v2')
    assert D.active() == 'v2'
    assert D.use('V1') == 'v1' and D.active() == 'v1'      # use() beats the env var
    assert D.resolve('v2') == 'v2'
    assert D.use('ESSD') == 'v1'                           # old name of v1, still accepted
    assert D.PUBLIC == ('v1', 'v2') and D.DEFAULT == 'v1'
    with pytest.raises(ValueError):
        D.use('v3')


def test_paths_follow_env_overrides(monkeypatch, tmp_path, v2_record):
    monkeypatch.setenv('OPENMESH_V1_DIR', str(tmp_path / 'v1'))
    monkeypatch.setenv('OPENMESH_V2_DIR', str(v2_record.parent))     # parent of openmesh-2.0.0/ works
    monkeypatch.setenv('OPENMESH_LOCAL_DIR', str(tmp_path / 'local'))
    p1, p2, pl = D.paths('v1'), D.paths('v2'), D.paths('local')
    assert p1.cml == tmp_path / 'v1' / 'ds_openmesh.nc'
    assert p2.cml == v2_record / 'data' / 'links' / 'openmesh_links.nc'
    assert pl.cml.parent.parent == tmp_path / 'local' and pl.cml_release == p1.cml
    assert p2.pws is None and p2.mesonet is None
    with pytest.raises(FileNotFoundError, match="has no 'pws'"):
        p2.require('pws')
    with pytest.raises(FileNotFoundError, match='zenodo.15287692'):
        p1.require('cml')
    with pytest.raises(FileNotFoundError, match="not distributed"):
        pl.require('cml')


def test_install_v2_from_zip_and_folder(tmp_path, v2_record):
    zpath = tmp_path / 'openmesh-2.0.0.zip'
    with zipfile.ZipFile(zpath, 'w') as z:
        for f in v2_record.rglob('*'):
            z.write(f, f.relative_to(v2_record.parent))
    rec = D.install_v2(zpath, dest=tmp_path / 'from_zip')
    assert (rec / 'data' / 'links' / 'openmesh_links.nc').exists()
    link = D.install_v2(v2_record, dest=tmp_path / 'from_dir')
    assert link.is_symlink() and (link / 'data' / 'links').is_dir()
    with pytest.raises(FileNotFoundError):
        D.install_v2(tmp_path / 'from_zip', dest=tmp_path / 'bad')     # no data/links/ directly inside


# ---- CML -------------------------------------------------------------------

def test_open_cml_v1_and_v2_same_shape(tmp_path, v2_record):
    times = pd.DatetimeIndex(['2023-12-01 00:00:08', '2023-12-01 00:00:00', '2023-12-01 00:00:16'])
    v1_file = tmp_path / 'ds_opensense_cml.nc'
    _cml(2, [f'sublink_{i}' for i in range(1, 6)], times, v2=False).to_netcdf(v1_file)
    v1 = D.open_cml(v1_file)
    v2 = D.open_cml(v2_record / 'data' / 'links' / 'openmesh_links.nc')
    for ds in (v1, v2):
        assert 'polarization' in ds.variables and 'polarisation' not in ds.variables
        assert ds.cml_id.dtype.kind == 'U' and ds.sublink_id.dtype.kind == 'U'
    assert D.cml_format(v1) == 'opensense' and D.cml_format(v2) == 'opensense-v2'
    assert not D.time_is_sorted(v1) and D.time_is_sorted(v2)
    assert D.open_cml(v1_file) is not v1 and D.open_cml(v1_file).equals(v1)   # shared handle, same data


def test_signal_level_fills_v2_avg_era(v2_record):
    ds = D.open_cml(v2_record / 'data' / 'links' / 'openmesh_links.nc')
    level = D.signal_level(ds.sel(cml_id='1', sublink_id='sublink_1')).values
    np.testing.assert_array_equal(level, [-50, -50, -50, -60, -60, -60])
    assert np.isnan(ds['rsl'].sel(cml_id='1', sublink_id='sublink_1').values[3:]).all()   # file untouched


def test_sublink_table_both_layouts(tmp_path, v2_record):
    times = pd.date_range('2024-01-01', periods=2, freq='8s')
    v1_ds = _cml(2, ['sublink_1', 'sublink_2', 'sublink_3'], times, v2=False)
    t1 = D.sublink_table(v1_ds)                                  # polarisation spelling accepted
    t2 = D.sublink_table(D.open_cml(v2_record / 'data' / 'links' / 'openmesh_links.nc'))
    assert len(t1) == 4 and len(t2) == 6                         # finite frequencies only
    assert list(t2.columns[:4]) == ['ci', 'si', 'cml_id', 'sublink_id']
    assert t2.sublink.iloc[0] == '1::sublink_1' and (t2.polarization == 'vertical').all()


# ---- weather ---------------------------------------------------------------

def test_flat_v2_asos_masks_flags_and_renames(v2_record):
    nets = load_weather_networks(v2_record / 'data' / 'weather' / 'asos' / 'openmesh_asos.nc',
                                 asos_gauge_melt='off', verbose=False)
    lga = nets['ASOS']['LGA']
    assert lga.sizes['id'] == 1 and 'dewpoint' in lga
    np.testing.assert_allclose(lga.rainfall_amount.values.ravel(), [0.2, 0.3, np.nan, 0.1])
    assert nets['WU PWS'] == {} and nets['Mesonet'] == {}


def test_asos_phase_from_category_skips_mix(v2_record):
    nets = load_weather_networks(v2_record / 'data' / 'weather' / 'asos' / 'openmesh_asos.nc',
                                 asos_gauge_melt='off', verbose=False)
    ph = _asos_code_phase(nets['ASOS'], window=('2026-02-22', '2026-02-23'), freq='1min')
    assert list(ph.values) == ['snow', 'snow', 'mixed']    # ice → mixed; the 'mix' minute adds no bin


def test_load_ghcn_v2_matches_v1_layout(monkeypatch, v2_record):
    monkeypatch.setenv('OPENMESH_V2_DIR', str(v2_record))
    g = D.load_ghcn('v2')
    assert list(g.columns[:len(D.GHCN_COLUMNS)]) == D.GHCN_COLUMNS
    row = g.iloc[0]
    assert row.station_id == 'USW00014732' and row.snowfall == pytest.approx(53.3)   # mm → cm
    assert row.temperature == pytest.approx(-2.0) and row.lat == pytest.approx(40.78)


def test_v1_uses_public_release_files(monkeypatch, tmp_path):
    monkeypatch.delenv('OPENMESH_V1_DIR', raising=False)
    p = D.paths('v1')
    rel = D.REPO_ROOT / 'dataset' / 'raw' / 'openmesh'
    assert p.cml == p.cml_release == rel / 'ds_openmesh.nc'
    assert p.pws == rel / 'pws_wu_os.nc'
    assert p.asos == rel / 'derived' / 'asos_v1.nc'
    assert p.baselines_10min.parent == p.derived == rel / 'derived'
    assert p.mesonet is None and p.pws_airport is None and p.ghcn is None
    assert list(D.load_ghcn('v1').columns) == D.GHCN_COLUMNS
    assert D.paths('ESSD') == p and D.fetch_essd_asos is D.fetch_v1_asos   # old names
