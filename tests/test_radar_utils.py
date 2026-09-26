"""Offline tests for analysis.radar_utils (synthetic data, no network, no local files)."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from analysis import radar_utils as RU
from fetch_data.mrms import path_average


def _station(values, start='2024-01-01 00:00', freq='1min', melt=None):
    t = pd.date_range(start, periods=len(values), freq=freq)
    ds = xr.Dataset({'rainfall_amount': (('id', 'time'), np.asarray(values, float)[None])},
                    coords={'time': t, 'id': ['X'], 'lat': 40.7, 'lon': -73.9})
    if melt is not None:
        ds['gauge_melt'] = ('time', np.asarray(melt, bool))
    return ds


def test_gauge_hourly_sums_hour_ending_and_keeps_gaps():
    v = np.full(180, 0.1)                     # 3 h of 0.1 mm/min from 00:00
    v[70:100] = np.nan                        # 30-min gap in the 01:00–02:00 hour
    h = RU.gauge_hourly({'X': _station(v)}, '2024-01-01 00:00', '2024-01-01 03:00')['X']
    assert h['2024-01-01 01:00'] == pytest.approx(6.0)       # (00:00, 01:00]: 60 minutes
    assert np.isnan(h['2024-01-01 02:00'])                   # < 90 % coverage → NaN, not 0


def test_gauge_hourly_counts_melt_masked_minutes_as_zero():
    v = np.full(120, 0.1)
    melt = np.zeros(120, bool)
    v[60:100], melt[60:100] = np.nan, True    # QC removed 40 min of melt water
    h = RU.gauge_hourly({'X': _station(v, melt=melt)}, '2024-01-01 00:00', '2024-01-01 02:00')['X']
    assert h['2024-01-01 02:00'] == pytest.approx(2.0)        # 20 unmasked min; masked = 0, hour valid


def test_scores_known_values():
    s = RU.scores([1, 2, 3, np.nan], [1, 2, 5, 1])
    assert s['n'] == 3 and s['bias'] == pytest.approx(-2 / 3)
    assert s['nrmse'] == pytest.approx(np.sqrt(4 / 3) / (8 / 3))
    assert s['csi'] == 1.0
    assert RU.scores([np.nan], [1])['n'] == 0


def test_path_average_string_index():
    f = xr.DataArray(np.arange(50.0).reshape(2, 5, 5), dims=('time', 'lat', 'lon'),
                     coords={'time': pd.date_range('2024', periods=2, freq='h'),
                             'lat': 40.6 + 0.01 * np.arange(5), 'lon': -74 + 0.01 * np.arange(5)})
    links = pd.DataFrame({'site_0_lat': [40.61], 'site_0_lon': [-73.99],
                          'site_1_lat': [40.61], 'site_1_lon': [-73.97]},
                         index=pd.Index(['11::sublink_1'], name='link', dtype='string'))
    out = path_average(f, links)
    assert list(out.link.values) == ['11::sublink_1']
    assert float(out.isel(time=0, link=0)) == pytest.approx(7.0)   # mean of row lat=40.61, lon cols 1..3


def test_station_table_empty_has_columns():
    assert list(RU.station_table({}).columns) == ['network', 'sensor_id', 'lat', 'lon']


def test_user_event_file_needs_only_start_end(tmp_path):
    f = tmp_path / "ev.csv"
    f.write_text("start,end\n2024-01-10 01:00,2024-01-10 02:00\n")
    ev = RU.load_event_catalog(f)
    assert list(ev.event) == ["2024-01-10T0100"] and list(ev.cls) == ["user"]
    (tmp_path / "bad.csv").write_text("begin,end\n2024-01-10,2024-01-11\n")
    with pytest.raises(ValueError):
        RU.load_event_catalog(tmp_path / "bad.csv")
