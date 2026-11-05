"""
Link quality control for rain retrieval: which CML sublinks to use, with a logged reason
for every one left out.

Two stages, cheapest first (a third, on the retrieved rain, is
`analysis.rain_maps.cml_retrieval_qc`: it flags links whose event total departs from their
neighbours, and never drops them — in convective storms a genuine outlier is signal):

1. **Metadata** (static, `metadata_qc`): ends missing or outside the study area, path length
   implausible or disagreeing with the end coordinates, frequency outside the band where
   rain attenuation is measurable, duplicate paths (same ends in either direction and
   the same frequency; the sublink with more data is kept).
2. **Time series** (per window, `timeseries_qc`): availability, stuck signal (low spread or a
   long run of one unchanged value), values outside the plausible RSL range, isolated
   spikes (flagged, kept).

Works on any OpenSense CML file in the repo's standard shape (`analysis.datasets.open_cml`);
sublinks are labelled `<cml_id>::<sublink_id>`, the `sublink` labels of the CML attenuation
file (src/analysis/cml_baseline.py), so the kept list can be passed to `exclude=` of the
map functions directly.

    from analysis import datasets as D, cml_qc as Q
    kept, log, summary = Q.run_qc(D.open_cml(), '2024-03-23', '2024-03-24')
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np
import pandas as pd
import xarray as xr

from fetch_data.mrms import NYC, Domain, haversine_m

LOG_COLUMNS = ['sublink', 'stage', 'reason', 'dropped', 'value']


@dataclass
class QCConfig:
    domain: Domain = NYC
    # Below ~10 GHz rain attenuation is too weak to separate from 1-dB quantization on
    # city-length paths (5.8 GHz: 10 mm/h over 2 km gives < 0.1 dB).
    min_frequency_ghz: float = 10.0
    max_frequency_ghz: float = 100.0      # ITU-R P.838 table range
    # Short paths accumulate too little attenuation; long ones break the uniform-rain assumption.
    min_length_km: float = 0.3
    max_length_km: float = 20.0
    length_tolerance: float = 0.1         # |length − distance between the ends| / length
    duplicate_tolerance_m: float = 100.0  # ends closer than this are "the same site"
    min_availability: float = 0.8         # share of valid samples in the window
    min_std_db: float = 0.05              # below: stuck / synthetic feed
    max_constant_hours: float = 48.0      # a run of one unchanged value longer than this: stuck
    rsl_range_dbm: tuple = (-100.0, -10.0)
    max_outside_share: float = 0.01
    spike_db: float = 15.0                # single-sample excursion against both neighbours


def _log(rows, sublink, stage, reason, dropped=True, value=None):
    rows.append(dict(zip(LOG_COLUMNS, (sublink, stage, reason, dropped, value))))


def metadata_qc(table: pd.DataFrame, cfg: QCConfig = QCConfig(),
                availability: Optional[pd.Series] = None) -> tuple:
    """Stage 1 on `analysis.datasets.sublink_table(ds)` (frequency MHz, length m).
    `availability` (indexed by sublink label) decides which duplicate is kept.
    Returns (kept sublink labels, log DataFrame)."""
    rows, keep = [], []
    t = table.set_index('sublink')
    for lk, r in t.iterrows():
        ends = np.array([r.site_0_lat, r.site_0_lon, r.site_1_lat, r.site_1_lon], float)
        f_ghz, l_km = r.frequency / 1000.0, r.length / 1000.0
        dist_km = haversine_m(r.site_0_lat, r.site_0_lon, r.site_1_lat, r.site_1_lon) / 1000.0
        if not np.isfinite(ends).all() or not cfg.domain.contains(ends[[0, 2]], ends[[1, 3]]).all():
            _log(rows, lk, 'metadata', 'ends missing or outside the study area')
        elif not np.isfinite(l_km) or l_km <= 0 or dist_km < 0.001:
            _log(rows, lk, 'metadata', 'zero or missing path length', value=r.length)
        elif abs(l_km - dist_km) > cfg.length_tolerance * l_km:
            _log(rows, lk, 'metadata', 'length disagrees with the end coordinates', value=round(dist_km / l_km, 3))
        elif l_km < cfg.min_length_km:
            _log(rows, lk, 'metadata', f'path shorter than {cfg.min_length_km} km', value=l_km)
        elif l_km > cfg.max_length_km:
            _log(rows, lk, 'metadata', f'path longer than {cfg.max_length_km} km', value=l_km)
        elif not cfg.min_frequency_ghz <= f_ghz <= cfg.max_frequency_ghz:
            _log(rows, lk, 'metadata',
                 f'frequency outside {cfg.min_frequency_ghz:g}–{cfg.max_frequency_ghz:g} GHz', value=f_ghz)
        else:
            keep.append(lk)

    # duplicates: same ends (either direction) and same frequency; keep the best available.
    # The two directions of one cml_id are different sublinks of one radio pair, not duplicates.
    cand = t.loc[keep].assign(avail=(availability.reindex(keep).fillna(0).values
                                     if availability is not None else 0.0))
    chosen = []
    for lk, r in cand.sort_values('avail', ascending=False, kind='stable').iterrows():
        dup = None
        for other in chosen:
            o = t.loc[other]
            if o.cml_id == r.cml_id or abs(o.frequency - r.frequency) >= 10:
                continue
            d = lambda a, b, c, e: haversine_m(a, b, c, e) < cfg.duplicate_tolerance_m
            same = d(r.site_0_lat, r.site_0_lon, o.site_0_lat, o.site_0_lon) and \
                d(r.site_1_lat, r.site_1_lon, o.site_1_lat, o.site_1_lon)
            flip = d(r.site_0_lat, r.site_0_lon, o.site_1_lat, o.site_1_lon) and \
                d(r.site_1_lat, r.site_1_lon, o.site_0_lat, o.site_0_lon)
            if same or flip:
                dup = other
                break
        if dup is None:
            chosen.append(lk)
        else:
            _log(rows, lk, 'metadata', 'duplicate path of another cml_id (that one kept)', value=dup)
    kept = [lk for lk in t.index if lk in set(chosen)]
    return kept, pd.DataFrame(rows, columns=LOG_COLUMNS)


def _longest_constant_hours(x: np.ndarray, t: np.ndarray) -> float:
    """Longest span (h) over which the valid samples keep one unchanged value."""
    ok = np.isfinite(x)
    if ok.sum() < 2:
        return 0.0
    v, tt = x[ok], t[ok]
    change = np.r_[True, v[1:] != v[:-1]]
    starts = np.flatnonzero(change)
    ends = np.r_[starts[1:] - 1, len(v) - 1]
    return float(((tt[ends] - tt[starts]) / np.timedelta64(1, 'h')).max())


def timeseries_qc(ds: xr.Dataset, start, end, sublinks=None, cfg: QCConfig = QCConfig()) -> tuple:
    """Stage 2 on the signal level (`datasets.signal_level`) of `sublinks` (labels; default
    every configured sublink) in [start, end]. Availability is the share of the file's time
    stamps in the window with a value. Returns (kept labels, log DataFrame, availability Series)."""
    from analysis import datasets as D
    tab = D.sublink_table(ds).set_index('sublink')
    sublinks = list(tab.index) if sublinks is None else list(sublinks)
    win = ds.sel(time=slice(pd.Timestamp(start), pd.Timestamp(end)))
    t = win['time'].values
    lo, hi = cfg.rsl_range_dbm
    rows, keep, avail = [], [], {}
    for lk in sublinks:
        r = tab.loc[lk]
        x = D.signal_level(win.isel(cml_id=int(r.ci), sublink_id=int(r.si))).values.astype(float)
        a = float(np.isfinite(x).mean()) if x.size else 0.0
        avail[lk] = a
        if a < cfg.min_availability:
            _log(rows, lk, 'timeseries', f'availability below {cfg.min_availability:.0%}', value=round(a, 3))
            continue
        if np.nanstd(x) < cfg.min_std_db:
            _log(rows, lk, 'timeseries', 'constant signal (stuck feed)', value=float(np.nanstd(x)))
            continue
        run_h = _longest_constant_hours(x, t)
        if run_h > cfg.max_constant_hours:
            _log(rows, lk, 'timeseries', f'one value unchanged for more than {cfg.max_constant_hours:g} h',
                 value=round(run_h, 1))
            continue
        out = np.isfinite(x) & ((x < lo) | (x > hi))
        if out.mean() > cfg.max_outside_share:
            _log(rows, lk, 'timeseries', f'level outside {lo:g}..{hi:g} dBm', value=round(float(out.mean()), 3))
            continue
        d_prev, d_next = x[1:-1] - x[:-2], x[1:-1] - x[2:]
        spikes = int(np.sum((np.abs(d_prev) > cfg.spike_db) & (np.abs(d_next) > cfg.spike_db)
                            & (np.sign(d_prev) == np.sign(d_next))))
        if spikes:
            _log(rows, lk, 'timeseries', 'isolated spikes (flagged, kept)', dropped=False, value=spikes)
        keep.append(lk)
    return keep, pd.DataFrame(rows, columns=LOG_COLUMNS), pd.Series(avail, name='availability')


def qc_summary(log: pd.DataFrame, n_in: int) -> dict:
    """Sublinks in / out and a count per reason (dropped and flagged)."""
    drop = log[log['dropped'].astype(bool)]
    n_drop = int(drop['sublink'].nunique())
    return {'sublinks_in': n_in, 'sublinks_dropped': n_drop, 'sublinks_out': n_in - n_drop,
            'by_reason': drop.groupby('reason')['sublink'].count().to_dict(),
            'flagged': log[~log['dropped'].astype(bool)].groupby('reason')['sublink'].count().to_dict()}


def run_qc(ds: xr.Dataset, start, end, cfg: QCConfig = QCConfig()) -> tuple:
    """Both stages for the window [start, end]: time series first (its availability decides
    which duplicate the metadata stage keeps), then metadata on the survivors' table.
    Returns (kept sublink labels, log, summary dict with the config)."""
    from analysis import datasets as D
    table = D.sublink_table(ds)
    meta_keep, _ = metadata_qc(table, cfg)                 # cheap pre-filter: no signal read for these
    ts_keep, ts_log, avail = timeseries_qc(ds, start, end, meta_keep, cfg)
    kept, meta_log = metadata_qc(table, cfg, availability=avail)
    kept = [lk for lk in kept if lk in set(ts_keep)]
    log = pd.concat([x for x in (meta_log, ts_log) if len(x)], ignore_index=True) \
        if len(meta_log) + len(ts_log) else meta_log
    summary = qc_summary(log, len(table))
    summary['window'] = (str(pd.Timestamp(start)), str(pd.Timestamp(end)))
    summary['config'] = {k: (str(v) if isinstance(v, Domain) else v) for k, v in asdict(cfg).items()}
    return kept, log, summary
