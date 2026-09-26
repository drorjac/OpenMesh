"""Offline tests for analysis.rain_maps (IDW, accumulation, distances, CML retrieval QC).
IDW / accumulation tests ported from pcpn_maps."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from analysis import rain_maps as RM
from fetch_data.mrms import Grid


def _points(lat, lon, v, time=None):
    time = time if time is not None else pd.date_range('2024-01-01 01:00', periods=1, freq='h')
    return xr.DataArray(np.asarray(v, float).reshape(len(lat), len(time)), dims=('sensor', 'time'),
                        coords={'sensor': [f's{i}' for i in range(len(lat))], 'time': time,
                                'lat': ('sensor', lat), 'lon': ('sensor', lon)})


def test_idw_exact_at_source_and_bounded():
    grid = Grid(np.array([40.70, 40.71]), np.array([-74.00, -73.99]))
    m = RM.idw_map(_points([40.70, 40.71], [-74.00, -73.99], [2.0, 8.0]), grid).isel(time=0)
    assert m.sel(lat=40.70, lon=-74.00).item() == pytest.approx(2.0)
    assert m.sel(lat=40.71, lon=-73.99).item() == pytest.approx(8.0)
    assert 2.0 < m.sel(lat=40.70, lon=-73.99).item() < 8.0


def test_idw_nan_policies_and_radius():
    grid = Grid(np.array([40.70]), np.array([-73.995]))
    da = _points([40.70, 40.70], [-74.00, -73.99], [np.nan, 4.0])
    assert RM.idw_map(da, grid, nan_policy='exclude').item() == pytest.approx(4.0)
    assert RM.idw_map(da, grid, nan_policy='zero').item() == pytest.approx(2.0)
    far = RM.idw_map(da, Grid(np.array([41.5]), np.array([-73.99])), radius_m=10_000)
    assert np.isnan(far.item())


def test_idw_nnear():
    W = RM.idw_weights(np.array([0.0, 100.0, 1000.0]), np.zeros(3), np.array([50.0]), np.zeros(1), nnear=2)
    assert W[0, 2] == 0 and W[0, 0] > 0 and W[0, 1] > 0


def test_accumulate_hour_ending():
    t = pd.date_range('2024-01-01 00:01', '2024-01-01 02:00', freq='1min')
    da = xr.DataArray(np.full((1, t.size), 6.0), dims=('link', 'time'), coords={'time': t})
    acc = RM.accumulate(da, '1h')
    assert list(pd.DatetimeIndex(acc.time.values)) == list(pd.to_datetime(['2024-01-01 01:00', '2024-01-01 02:00']))
    assert np.allclose(acc.values, 6.0)


def test_distances():
    grid = Grid(np.array([40.70, 40.80]), np.array([-74.00]))
    d = RM.distance_to_points(grid, [40.70], [-74.00])
    assert d.sel(lat=40.70).item() == pytest.approx(0.0)
    assert d.sel(lat=40.80).item() == pytest.approx(11.12, rel=1e-2)
    links = pd.DataFrame({'site_0_lat': [40.70], 'site_0_lon': [-74.00],
                          'site_1_lat': [40.80], 'site_1_lon': [-74.00]})
    assert float(RM.distance_to_paths(grid, links).max()) < 0.06      # both cells on the path


def test_cml_retrieval_qc_flags_dead_link_not_missing_neighbours():
    rows = []
    for i, (lat, tot) in enumerate([(40.70, 20.0), (40.701, 22.0), (40.702, 18.0), (40.703, 0.0)]):
        for h in range(4):
            rows.append(dict(event='e', network='CML', sensor_id=f'L{i}', lat=lat, lon=-74.0,
                             time=pd.Timestamp('2024-01-01') + pd.Timedelta(hours=h), sensor_mm=tot / 4))
    for h in range(4):                                   # a neighbour with no data at all
        rows.append(dict(event='e', network='CML', sensor_id='dead', lat=40.7005, lon=-74.0,
                         time=pd.Timestamp('2024-01-01') + pd.Timedelta(hours=h), sensor_mm=np.nan))
    q = RM.cml_retrieval_qc(pd.DataFrame(rows), 'e')
    assert q.loc['L3', 'flag'] == 'outlier'              # 0 mm among ~20 mm neighbours
    assert (q.loc[['L0', 'L1', 'L2'], 'flag'] == 'ok').all()
    assert q.loc['dead', 'flag'] == 'low coverage'       # not counted as a dry neighbour
