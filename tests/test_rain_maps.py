"""Offline tests for analysis.rain_maps (IDW, accumulation, distances, CML retrieval QC)."""
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


def _adjust_case(obs_mm, radar_mm=2.0):
    """2 × 3 grid of constant radar, three sensors on cells, one hour."""
    from fetch_data.mrms import Grid
    lat, lon = np.array([40.70, 40.71]), np.array([-73.99, -73.98, -73.97])
    t = pd.DatetimeIndex(['2024-03-23 12:00'])
    radar = xr.DataArray(np.full((1, 2, 3), radar_mm), dims=('time', 'lat', 'lon'),
                         coords={'time': t, 'lat': lat, 'lon': lon})
    pts = dict(lat=('sensor', [40.70, 40.71, 40.70]), lon=('sensor', [-73.99, -73.98, -73.97]))
    obs = xr.DataArray(np.asarray(obs_mm, float)[:, None], dims=('sensor', 'time'),
                       coords={'sensor': ['a', 'b', 'c'], 'time': t, **pts})
    rad = obs.copy(data=np.full((3, 1), radar_mm))
    return Grid(lat, lon), radar, obs, rad


def test_adjust_radar_mfb_scales_by_sum_ratio():
    _, radar, obs, rad = _adjust_case([4.0, 4.0, 4.0])
    out = RM.adjust_radar(radar, obs, rad, 'mfb')
    np.testing.assert_allclose(out.values, 4.0, rtol=1e-6)          # factor Σobs / Σradar = 2
    assert out.attrs['event_factor'] == pytest.approx(2.0)


def test_adjust_radar_add_and_mul_hit_the_sensors():
    _, radar, obs, rad = _adjust_case([1.0, 3.0, 5.0])
    add = RM.adjust_radar(radar, obs, rad, 'add')
    assert add.sel(lat=40.70, lon=-73.99).item() == pytest.approx(1.0)  # exact at a sensor cell
    assert add.sel(lat=40.70, lon=-73.97).item() == pytest.approx(5.0)
    mul = RM.adjust_radar(radar, obs, rad, 'mul', eps=0.0)
    assert mul.sel(lat=40.71, lon=-73.98).item() == pytest.approx(3.0)


def test_adjust_radar_too_few_points_uses_event_factor_and_clips():
    _, radar, obs, rad = _adjust_case([40.0, np.nan, np.nan])
    out = RM.adjust_radar(radar, obs, rad, 'mfb', max_factor=5.0)
    np.testing.assert_allclose(out.values, 10.0, rtol=1e-6)         # factor 20 clipped to 5


def test_kokx_sample_uses_the_radial_containing_the_point():
    from fetch_data.nexrad import kokx
    az = np.arange(0, 360, 1.0)                        # radial i spans [i, i+1)°
    data = np.tile(az[:, None], (1, 400)).astype(np.float32)   # value = radial start
    scan = {'t': pd.Timestamp('2024-03-23 12:00'), 'data': data, 'az': az, 'az_end': az + 1.0,
            'gate_km': 0.25, 'rlat': 40.0, 'rlon': -73.0}
    # a point due east-north-east at 45.8°, 50 km out: inside radial 45, nearer the start of 46
    b = np.radians(45.8)
    lat = 40.0 + 50 * np.cos(b) / 111.19
    lon = -73.0 + 50 * np.sin(b) / (111.19 * np.cos(np.radians((lat + 40.0) / 2)))
    pts = pd.DataFrame({'key': ['p'], 'pt': [0], 'lat': [lat], 'lon': [lon]})
    assert kokx._sample(scan, pts)['value'].iloc[0] == 45.0


def test_kokx_rain_field_counts_no_echo_as_zero():
    from fetch_data.nexrad import kokx
    z = xr.DataArray(np.array([[[np.nan, 40.0]]]), dims=('time', 'lat', 'lon'))
    r = kokx.rain_field(z).values.ravel()
    assert r[0] == 0.0 and r[1] == pytest.approx(11.53, abs=0.01)


def test_kokx_sample_grid_nearest_scan_and_fill(monkeypatch):
    """Scan nearest each stamp within 5 min; stamps without one are 255 (HHC) / NaN (N0B)."""
    from fetch_data.nexrad import kokx
    scan_t = {'HHC': ['2024-02-13 12:02:10', '2024-02-13 12:13:00'],
              'N0B': ['2024-02-13 12:01:00', '2024-02-13 12:04:00']}
    def fake_list(prod, hour):
        return [f'OKX_{prod}_{pd.Timestamp(t):%Y_%m_%d_%H_%M_%S}' for t in scan_t[prod]
                if pd.Timestamp(t).floor('h') == hour]
    def fake_read(key):
        prod, t = key.split('_')[1], kokx._key_time(key)
        az = np.arange(0, 360, 1.0)
        val = 60.0 if prod == 'HHC' else float(t.minute)        # N0B value = scan minute
        return {'t': t, 'product': prod, 'data': np.full((360, 800), val, np.float32), 'az': az,
                'az_end': az + 1, 'gate_km': 0.25, 'rlat': 40.865, 'rlon': -72.864}
    monkeypatch.setattr(kokx, '_list', fake_list)
    monkeypatch.setattr(kokx, '_read', fake_read)
    times = pd.date_range('2024-02-13 12:00', periods=3, freq='10min')       # 12:00, 12:10, 12:20
    ds = kokx.sample_grid(times, lat=[40.70, 40.71], lon=[-73.95])
    assert list(ds.hydrometeor_class.values[:, 0, 0]) == [60, 60, 255]
    n0b = ds.reflectivity.values[:, 0, 0]
    assert n0b[0] == 1.0 and np.isnan(n0b[1]) and np.isnan(n0b[2])          # 12:01 nearest to 12:00
    assert pd.isna(ds.scan_time_n0b.values[1]) and ds.scan_time_hhc.values[1] == pd.Timestamp('2024-02-13 12:13')
