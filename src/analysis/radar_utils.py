"""
Radar (MRMS) × sensor helpers — event catalog, radar fetch, merging, comparison.

Chain used by the tutorials in tutorials/radar_*.ipynb:

1. `build_event_catalog`  — the top-N snow / rain / mix storms of the study period,
   from ASOS present-weather codes (phase) and NOAA GHCN daily totals (magnitude).
2. `fetch_event_radar`    — fill the MRMS cache (src/fetch_data/mrms) for every event.
3. `merge_event`          — one tidy hourly table per event: every sensor (ASOS, WU PWS,
   NY Mesonet, CML) next to the MRMS value at its location (gauges) or path (CML).
4. `compare_sensors` / `phase_agreement` — scores (NRMSE headline) and precip-type
   agreement, per event and pooled.

Time convention everywhere: hourly values are accumulations in mm labelled by the END
of the hour (UTC, tz-naive), the MRMS QPE convention — 12:00 holds 11:00–12:00.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parents[2]
EVENTS_CSV = REPO_ROOT / 'dataset' / 'meta' / 'radar_events.csv'

_WET = ('rain', 'snow', 'mix', 'ice')

# merged-table column → MRMS hourly product
RADAR_COLUMNS = {'radar_mm': 'MultiSensor_QPE_01H_Pass2', 'radar_only_mm': 'RadarOnly_QPE_01H'}
RADAR_LABELS = {'radar_mm': 'MRMS', 'radar_only_mm': 'MRMS radar-only'}

# Full-period study files (local, not in the Zenodo archive).
FULL_OUTPUTS = REPO_ROOT / 'dataset' / 'raw' / 'full' / 'outputs'
FULL_FILES = {
    'asos': FULL_OUTPUTS / 'asos_2023-10-01_2026-04-23.nc',
    'pws': FULL_OUTPUTS / 'pws_wu_merged_2023-10-29_2026-04-24_qc.nc',
    'mesonet': FULL_OUTPUTS / 'mesonet_2023-08-01_2026-03-04.nc',
    'cml': FULL_OUTPUTS / 'cml_attenuation_baselines_10min.nc',
    'ghcn': FULL_OUTPUTS / 'noaa_daily_2023-10-29_2026-04-24_combined.csv',
}


def load_sensors(files: Optional[Dict[str, Path]] = None, *, verbose: bool = True):
    """Load every sensor used in the radar comparison in one call.

    Returns (networks, cml, ghcn): `networks` = {'ASOS', 'WU PWS', 'Mesonet'} →
    {station: Dataset} (ASOS with gauge-melt QC, PWS with its QC drops applied);
    `cml` = 10-min attenuation Dataset (lazy); `ghcn` = NOAA daily DataFrame.
    """
    from analysis.nycmesh_utils import load_weather_networks
    f = {**FULL_FILES, **(files or {})}
    networks = load_weather_networks(f['asos'], f['pws'], f['mesonet'], verbose=verbose)
    cml = xr.open_dataset(f['cml'])
    ghcn = pd.read_csv(f['ghcn'], parse_dates=['datetime'])
    if verbose:
        print(f"  CML        {cml.sizes['sublink']:3d} sublinks ({len(cml_links(cml))} ≥ 20 GHz)")
        print(f"  GHCN       {ghcn.station_id.nunique():3d} stations (daily)")
    return networks, cml, ghcn


# ============================================================================
# 1. Event catalog
# ============================================================================

def _station_series(ds: xr.Dataset, var: str) -> pd.Series:
    return pd.Series(ds[var].values.ravel(), index=pd.DatetimeIndex(ds['time'].values))


def build_event_catalog(
    asos_net: Dict[str, xr.Dataset],
    ghcn_daily: pd.DataFrame,
    *,
    period=('2023-10-29', '2026-04-23'),
    n_per_class: int = 5,
    gap: str = '6h',
    merge_gap: str = '12h',
    min_wet_station_min: int = 30,
    min_stations: int = 3,
    rain_temp_min_c: float = 2.0,
) -> pd.DataFrame:
    """Top `n_per_class` snow, rain and mixed-precipitation events in `period`.

    Segmentation (network-wide, 10-min bins over all ASOS stations):
      * a bin is wet when any station reports a wet precip_category;
      * wet bins closer than `gap` form one event; events with fewer than
        `min_wet_station_min` wet station-minutes are dropped;
      * phase fractions f_rain / f_snow / f_frozen (snow+ice) / f_P (ASOS 'P',
        unknown type) are shares of wet station-minutes.
    Class:
      snow = f_snow ≥ 0.5 · rain = f_rain ≥ 0.8 and T_min > `rain_temp_min_c`
      mix  = f_rain ≥ 0.15, (f_frozen ≥ 0.1 or f_P ≥ 0.2) and T_min ≤ `rain_temp_min_c`
      (warm 'P' codes are thunderstorms, not mixed phase — hence the cold gate).
    Same-class events closer than `merge_gap` are merged (e.g. a blizzard split by a lull).
    Ranking: snow by NOAA snowfall (cm), rain and mix by NOAA precipitation (mm), both
    as the mean over GHCN stations of the event's local-standard-time days. Events with
    fewer than `min_stations` reporting ASOS stations or 0 mm in GHCN are skipped, and
    picks may not share a GHCN day.

    `asos_net` should be loaded with the gauge-melt QC on (the default);
    `ghcn_daily` is the combined NOAA daily CSV (datetime, station_id, precip_amount,
    snowfall). Returns one row per event with units in the column names.
    """
    t0, t1 = pd.Timestamp(period[0]), pd.Timestamp(period[1]) + pd.Timedelta('1D')
    idx = pd.date_range(t0, t1, freq='10min', inclusive='left')

    def per_bin(fn):
        return pd.DataFrame({s: fn(ds).reindex(idx) for s, ds in asos_net.items()})

    cat = {s: _station_series(ds, 'precip_category').astype(str) for s, ds in asos_net.items()}
    wet_min = {ph: pd.DataFrame({s: (c == ph).astype(float).resample('10min').sum()
                                 .reindex(idx, fill_value=0) for s, c in cat.items()}).sum(axis=1)
               for ph in _WET}
    rain = per_bin(lambda ds: _station_series(ds, 'rainfall_amount').resample('10min').sum(min_count=1))
    temp = per_bin(lambda ds: _station_series(ds, 'temperature').resample('10min').mean()).mean(axis=1)

    wet = sum(wet_min.values()) > 0
    t = wet[wet].index.to_series()
    rows = []
    for _, ts in t.groupby((t.diff() > pd.Timedelta(gap)).cumsum().values):
        a, b = ts.iloc[0], ts.iloc[-1] + pd.Timedelta('10min')
        m = {ph: float(wet_min[ph].loc[a:b].sum()) for ph in _WET}
        tot = sum(m.values())
        if tot < min_wet_station_min:
            continue
        rows.append(dict(start=a, end=b, wet_station_min=tot,
                         f_rain=m['rain'] / tot, f_snow=m['snow'] / tot,
                         f_frozen=(m['snow'] + m['ice']) / tot, f_P=m['mix'] / tot,
                         t_min_C=float(temp.loc[a:b].min()), asos_mm=float(rain.loc[a:b].sum(min_count=1).mean()),
                         n_stations=int(rain.loc[a:b].notna().any().sum())))
    ev = pd.DataFrame(rows)
    ev['cls'] = np.select(
        [ev.f_snow >= 0.5,
         (ev.f_rain >= 0.8) & (ev.t_min_C > rain_temp_min_c),
         (ev.f_rain >= 0.15) & ((ev.f_frozen >= 0.1) | (ev.f_P >= 0.2)) & (ev.t_min_C <= rain_temp_min_c)],
        ['snow', 'rain', 'mix'], 'other')

    merged = []
    for r in ev.sort_values('start').to_dict('records'):
        p = merged[-1] if merged else None
        if p and p['cls'] == r['cls'] != 'other' and r['start'] - p['end'] < pd.Timedelta(merge_gap):
            w0, w1 = p['wet_station_min'], r['wet_station_min']
            for f in ('f_rain', 'f_snow', 'f_frozen', 'f_P'):
                p[f] = (p[f] * w0 + r[f] * w1) / (w0 + w1)
            p.update(end=r['end'], wet_station_min=w0 + w1, t_min_C=min(p['t_min_C'], r['t_min_C']),
                     asos_mm=np.nansum([p['asos_mm'], r['asos_mm']]),
                     n_stations=max(p['n_stations'], r['n_stations']))
        else:
            merged.append(dict(r))
    ev = pd.DataFrame(merged)

    # GHCN days are local standard time (UTC-5).
    ev['day0'] = (ev['start'] - pd.Timedelta('5h')).dt.normalize()
    ev['day1'] = (ev['end'] - pd.Timedelta('5h')).dt.normalize()
    g = ghcn_daily.assign(datetime=pd.to_datetime(ghcn_daily['datetime']))
    pr = g.pivot_table(index='datetime', columns='station_id', values='precip_amount')
    sn = g.pivot_table(index='datetime', columns='station_id', values='snowfall')
    ev['ghcn_mm'] = [pr.loc[a:b].sum(min_count=1).mean() for a, b in zip(ev.day0, ev.day1)]
    ev['ghcn_snow_cm'] = [sn.loc[a:b].sum(min_count=1).mean() for a, b in zip(ev.day0, ev.day1)]

    picks = []
    for cls, key in (('snow', 'ghcn_snow_cm'), ('rain', 'ghcn_mm'), ('mix', 'ghcn_mm')):
        cand = ev[(ev.cls == cls) & (ev.ghcn_mm > 0) & (ev.n_stations >= min_stations)]
        keep = []
        for i, r in cand.sort_values(key, ascending=False).iterrows():
            if any(not (r.day1 < ev.at[j, 'day0'] or r.day0 > ev.at[j, 'day1']) for j in keep):
                continue
            keep.append(i)
            if len(keep) == n_per_class:
                break
        picks.append(ev.loc[keep].assign(rank=range(1, len(keep) + 1)))
    out = pd.concat(picks, ignore_index=True)
    out['hours'] = (out['end'] - out['start']).dt.total_seconds() / 3600
    out['event'] = out['start'].dt.strftime('%Y-%m-%d') + '_' + out['cls']
    cols = ['event', 'cls', 'rank', 'start', 'end', 'hours', 'ghcn_mm', 'ghcn_snow_cm', 'asos_mm',
            't_min_C', 'f_rain', 'f_snow', 'f_frozen', 'f_P', 'n_stations']
    num = out[cols].select_dtypes('number').columns
    out[num] = out[num].round(3)
    return out[cols]


def save_event_catalog(events: pd.DataFrame, path: Path = EVENTS_CSV) -> Path:
    """Write the catalog with a header explaining every column (units in names)."""
    header = (
        "# Radar comparison event catalog: top snow / rain / mix storms, NYC.\n"
        "# Built by src/analysis/radar_utils.py:build_event_catalog (see its docstring).\n"
        "# start/end: UTC (tz-naive), first/last wet 10-min bin over the ASOS network.\n"
        "# ghcn_mm / ghcn_snow_cm: NOAA GHCN daily precipitation (mm) / snowfall (cm),\n"
        "#   mean over GHCN stations of the event's local days (ranking key).\n"
        "# asos_mm: ASOS 1-min precip summed over the event (gauge-melt QC on), station mean.\n"
        "# t_min_C: lowest 10-min network-mean temperature (degC).\n"
        "# f_*: share of wet station-minutes coded rain / snow / snow+ice / P (unknown).\n"
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        f.write(header)
        events.to_csv(f, index=False)
    return path


def load_event_catalog(path: Path = EVENTS_CSV) -> pd.DataFrame:
    """Read an event catalog: ours by default, or any CSV of yours with `start` and
    `end` columns (UTC); `event` and `cls` are optional (generated / 'user')."""
    ev = pd.read_csv(path, comment='#', parse_dates=['start', 'end'])
    missing = {'start', 'end'} - set(ev.columns)
    if missing:
        raise ValueError(f'{path}: event file needs columns start, end (missing {sorted(missing)})')
    if 'event' not in ev:
        ev['event'] = ev['start'].dt.strftime('%Y-%m-%dT%H%M')
    if 'cls' not in ev:
        ev['cls'] = 'user'
    return ev


# ============================================================================
# 2. Radar fetch
# ============================================================================

DEFAULT_PRODUCTS = {
    'MultiSensor_QPE_01H_Pass2': None,   # hourly gauge-corrected QPE — the reference
    'RadarOnly_QPE_01H': None,           # hourly radar-only QPE — gauge-independent check
    'PrecipFlag': '10min',               # surface precip type
    'PrecipRate': '10min',               # instantaneous rate, for 10-min CML comparison
}


def fetch_event_radar(
    events: pd.DataFrame,
    *,
    products: Dict[str, Optional[str]] = None,
    pad: str = '1h',
    client=None,
    domain=None,
    verbose: bool = True,
) -> pd.DataFrame:
    """Fill the MRMS cache for every event (±`pad`). `products` maps any MRMS product
    name → subsampling freq (None = native cadence); `domain` is any
    `fetch_data.mrms.Domain` (default NYC). Returns one row per (event, product) with
    the number of fields cached and missing. Re-runs are free (cache hits)."""
    from fetch_data.mrms import NYC, MRMSClient, usable_freq
    client = client or MRMSClient()
    domain = domain or NYC
    products = products or DEFAULT_PRODUCTS
    rows = []
    for ev in events.itertuples():
        a, b = ev.start - pd.Timedelta(pad), ev.end + pd.Timedelta(pad)
        for prod, freq in products.items():
            p = client.resolve_product(prod)
            da = client.load(p, a.floor('h'), b.ceil('h'), domain, freq=usable_freq(p, freq))
            rows.append(dict(event=ev.event, product=prod, n_fields=int(da.sizes['time']),
                             n_missing=len(da.attrs.get('missing_times', []))))
            if verbose:
                print(f'  {ev.event:22s} {prod:28s} {rows[-1]["n_fields"]:5d} fields'
                      f'  {rows[-1]["n_missing"]:3d} missing', flush=True)
    return pd.DataFrame(rows)


# ============================================================================
# 3. Hourly sensor series (pre-processing)
# ============================================================================

def _hour_window(start, end):
    """Hour-ending labels covering [start, end]: (floor(start)+1h … ceil(end))."""
    return pd.Timestamp(start).floor('h') + pd.Timedelta('1h'), pd.Timestamp(end).ceil('h')


def gauge_hourly(
    net: Dict[str, xr.Dataset],
    start, end,
    *,
    var: str = 'rainfall_amount',
    min_coverage: float = 0.8,
) -> pd.DataFrame:
    """Hourly precipitation (mm, hour-ending) per station, (time × station).

    Sums the per-interval `var` inside each hour; an hour is NaN when fewer than
    `min_coverage` of the station's expected samples (from its median time step) are
    present — so a gap is never read as 0 mm. Works for ASOS (1 min), WU PWS
    (5 min / 15 min / 1 h) and NY Mesonet (5 min).
    """
    h0, h1 = _hour_window(start, end)
    hours = pd.date_range(h0, h1, freq='1h')
    out = {}
    for sid, ds in net.items():
        if var not in ds:
            continue
        s = _station_series(ds, var).astype(float)
        if 'gauge_melt' in ds:
            # ASOS melt-masked minutes: the gauge worked, the water was removed → 0 mm
            s = s.mask(_station_series(ds, 'gauge_melt').astype(bool) & s.isna(), 0.0)
        s = s.loc[h0 - pd.Timedelta('1h'):h1]
        s = s[~s.index.duplicated()].sort_index()
        if s.notna().sum() == 0:
            continue
        step = pd.Series(s.index).diff().median()
        expected = max(1.0, pd.Timedelta('1h') / step)
        g = s.resample('1h', label='right', closed='right')
        h = g.sum(min_count=1).where(g.count() >= min_coverage * expected)
        out[sid] = h.reindex(hours)
    return pd.DataFrame(out, index=hours)


def station_table(networks: Dict[str, Dict[str, xr.Dataset]]) -> pd.DataFrame:
    """One row per station: network, id, lat, lon (degrees)."""
    rows = []
    for net, stations in networks.items():
        for sid, ds in stations.items():
            if 'lat' in ds and 'lon' in ds:
                rows.append(dict(network=net, sensor_id=sid,
                                 lat=float(np.ravel(ds['lat'].values)[0]),
                                 lon=float(np.ravel(ds['lon'].values)[0])))
    return pd.DataFrame(rows, columns=['network', 'sensor_id', 'lat', 'lon'])


def cml_links(cml: xr.Dataset, *, min_freq_ghz: float = 20.0) -> pd.DataFrame:
    """Sublinks usable for rain retrieval (freq ≥ `min_freq_ghz`): geometry, GHz, km.
    Sub-6 GHz links attenuate too little in rain for a reliable inversion."""
    df = pd.DataFrame({c: cml[c].values for c in
                       ('site_0_lat', 'site_0_lon', 'site_1_lat', 'site_1_lon', 'band_tier')},
                      index=pd.Index(cml['sublink'].values, name='link'))
    df['freq_ghz'] = cml['freq_MHz'].values / 1000.0
    df['length_km'] = cml['length_m'].values / 1000.0
    df['lat'] = (df.site_0_lat + df.site_1_lat) / 2
    df['lon'] = (df.site_0_lon + df.site_1_lon) / 2
    return df[df['freq_ghz'] >= min_freq_ghz]


def cml_hourly_rain(
    cml: xr.Dataset,
    start, end,
    *,
    baseline: str = 'att_drymed',
    links: Optional[pd.DataFrame] = None,
    min_samples: int = 5,
) -> pd.DataFrame:
    """Hourly rain (mm, hour-ending) per CML sublink, (time × link).

    Pre-processing: attenuation from `baseline` (one of att_static / att_rollq /
    att_drymed / att_ewma, dB) → samples flagged `failure` dropped → ITU-R P.838-3
    power law R = (A / (k·L))^(1/α), negative A → 0 mm/h → hourly mean of the 10-min
    rates (= mm in the hour), NaN with fewer than `min_samples` of 6 samples.
    No wet-antenna correction: expect a positive bias in light rain. The power law is
    for liquid rain; values in snow/mix are attenuation-equivalent rain, not snowfall.
    """
    import sys
    sys.path.insert(0, str(REPO_ROOT / 'methods'))
    from cml_rainrate import rain_rate_from_attenuation

    links = cml_links(cml) if links is None else links
    h0, h1 = _hour_window(start, end)
    sub = cml.sel(sublink=links.index.values, time=slice(h0 - pd.Timedelta('1h'), h1))
    att = sub[baseline].where(sub['failure'] == 0).values          # (link, time)
    rate = rain_rate_from_attenuation(att, links['length_km'].values[:, None],
                                      links['freq_ghz'].values[:, None], 'V')
    rate = np.where(np.isfinite(att), rate, np.nan)                 # keep gaps as gaps
    df = pd.DataFrame(rate.T, index=pd.DatetimeIndex(sub['time'].values), columns=links.index)
    g = df.resample('1h', label='right', closed='right')
    hourly = g.mean().where(g.count() >= min_samples)
    return hourly.reindex(pd.date_range(h0, h1, freq='1h'))


# ============================================================================
# 4. Merge: every sensor next to the radar at its location
# ============================================================================

def merge_event(
    event,
    networks: Dict[str, Dict[str, xr.Dataset]],
    cml: Optional[xr.Dataset] = None,
    *,
    baseline: str = 'att_drymed',
    client=None,
    domain=None,
) -> pd.DataFrame:
    """Tidy hourly table for one event (a row of the catalog).

    Columns: event, cls, time (hour-ending UTC), network, sensor_id, lat, lon,
    sensor_mm, radar_mm, radar_only_mm. The radar columns (see `RADAR_COLUMNS`) are
    MRMS hourly QPE in the cell of each gauge, or averaged along each CML path (~250 m
    sampling): `radar_mm` = gauge-corrected Pass 2 (best estimate, but it has seen the
    ASOS gauges), `radar_only_mm` = radar-only (independent of every gauge). Rows where
    a value is missing are kept (NaN) so coverage can be audited.
    """
    from fetch_data.mrms import NYC, hourly_rainfall, path_average, sample_points
    domain = domain or NYC
    h0, h1 = _hour_window(event.start, event.end)
    radars = {col: hourly_rainfall(h0 - pd.Timedelta('1h'), h1, domain, product=prod, client=client)
              for col, prod in RADAR_COLUMNS.items()}
    parts = []

    stations = station_table(networks)
    for net, st in stations.groupby('network'):
        sens = gauge_hourly(networks[net], event.start, event.end)
        st = st[st.sensor_id.isin(sens.columns)]
        if st.empty:
            continue
        rads = {col: sample_points(r, st.lat.values, st.lon.values, names=st.sensor_id.values)
                     .to_pandas().reindex(sens.index)[st.sensor_id]           # (time × station)
                for col, r in radars.items()}
        parts.append(_tidy(sens[st.sensor_id], rads, st.set_index('sensor_id'), net))

    if cml is not None:
        links = cml_links(cml)
        sens = cml_hourly_rain(cml, event.start, event.end, baseline=baseline, links=links)
        rads = {col: path_average(r, links).to_pandas().T.reindex(sens.index)[sens.columns]
                for col, r in radars.items()}
        parts.append(_tidy(sens, rads, links, 'CML'))

    out = pd.concat(parts, ignore_index=True)
    out.insert(0, 'cls', event.cls)
    out.insert(0, 'event', event.event)
    return out


def merge_events(events: pd.DataFrame, networks, cml=None, *, verbose: bool = True, **kw) -> pd.DataFrame:
    """`merge_event` for every catalog row, concatenated (same columns)."""
    parts = []
    for ev in events.itertuples():
        parts.append(merge_event(ev, networks, cml, **kw))
        if verbose:
            print(f'  {ev.event:22s} {len(parts[-1]):6,d} rows', flush=True)
    return pd.concat(parts, ignore_index=True)


def _tidy(sens: pd.DataFrame, rads: Dict[str, pd.DataFrame], meta: pd.DataFrame,
          network: str) -> pd.DataFrame:
    def long(df, name):
        return df.rename_axis('time').reset_index().melt('time', var_name='sensor_id', value_name=name)
    df = long(sens, 'sensor_mm')
    for col, rad in rads.items():
        df = df.merge(long(rad, col), on=['time', 'sensor_id'])
    df['sensor_id'] = df['sensor_id'].astype(str)
    m = meta[['lat', 'lon']].rename_axis('sensor_id').reset_index().astype({'sensor_id': str})
    return df.merge(m, on='sensor_id').assign(network=network)[
        ['time', 'network', 'sensor_id', 'lat', 'lon', 'sensor_mm', *rads]]


# ============================================================================
# 5. Comparison
# ============================================================================

def scores(est, ref, wet_threshold: float = 0.1) -> dict:
    """Continuous + detection scores over jointly valid samples (from pcpn_maps).

    n, mean_ref, mean_est, bias, rel_bias (Σest/Σref − 1), mae, rmse,
    nrmse (= rmse / mean_ref, the headline metric), corr (Pearson), and
    pod / far / csi for 'wet' = value ≥ `wet_threshold` (mm).
    """
    e = np.asarray(est, dtype=float).ravel()
    r = np.asarray(ref, dtype=float).ravel()
    ok = np.isfinite(e) & np.isfinite(r)
    e, r = e[ok], r[ok]
    n = int(ok.sum())
    if n == 0:
        return {'n': 0}
    err = e - r
    mean_ref = float(r.mean())
    rmse = float(np.sqrt(np.mean(err ** 2)))
    hit = np.sum((e >= wet_threshold) & (r >= wet_threshold))
    miss = np.sum((e < wet_threshold) & (r >= wet_threshold))
    false = np.sum((e >= wet_threshold) & (r < wet_threshold))
    corr = float(np.corrcoef(e, r)[0, 1]) if n > 2 and e.std() > 0 and r.std() > 0 else np.nan
    return {
        'n': n, 'mean_ref': mean_ref, 'mean_est': float(e.mean()),
        'bias': float(err.mean()),
        'rel_bias': float(e.sum() / r.sum() - 1) if r.sum() > 0 else np.nan,
        'mae': float(np.abs(err).mean()), 'rmse': rmse,
        'nrmse': rmse / mean_ref if mean_ref > 0 else np.nan,
        'corr': corr,
        'pod': float(hit / (hit + miss)) if hit + miss else np.nan,
        'far': float(false / (hit + false)) if hit + false else np.nan,
        'csi': float(hit / (hit + miss + false)) if hit + miss + false else np.nan,
    }


def _scores_min(est, ref, wet_threshold, min_n) -> dict:
    """`scores`, with every metric NaN (n kept) when fewer than `min_n` samples."""
    s = scores(est, ref, wet_threshold)
    if s['n'] < min_n:
        s = {'n': s['n']}
    return s


def compare_sensors(
    merged: pd.DataFrame,
    *,
    by: Sequence[str] = ('network',),
    reference: str = 'radar_mm',
    wet_threshold: float = 0.1,
    min_n: int = 30,
) -> pd.DataFrame:
    """Hourly sensor vs. MRMS scores, grouped by `by` (e.g. ('cls', 'network')).
    `reference`: 'radar_mm' (gauge-corrected) or 'radar_only_mm' (gauge-independent).
    Groups with fewer than `min_n` sensor-hours get NaN metrics.
    Units: bias / mae / rmse in mm h⁻¹; nrmse, rel_bias, corr, pod, far, csi unitless."""
    rows = []
    for key, g in merged.groupby(list(by)):
        key = key if isinstance(key, tuple) else (key,)
        rows.append({**dict(zip(by, key)), 'n_sensors': g.sensor_id.nunique(),
                     **_scores_min(g.sensor_mm, g[reference], wet_threshold, min_n)})
    return pd.DataFrame(rows).set_index(list(by))


def compare_to_reference(
    merged: pd.DataFrame,
    *,
    reference: str = 'ASOS',
    max_km: float = 5.0,
    by: Sequence[str] = ('network',),
    wet_threshold: float = 0.1,
    min_n: int = 30,
) -> pd.DataFrame:
    """Sensor-to-sensor scores: every non-reference sensor within `max_km` of a
    `reference`-network gauge, hourly, against that gauge (the nearest one).
    MRMS at the same gauges is included as 'MRMS' and 'MRMS radar-only' rows.
    Groups with fewer than `min_n` pairs get NaN metrics."""
    from fetch_data.mrms import haversine_m
    ref = merged[merged.network == reference]
    ref_st = ref.groupby('sensor_id')[['lat', 'lon']].first()
    others = merged[merged.network != reference]
    st = others.groupby(['network', 'sensor_id'])[['lat', 'lon']].first().reset_index()
    d = haversine_m(st.lat.values[:, None], st.lon.values[:, None],
                    ref_st.lat.values[None, :], ref_st.lon.values[None, :]) / 1000
    st['ref_id'] = ref_st.index.values[d.argmin(1)]
    st['dist_km'] = d.min(1)
    st = st[st.dist_km <= max_km]
    pairs = others.merge(st[['network', 'sensor_id', 'ref_id', 'dist_km']], on=['network', 'sensor_id'])
    ref_v = ref[['event', 'cls', 'time', 'sensor_id', 'sensor_mm', *RADAR_COLUMNS]].rename(
        columns={'sensor_id': 'ref_id', 'sensor_mm': 'ref_mm'})
    pairs = pairs.merge(ref_v[['event', 'time', 'ref_id', 'ref_mm']], on=['event', 'time', 'ref_id'])
    radar_rows = [ref_v.assign(sensor_mm=ref_v[col], network=RADAR_LABELS[col],
                               sensor_id=ref_v.ref_id, dist_km=0.0) for col in RADAR_COLUMNS]
    allp = pd.concat([pairs, *radar_rows], ignore_index=True)
    rows = []
    for key, g in allp.groupby(list(by)):
        key = key if isinstance(key, tuple) else (key,)
        rows.append({**dict(zip(by, key)), 'n_sensors': g.sensor_id.nunique(),
                     'median_dist_km': float(g.drop_duplicates('sensor_id').dist_km.median()),
                     **_scores_min(g.sensor_mm, g.ref_mm, wet_threshold, min_n)})
    return pd.DataFrame(rows).set_index(list(by))


def phase_agreement(
    asos_net: Dict[str, xr.Dataset],
    events: pd.DataFrame,
    *,
    freq: str = '10min',
    client=None,
    domain=None,
) -> pd.DataFrame:
    """Crosstab of surface precip type: ASOS present-weather class (dominant per
    `freq` bin, wet bins only) vs MRMS PrecipFlag at the station's cell
    (snow = 3, rain = 1/6/7/10/91/96, none = 0). Counts of station-bins."""
    from fetch_data.mrms import NYC, RAIN_FLAGS, SNOW_FLAGS, MRMSClient, sample_points
    client = client or MRMSClient()
    domain = domain or NYC
    st = station_table({'ASOS': asos_net}).set_index('sensor_id')
    rows = []
    for ev in events.itertuples():
        flag = client.load('PrecipFlag', ev.start.floor(freq), ev.end.ceil(freq), domain, freq=freq)
        f = sample_points(flag, st.lat.values, st.lon.values, names=st.index.values).to_pandas()
        v = f.values                                                # (time, station)
        mrms = pd.DataFrame(np.select([np.isin(v, SNOW_FLAGS), np.isin(v, RAIN_FLAGS), v == 0],
                                      ['snow', 'rain', 'none'], 'nodata'),
                            index=f.index, columns=f.columns)
        for sid, ds in asos_net.items():
            c = _station_series(ds, 'precip_category').astype(str).loc[ev.start:ev.end]
            dom = c[c.isin(_WET)].resample(freq, label='right', closed='right').agg(
                lambda x: x.value_counts().index[0] if len(x) else None).dropna()
            m = mrms[sid].reindex(dom.index)
            rows.append(pd.DataFrame({'event': ev.event, 'cls': ev.cls, 'station': sid,
                                      'asos': dom.values, 'mrms': m.values}))
    df = pd.concat(rows, ignore_index=True).dropna()
    return pd.crosstab(df['asos'], df['mrms'], margins=True)


def event_totals_vs_ghcn(
    events: pd.DataFrame,
    networks: Dict[str, Dict[str, xr.Dataset]],
    ghcn_daily: pd.DataFrame,
    *,
    max_km: float = 5.0,
    client=None,
    domain=None,
) -> pd.DataFrame:
    """Event totals (mm) at each GHCN station vs. every sensor type.

    GHCN daily precipitation is the official, manually QC'd water equivalent — the
    fairest reference for snow, where tipping-bucket gauges under-catch. Window = the
    event's local-standard-time days (GHCN convention, UTC−5). Per GHCN station:
    ghcn_mm; MRMS and MRMS radar-only (hourly QPE summed in its cell); the mean event total of each
    network's gauges within `max_km` (hours with ≥ 80 % coverage, all hours required).
    """
    from fetch_data.mrms import NYC, haversine_m, hourly_rainfall, sample_points
    domain = domain or NYC
    g = ghcn_daily.assign(datetime=pd.to_datetime(ghcn_daily['datetime']))
    gst = g.groupby('station_id')[['lat', 'lon']].first()
    stations = station_table(networks)
    rows = []
    for ev in events.itertuples():
        d0 = (ev.start - pd.Timedelta('5h')).normalize()
        d1 = (ev.end - pd.Timedelta('5h')).normalize()
        w0, w1 = d0 + pd.Timedelta('5h'), d1 + pd.Timedelta('1D') + pd.Timedelta('5h')   # LST → UTC
        r_tot = {}
        for col, prod in RADAR_COLUMNS.items():
            radar = hourly_rainfall(w0, w1, domain, product=prod, client=client)
            r_tot[RADAR_LABELS[col]] = sample_points(
                radar.sum('time', min_count=radar.sizes['time']),
                gst.lat.values, gst.lon.values, names=gst.index.values).to_pandas()
        sens = {}
        for net in networks:
            if networks[net]:
                h = gauge_hourly(networks[net], w0 + pd.Timedelta('1min'), w1)
                sens[net] = h.sum(min_count=len(h))           # every hour must be valid
        for sid, (lat, lon) in gst.iterrows():
            obs = g[(g.station_id == sid) & g.datetime.between(d0, d1)]['precip_amount']
            row = dict(event=ev.event, cls=ev.cls, ghcn_station=sid,
                       ghcn_mm=float(obs.sum()) if obs.notna().all() and len(obs) else np.nan,
                       **{k: float(v[sid]) for k, v in r_tot.items()})
            for net, tot in sens.items():
                st = stations[(stations.network == net) & stations.sensor_id.isin(tot.index)]
                near = st[haversine_m(lat, lon, st.lat.values, st.lon.values) / 1000 <= max_km]
                row[net] = float(tot[near.sensor_id].mean()) if len(near) else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def totals_scores(totals: pd.DataFrame, *, by: Sequence[str] = ('cls',),
                  sensors: Sequence[str] = ('MRMS', 'MRMS radar-only', 'ASOS', 'WU PWS', 'Mesonet')
                  ) -> pd.DataFrame:
    """Scores of event totals vs GHCN (reference), per sensor and group."""
    rows = []
    for key, g in totals.groupby(list(by)):
        key = key if isinstance(key, tuple) else (key,)
        for s in sensors:
            if s in g:
                rows.append({**dict(zip(by, key)), 'sensor': s,
                             **scores(g[s], g['ghcn_mm'], wet_threshold=1.0)})
    return pd.DataFrame(rows).set_index([*by, 'sensor'])


# ============================================================================
# 6. Figures
# ============================================================================

# Fixed categorical order (dataviz reference palette, validated): identity never by rank.
NETWORK_COLORS = {'ASOS': '#2a78d6', 'WU PWS': '#eb6834', 'Mesonet': '#1baf7a',
                  'CML': '#eda100', 'MRMS': '#52514e', 'MRMS radar-only': '#a3a29c'}
NETWORK_ORDER = ('ASOS', 'WU PWS', 'Mesonet', 'CML')


def _style(ax):
    ax.grid(True, alpha=0.3)
    ax.spines[['top', 'right']].set_visible(False)


def plot_event_map(event, merged: pd.DataFrame, *, client=None, domain=None, vmax=None):
    """MRMS event accumulation (mm) with every gauge drawn in the same color scale
    (circle = ASOS, square = Mesonet, dot = WU PWS, small square = CML path midpoint), so a
    sensor that disagrees with the radar stands out by color."""
    import matplotlib.pyplot as plt
    from fetch_data.mrms import NYC, event_accumulation
    domain = domain or NYC
    h0, h1 = _hour_window(event.start, event.end)
    acc = event_accumulation(h0 - pd.Timedelta('1h'), h1, domain, client=client)
    m = merged[merged.event == event.event]
    tot = (m.groupby(['network', 'sensor_id'])
             .agg(lat=('lat', 'first'), lon=('lon', 'first'),
                  mm=('sensor_mm', lambda x: x.sum(min_count=len(x))))).reset_index()
    vmax = vmax or float(np.nanpercentile(acc.values, 99))
    fig, ax = plt.subplots(figsize=(7.5, 6.2))
    im = ax.pcolormesh(acc.lon, acc.lat, acc, cmap='Blues', vmin=0, vmax=vmax, shading='nearest')
    cmap, norm = im.cmap, im.norm
    if 'CML' in merged.network.values:
        links = m[m.network == 'CML'].groupby('sensor_id')[['lat', 'lon']].first()
        for sid, r in tot[tot.network == 'CML'].set_index('sensor_id').iterrows():
            if np.isfinite(r.mm) and sid in links.index:
                ax.plot(r.lon, r.lat, 's', ms=3, color=cmap(norm(r.mm)), mec='k', mew=0.3)
    for net, mk, ms in (('WU PWS', 'o', 5), ('Mesonet', 's', 9), ('ASOS', 'o', 11)):
        t = tot[(tot.network == net) & tot.mm.notna()]
        ax.scatter(t.lon, t.lat, c=t.mm, cmap=cmap, norm=norm, marker=mk, s=ms ** 2,
                   edgecolors='k', linewidths=0.8, label=f'{net} (n={len(t)})', zorder=3)
    fig.colorbar(im, ax=ax, label='event total (mm)', shrink=0.85)
    ax.set_xlabel('longitude (°)'); ax.set_ylabel('latitude (°)')
    ax.set_aspect(1 / np.cos(np.radians(40.7)))
    ax.set_title(f'{event.event}: MRMS QPE vs. sensors (same color scale)', loc='left', fontsize=10)
    ax.legend(loc='lower right', fontsize=8, frameon=True)
    fig.tight_layout()
    return {'fig': fig, 'ax': ax}


def plot_event_timeseries(merged: pd.DataFrame, event_name: str):
    """Network-mean hourly precipitation (mm/h): sensors vs. MRMS at the same
    locations, one panel per network (shared time axis, one y-axis each)."""
    import matplotlib.pyplot as plt
    m = merged[merged.event == event_name]
    nets = [n for n in NETWORK_ORDER if n in m.network.values]
    fig, axes = plt.subplots(len(nets), 1, sharex=True, figsize=(10, 2.1 * len(nets)), squeeze=False)
    for ax, net in zip(axes[:, 0], nets):
        g = m[m.network == net]
        both = g.dropna(subset=['sensor_mm', 'radar_mm']).groupby('time')[['sensor_mm', 'radar_mm']].mean()
        ax.plot(both.index, both.radar_mm, color=NETWORK_COLORS['MRMS'], lw=2, label='MRMS at sensors')
        ax.plot(both.index, both.sensor_mm, color=NETWORK_COLORS[net], lw=2, label=net)
        ax.set_ylabel('mm h⁻¹')
        ax.set_title(f'{net}  (n={g.sensor_id.nunique()})', loc='left', fontsize=9)
        ax.legend(loc='upper right', fontsize=8, frameon=False)
        _style(ax)
    axes[-1, 0].set_xlabel('time (UTC, hour-ending)')
    fig.suptitle(f'{event_name}: hourly network mean, sensor vs. radar', fontsize=10)
    fig.tight_layout()
    return {'fig': fig, 'axes': axes}


def plot_sensor_vs_radar(merged: pd.DataFrame, *, max_mm: Optional[float] = None):
    """Hourly sensor vs. MRMS scatter, one panel per network (all events pooled),
    1:1 line and NRMSE / r / relative bias in each panel. Each panel is scaled to its
    own 99.5th percentile (pass `max_mm` for a common scale)."""
    import matplotlib.pyplot as plt
    nets = [n for n in NETWORK_ORDER if n in merged.network.values]
    fig, axes = plt.subplots(1, len(nets), figsize=(3.4 * len(nets), 3.5), squeeze=False)
    ok = merged.dropna(subset=['sensor_mm', 'radar_mm'])
    for ax, net in zip(axes[0], nets):
        g = ok[ok.network == net]
        top = max_mm or max(1.0, float(np.nanpercentile(g[['sensor_mm', 'radar_mm']].values, 99.5)))
        ax.plot(g.radar_mm, g.sensor_mm, '.', ms=3, alpha=0.35, color=NETWORK_COLORS[net])
        ax.plot([0, top], [0, top], color='0.3', lw=1)
        s = scores(g.sensor_mm, g.radar_mm)
        ax.text(0.04, 0.96, f"NRMSE {s.get('nrmse', np.nan):.2f}\nr {s.get('corr', np.nan):.2f}\n"
                f"rel. bias {s.get('rel_bias', np.nan):+.0%}\nn {s['n']:,}",
                transform=ax.transAxes, va='top', fontsize=8)
        ax.set(xlim=(0, top), ylim=(0, top), title=net, xlabel='MRMS (mm h⁻¹)')
        _style(ax)
    axes[0, 0].set_ylabel('sensor (mm h⁻¹)')
    fig.tight_layout()
    return {'fig': fig, 'axes': axes}


def plot_scores_by_class(table: pd.DataFrame, metric: str = 'nrmse', *, title: str = ''):
    """Grouped bars of `metric` per class (x) and network/sensor (color).
    `table` is indexed by (cls, network) or (cls, sensor)."""
    import matplotlib.pyplot as plt
    t = table[metric].unstack()
    cols = [c for c in (*NETWORK_ORDER, 'MRMS', 'MRMS radar-only') if c in t.columns]
    t = t.reindex(index=[c for c in ('rain', 'mix', 'snow') if c in t.index], columns=cols)
    fig, ax = plt.subplots(figsize=(7, 3.6))
    w = 0.8 / len(cols)
    for i, c in enumerate(cols):
        x = np.arange(len(t)) + (i - (len(cols) - 1) / 2) * w
        ax.bar(x, t[c], width=w * 0.92, color=NETWORK_COLORS.get(c, '0.5'), label=c)
    ax.set_xticks(range(len(t)), t.index)
    ax.set_ylabel(metric)
    ax.set_title(title or f'{metric} by precipitation class', loc='left', fontsize=10)
    ax.legend(fontsize=8, frameon=False, ncol=len(cols))
    _style(ax)
    fig.tight_layout()
    return {'fig': fig, 'ax': ax}
