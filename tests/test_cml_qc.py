"""Offline tests for analysis.cml_qc (synthetic CML file, no network)."""
import numpy as np
import pandas as pd
import xarray as xr

from analysis import cml_qc as Q


def _cml(levels, ends, freq_mhz, length_m):
    """OpenSense-shaped file: one sublink per cml_id, levels (cml, time)."""
    n, nt = len(levels), len(levels[0])
    t = pd.date_range('2024-03-22', periods=nt, freq='1h')
    ends = np.asarray(ends, float)
    return xr.Dataset(
        {'rsl': (('cml_id', 'sublink_id', 'time'), np.asarray(levels, float)[:, None, :])},
        coords={'cml_id': [str(i + 1) for i in range(n)], 'sublink_id': ['sublink_1'], 'time': t,
                'site_0_lat': ('cml_id', ends[:, 0]), 'site_0_lon': ('cml_id', ends[:, 1]),
                'site_1_lat': ('cml_id', ends[:, 2]), 'site_1_lon': ('cml_id', ends[:, 3]),
                'frequency': (('cml_id', 'sublink_id'), np.asarray(freq_mhz, float)[:, None]),
                'length': ('cml_id', np.asarray(length_m, float)),
                'polarization': (('cml_id', 'sublink_id'), np.full((n, 1), 'v'))})


def test_run_qc_logs_every_reason():
    rng = np.random.default_rng(0)
    good = -50 + rng.normal(0, 1, 72).round()
    path = [40.70, -73.99, 40.71, -73.97]                       # ~1.98 km
    other = [40.75, -73.95, 40.76, -73.93]
    levels = [good, good.copy(), np.full(72, -60.0), np.where(np.arange(72) < 50, np.nan, good),
              good, good]
    ends = [path, path, other, other, other, [40.70, -73.99, 40.7001, -73.9899]]
    freq = [68000, 68000, 68000, 24000, 5800, 68000]
    length = [1980, 1980, 1980, 1980, 1980, 14]
    kept, log, summary = Q.run_qc(_cml(levels, ends, freq, length), '2024-03-22', '2024-03-25')
    reasons = log.set_index('sublink')['reason'].to_dict()
    assert kept == ['1::sublink_1']
    assert reasons['2::sublink_1'].startswith('duplicate path')
    assert reasons['3::sublink_1'] == 'constant signal (stuck feed)'
    assert reasons['4::sublink_1'].startswith('availability below')
    assert reasons['5::sublink_1'].startswith('frequency outside')
    assert reasons['6::sublink_1'].startswith('zero or missing') or reasons['6::sublink_1'].startswith('path shorter')
    assert summary['sublinks_in'] == 6 and summary['sublinks_out'] == 1


def test_long_constant_run_is_stuck():
    t = pd.date_range('2024-01-01', periods=100, freq='1h').values
    x = np.r_[np.arange(10.0), np.full(60, -70.0), np.arange(30.0)]
    assert Q._longest_constant_hours(x, t) == 59.0
