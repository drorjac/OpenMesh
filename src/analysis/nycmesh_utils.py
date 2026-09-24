"""
NYC Mesh signal analysis helpers — modular signal + weather correlation.

Designed to be driven by per-cell "knobs" in a notebook (PERIOD, AREA, LINKS,
BAND, TIME_RES). All selection logic lives in `build_signal()` /
`build_weather()`; plot helpers consume their output.

Primary data sources
--------------------
- nycmesh_data_20231029_to_20260430.nc  — 731 links × ~2.6M timestamps (8s),
  variables: rsl, rsl_remote, rsl_60g, rsl_60g_remote, device_name.
  NB: time axis is not monotonic — wraps. Always sort per-link series by time.
- ds_openmesh.nc + links_metadata.csv — 75-link subset with length / frequency /
  polarization / site lat-lon. Used to attach physical metadata when available.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
import xarray as xr


# ============================================================================
# Loading
# ============================================================================

def load_weather_networks(
    asos_nc: Optional[Union[str, Path]] = None,
    pws_nc:  Optional[Union[str, Path]] = None,
    meso_nc: Optional[Union[str, Path]] = None,
    *,
    apply_pws_qc: bool = True,
    verbose: bool = True,
) -> Dict[str, Dict[str, xr.Dataset]]:
    """Load ASOS / WU PWS / Mesonet into the {network: {sid: xr.Dataset}}
    shape that `build_weather()` consumes.

    ASOS files are written in OpenSense flat format (id × time); this reshapes
    them to {sid: ds} and renames `precip_amount` → `rainfall_amount` so
    downstream helpers stay variable-name agnostic. PWS stations marked
    'dropped' by the QC pipeline are filtered out when a QC table is present.
    Missing or `None` paths are silently skipped (empty network).
    """
    from analysis.netcdf_utils import load_pws_grouped
    from analysis.pws_qc import read_qc_status

    def _load_asos(p):
        if p is None or not Path(p).exists():
            return {}
        try:
            grouped = load_pws_grouped(p, verbose=False)
            if grouped:
                return grouped
        except Exception:
            pass
        ds = xr.open_dataset(p)
        out = {}
        for sid in ds.id.values:
            sub = ds.sel(id=sid).drop_vars('id', errors='ignore')
            if 'precip_amount' in sub.data_vars and 'rainfall_amount' not in sub.data_vars:
                sub = sub.rename({'precip_amount': 'rainfall_amount'})
            out[str(sid)] = sub
        return out

    def _load_pws(p):
        if p is None or not Path(p).exists():
            return {}
        pws = load_pws_grouped(p, verbose=False)
        if apply_pws_qc:
            try:
                qcs = read_qc_status(Path(p)).set_index('station')
                keep = qcs[qcs['qc_status'] != 'dropped'].index
                pws = {sid: pws[sid] for sid in keep if sid in pws}
            except Exception:
                pass
        return pws

    def _load_meso(p):
        if p is None or not Path(p).exists():
            return {}
        return load_pws_grouped(p, verbose=False)

    master = {
        'ASOS'   : _load_asos(asos_nc),
        'WU PWS' : _load_pws(pws_nc),
        'Mesonet': _load_meso(meso_nc),
    }
    if verbose:
        for name, net in master.items():
            print(f'  {name:10s} {len(net):3d} stations')
    return master


def open_nycmesh(path: Union[str, Path]) -> xr.Dataset:
    """Open the big NYC Mesh signal netCDF lazily (no full read).

    Uses dask chunks when dask is installed; otherwise falls back to a plain
    open (variables stay lazy via netCDF4's HDF5 backend)."""
    try:
        return xr.open_dataset(path, chunks={'time': 200_000})
    except ImportError:
        return xr.open_dataset(path)


def load_links_metadata(
    csv_path: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """Load per-sublink physical metadata (length, frequency, polarization,
    site lat/lon). Returned as one row per (cml_id, sublink_id)."""
    if csv_path is None:
        return pd.DataFrame()
    df = pd.read_csv(csv_path)
    if df.columns[0].startswith('Unnamed'):
        df = df.drop(columns=df.columns[0])
    return df


def collapse_metadata_per_cml(meta: pd.DataFrame) -> pd.DataFrame:
    """Collapse multi-sublink metadata to one row per cml_id with the
    representative length and the set of available frequencies."""
    if meta.empty:
        return meta
    g = meta.groupby('cml_id', dropna=False)
    out = pd.DataFrame({
        'cml_id'      : g['cml_id'].first().values,
        'length_m'    : g['length'].mean().values,
        'site_0_lat'  : g['site_0_lat'].first().values,
        'site_0_lon'  : g['site_0_lon'].first().values,
        'site_1_lat'  : g['site_1_lat'].first().values,
        'site_1_lon'  : g['site_1_lon'].first().values,
        'freqs_MHz'   : g['frequency'].agg(lambda s: sorted(set(int(x) for x in s.dropna()))).values,
        'polarization': g['polarization'].agg(lambda s: '/'.join(sorted(set(s.dropna())))).values,
        'n_sublinks'  : g.size().values,
    })
    out['has_5GHz']   = out['freqs_MHz'].apply(lambda fs: any(4000 <= f <= 8000 for f in fs))
    out['has_24GHz']  = out['freqs_MHz'].apply(lambda fs: any(20_000 <= f <= 28_000 for f in fs))
    out['has_60GHz']  = out['freqs_MHz'].apply(lambda fs: any(55_000 <= f <= 72_000 for f in fs))
    return out


# ============================================================================
# Per-link metadata derived from the big file
# ============================================================================

def link_table(ds: xr.Dataset, stride: int = 200) -> pd.DataFrame:
    """One row per cml_id with device_name and per-variable valid fraction.

    Coverage fractions are estimated on a stride-decimated time axis to avoid
    loading the full 8GB-per-variable arrays. Default `stride=200` yields ~13k
    samples spanning the full 2.6M-step file and runs in a few seconds.
    """
    valid = {}
    sub = ds.isel(time=slice(None, None, stride))
    n_sub = sub.dims['time']
    for var in ['rsl', 'rsl_remote', 'rsl_60g', 'rsl_60g_remote']:
        if var in ds.data_vars:
            arr = sub[var].values  # (n_sub, n_links)
            valid[var] = np.isfinite(arr).sum(axis=0)
    dev = ds['device_name'].values.astype(str)
    rows = []
    cml = ds.cml_id.values
    for i in range(len(cml)):
        row = {'cml_id': str(cml[i]), 'device_name': str(dev[i]) if i < len(dev) else ''}
        for var, arr in valid.items():
            row[f'valid_{var}'] = int(arr[i])
            row[f'frac_{var}']  = float(arr[i]) / max(n_sub, 1)
        rows.append(row)
    df = pd.DataFrame(rows)
    df['band'] = np.where(df.get('frac_rsl_60g_remote', 0) > df.get('frac_rsl_remote', 0),
                          '60GHz', '5GHz')
    return df


def attach_meta(link_df: pd.DataFrame, meta_cml: pd.DataFrame) -> pd.DataFrame:
    """Attempt to join physical metadata (length/freq) by cml_id text match.
    Note: the big file uses UUID-pair cml_ids while openmesh metadata uses
    numeric IDs ('1'..'75'); a direct join usually returns no matches and the
    physical fields end up NaN — that is expected. Length filtering then
    silently falls back to 'all'."""
    if meta_cml is None or meta_cml.empty:
        return link_df.copy()
    left  = link_df.copy()
    right = meta_cml.copy()
    left['cml_id']  = left['cml_id'].astype(str)
    right['cml_id'] = right['cml_id'].astype(str)
    return left.merge(right, on='cml_id', how='left')


# ============================================================================
# Link selection
# ============================================================================

def select_links(
    link_df: pd.DataFrame,
    spec: Union[str, int, Sequence[str], Tuple],
) -> List[str]:
    """Return a list of cml_ids matching the selection spec.

    Spec forms
    ----------
    'all'                              → every link
    int N                              → top-N links by combined valid fraction
    ['cml_id_1', ...]                  → explicit list
    ('device_pattern', regex)          → regex match on device_name
    ('valid_min', 0.05, var='rsl_remote') → fraction >= 0.05 for that variable
    ('top_valid', N, var='rsl_remote') → top-N by that variable
    ('band', '5GHz' | '60GHz')         → derived band column
    ('length_range', (min_m, max_m))   → physical link length (needs metadata)
    ('freq_range', (min_MHz, max_MHz)) → frequency band (needs metadata)
    """
    if link_df is None or link_df.empty:
        return []
    if spec == 'all' or spec is None:
        return list(link_df['cml_id'])
    if isinstance(spec, int):
        cols = [c for c in link_df.columns if c.startswith('frac_')]
        if not cols:
            return list(link_df['cml_id'].head(spec))
        score = link_df[cols].sum(axis=1)
        return list(link_df.loc[score.sort_values(ascending=False).index[:spec], 'cml_id'])
    if isinstance(spec, (list, set)):
        wanted = set(map(str, spec))
        return [c for c in link_df['cml_id'] if str(c) in wanted]
    if not isinstance(spec, tuple) or not spec:
        raise ValueError(f'Unknown LINKS spec: {spec!r}')

    kind = spec[0]
    if kind == 'device_pattern':
        pat = re.compile(spec[1])
        return list(link_df.loc[link_df['device_name'].astype(str).str.contains(pat), 'cml_id'])
    if kind == 'valid_min':
        thresh = spec[1]
        var = spec[2] if len(spec) > 2 else 'rsl_remote'
        col = f'frac_{var}'
        return list(link_df.loc[link_df[col] >= thresh, 'cml_id'])
    if kind == 'top_valid':
        n = spec[1]
        var = spec[2] if len(spec) > 2 else 'rsl_remote'
        col = f'frac_{var}'
        return list(link_df.sort_values(col, ascending=False).head(n)['cml_id'])
    if kind == 'band':
        return list(link_df.loc[link_df['band'] == spec[1], 'cml_id'])
    if kind == 'length_range':
        lo, hi = spec[1]
        if 'length_m' not in link_df.columns:
            return list(link_df['cml_id'])  # no metadata → keep all
        m = link_df['length_m'].between(lo, hi)
        return list(link_df.loc[m, 'cml_id'])
    if kind == 'freq_range':
        lo, hi = spec[1]
        if 'freqs_MHz' not in link_df.columns:
            return list(link_df['cml_id'])
        def _hits(fs):
            if not isinstance(fs, (list, tuple)):
                return False
            return any(lo <= f <= hi for f in fs)
        return list(link_df.loc[link_df['freqs_MHz'].apply(_hits), 'cml_id'])
    raise ValueError(f'Unknown LINKS spec: {spec!r}')


# ============================================================================
# Signal resampling
# ============================================================================

VAR_BY_BAND = {
    '5GHz' : ('rsl', 'rsl_remote'),
    '60GHz': ('rsl_60g', 'rsl_60g_remote'),
}


def _resolve_vars(band: str, end: str) -> List[str]:
    """Resolve (band, end) knobs to a list of actual netCDF variable names.

    band: '5GHz' | '60GHz' | 'all'
    end : 'local' | 'remote' | 'both'
    """
    if band == 'all':
        bands = ['5GHz', '60GHz']
    else:
        bands = [band]
    vars_ = []
    for b in bands:
        loc, rem = VAR_BY_BAND[b]
        if end in ('local', 'both'):
            vars_.append(loc)
        if end in ('remote', 'both'):
            vars_.append(rem)
    return vars_


def resample_signal(
    ds: xr.Dataset,
    cml_ids: Sequence[str],
    var: str,
    time_res: str = '1h',
    agg: str = 'mean',
    time_window: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None,
    time_mask: Optional[np.ndarray] = None,
) -> pd.DataFrame:
    """Return DataFrame[time × cml_id] of resampled RSL values.

    Internally: bulk-select the cml_ids in one read, sort time once (the
    source netCDF is not monotonic), drop NaN per column, then resample.
    Reading the whole (time × n_sel) slice once is dramatically faster than
    per-link `sel` calls because the netCDF file is chunked along `time`.

    Pre-filters (used to keep event-window calls cheap):
        time_window — (t0, t1) keeps only samples in that window before load
        time_mask   — boolean array aligned to ds.time
    """
    if not cml_ids:
        return pd.DataFrame()
    cml_arr = list(map(str, cml_ids))

    # Pre-filter at the time-index level to avoid decompressing the full
    # 2.6M-step array when an event window or day mask is requested.
    times_all = pd.to_datetime(ds.time.values)
    keep = np.ones(len(times_all), dtype=bool)
    if time_window is not None:
        t0, t1 = time_window
        keep &= (times_all.values >= np.datetime64(pd.Timestamp(t0))) & \
                (times_all.values <= np.datetime64(pd.Timestamp(t1)))
    if time_mask is not None:
        keep &= np.asarray(time_mask, dtype=bool)

    if not keep.all():
        idx_keep = np.where(keep)[0]
        sub = ds[var].isel(time=idx_keep).sel(cml_id=cml_arr)
        arr = sub.values
        times = times_all[idx_keep]
    else:
        sub = ds[var].sel(cml_id=cml_arr)
        arr = sub.values
        times = times_all

    order = np.argsort(times.values)
    times_sorted = times.values[order]
    cols = {}
    for j, cid in enumerate(cml_arr):
        col = arr[order, j]
        mask = np.isfinite(col)
        if not mask.any():
            continue
        s = pd.Series(col[mask], index=pd.DatetimeIndex(times_sorted[mask]))
        s = s[~s.index.duplicated(keep='first')]
        rs = s.resample(time_res)
        if agg == 'mean':
            cols[cid] = rs.mean()
        elif agg == 'median':
            cols[cid] = rs.median()
        elif agg == 'min':
            cols[cid] = rs.min()
        elif agg == 'max':
            cols[cid] = rs.max()
        elif agg == 'std':
            cols[cid] = rs.std()
        elif agg == 'count':
            cols[cid] = rs.count()
        else:
            raise ValueError(f'agg must be mean/median/min/max/std/count, got {agg!r}')
    return pd.concat(cols, axis=1) if cols else pd.DataFrame()


def signal_drop_from_baseline(
    df_rsl: pd.DataFrame,
    baseline: str = 'rolling',
    window: str = '24h',
    quantile: float = 0.95,
) -> pd.DataFrame:
    """Convert raw RSL (dBm) to **attenuation** relative to a clear-sky baseline.

    baseline:
        'rolling'  — per-link rolling `quantile` over `window` (preferred for
                     rain-attenuation analysis)
        'median'   — per-link global median
        'max'      — per-link global max
    Returns positive values (dB of fade); 0 means no fade.
    """
    if df_rsl.empty:
        return df_rsl
    if baseline == 'rolling':
        ref = df_rsl.rolling(window, min_periods=1).quantile(quantile)
    elif baseline == 'median':
        ref = df_rsl.median(axis=0)
        ref = pd.DataFrame(
            np.broadcast_to(ref.values, df_rsl.shape),
            index=df_rsl.index, columns=df_rsl.columns,
        )
    elif baseline == 'max':
        ref = df_rsl.max(axis=0)
        ref = pd.DataFrame(
            np.broadcast_to(ref.values, df_rsl.shape),
            index=df_rsl.index, columns=df_rsl.columns,
        )
    else:
        raise ValueError(f'unknown baseline {baseline!r}')
    return (ref - df_rsl).clip(lower=0)


# ============================================================================
# Period selection (shared with weather)
# ============================================================================

def select_period(
    df: pd.DataFrame,
    period: Union[str, Tuple[str, str], List],
    rainy_days: Optional[pd.Series] = None,
    snow_days: Optional[pd.Series]  = None,
    dry_days: Optional[pd.Series]   = None,
    pad_days: int = 1,
    window: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None,
) -> pd.DataFrame:
    """Mask a time-indexed DataFrame to a period selection.

    period:
        'all'                 — full window
        'rainy' / 'snow' / 'dry'
                              — keep ±pad_days around each day in the matching list
        (start, end)          — explicit datetime range
        ['2025-12-01', ...]   — list of explicit YYYY-MM-DD day labels (±pad_days)
    """
    if df.empty:
        return df
    if window is not None:
        df = df.loc[window[0]:window[1]]
    if period in (None, 'all'):
        return df
    if period in ('rainy', 'snow', 'dry'):
        days = {'rainy': rainy_days, 'snow': snow_days, 'dry': dry_days}[period]
        if days is None or len(days) == 0:
            print(f'  (no {period} days defined; returning full window)')
            return df
        mask = pd.Series(False, index=df.index)
        for d in pd.to_datetime(days.index):
            w0 = d - pd.Timedelta(days=pad_days)
            w1 = d + pd.Timedelta(days=pad_days)
            mask |= (df.index >= w0) & (df.index <= w1)
        return df.loc[mask]
    if isinstance(period, (tuple, list)) and len(period) == 2 \
            and isinstance(period[0], str) and ' ' not in period[0][:11]:
        # (start, end) string pair
        return df.loc[pd.Timestamp(period[0]):pd.Timestamp(period[1])]
    if isinstance(period, (list, tuple)):
        days = pd.to_datetime(list(period))
        mask = pd.Series(False, index=df.index)
        for d in days:
            w0 = d - pd.Timedelta(days=pad_days)
            w1 = d + pd.Timedelta(days=pad_days)
            mask |= (df.index >= w0) & (df.index <= w1)
        return df.loc[mask]
    raise ValueError(f'unknown PERIOD spec: {period!r}')


# ============================================================================
# Weather day-classifier (ASOS-driven)
# ============================================================================

def classify_weather_days(
    asos_dict: Dict[str, xr.Dataset],
    window: Tuple[pd.Timestamp, pd.Timestamp],
    rainy_threshold_mm: float = 10.0,
    dry_threshold_mm: float = 0.1,
    rain_var: str = 'rainfall_amount',
    mesonet_dict: Optional[Dict[str, xr.Dataset]] = None,
    snow_delta_threshold: float = 2.0,
) -> Dict[str, pd.Series]:
    """Compute per-day classification: dry / any-rain / wet / snow.

    Returns dict with `daily_rain`, `dry_days`, `any_rain_days`, `rainy_days`,
    `snow_days`. `*_days` are date-indexed pd.Series of the daily metric.
    """
    from analysis.pws_qc import network_resample
    h = network_resample(asos_dict, rain_var, '1h', 'sum').loc[window[0]:window[1]]
    daily = h.median(axis=1).resample('1D').sum(min_count=1)
    rainy = daily[daily >= rainy_threshold_mm].sort_values(ascending=False)
    dry   = daily[(daily.notna()) & (daily < dry_threshold_mm)]
    any_r = daily[daily >= dry_threshold_mm]

    snow = pd.Series(dtype=float)
    if mesonet_dict:
        try:
            ms = network_resample(mesonet_dict, 'snow_depth', '1D', 'max').loc[window[0]:window[1]]
            if not ms.empty:
                d = ms.median(axis=1).diff()
                snow = d[d >= snow_delta_threshold].sort_values(ascending=False)
        except Exception:
            pass
    return {
        'daily_rain'    : daily,
        'dry_days'      : dry,
        'any_rain_days' : any_r,
        'rainy_days'    : rainy,
        'snow_days'     : snow,
    }


# ============================================================================
# Rain / snow phase split (sub-daily)
# ============================================================================

def split_precip_by_phase(
    asos_dict: Dict[str, xr.Dataset],
    window: Tuple[pd.Timestamp, pd.Timestamp],
    *,
    rain_var: str = 'rainfall_amount',
    temp_var: str = 'temperature',
    freq: str = '1h',
    snow_max_c: float = 0.0,
    rain_min_c: float = 2.0,
    min_precip_mm: float = 0.1,
    reduce: str = 'mean',
) -> pd.DataFrame:
    """Classify each `freq`-bin of network-median precip into snow / mixed / rain / dry.

    Phase rule (per-bin, using network-median temperature):
        T <= snow_max_c            → 'snow'
        snow_max_c < T < rain_min_c → 'mixed'  (sleet / freezing rain band)
        T >= rain_min_c            → 'rain'
        precip < min_precip_mm     → 'dry'   (regardless of T)

    Returns
    -------
    DataFrame indexed by time (at `freq`) with columns:
        precip_mm  — network-median precipitation in the bin
        temp_c     — network-median temperature in the bin
        phase      — one of {'dry','snow','mixed','rain'}
        rain_mm, snow_mm, mixed_mm — precip routed to the matching phase, else 0
    """
    from analysis.pws_qc import network_resample

    t0, t1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    precip = network_resample(asos_dict, rain_var, freq, 'sum').loc[t0:t1]
    temp   = network_resample(asos_dict, temp_var, freq, 'mean').loc[t0:t1]
    if precip.empty or temp.empty:
        return pd.DataFrame(columns=['precip_mm','temp_c','phase','rain_mm','snow_mm','mixed_mm'])

    if reduce not in {'mean', 'median'}:
        raise ValueError(f"reduce must be 'mean' or 'median', got {reduce!r}")
    p = getattr(precip, reduce)(axis=1)
    t = getattr(temp,   reduce)(axis=1).reindex(p.index)

    phase = pd.Series('dry', index=p.index, dtype=object)
    wet   = p >= min_precip_mm
    phase[wet & (t <= snow_max_c)]                     = 'snow'
    phase[wet & (t >  snow_max_c) & (t < rain_min_c)]  = 'mixed'
    phase[wet & (t >= rain_min_c)]                     = 'rain'

    out = pd.DataFrame({
        'precip_mm': p,
        'temp_c'   : t,
        'phase'    : phase,
    })
    out['rain_mm']  = np.where(out['phase'] == 'rain',  out['precip_mm'], 0.0)
    out['snow_mm']  = np.where(out['phase'] == 'snow',  out['precip_mm'], 0.0)
    out['mixed_mm'] = np.where(out['phase'] == 'mixed', out['precip_mm'], 0.0)
    return out


def phase_event_table(
    df_split: pd.DataFrame,
    *,
    phase: str = 'snow',
    gap: str = '3h',
    min_total_mm: float = 1.0,
) -> pd.DataFrame:
    """Collapse contiguous `phase` bins (allowing short gaps) into events.

    Parameters
    ----------
    df_split     : output of `split_precip_by_phase`
    phase        : one of 'snow' / 'rain' / 'mixed'
    gap          : merge bins of the same phase if separated by ≤ `gap`
    min_total_mm : drop events whose total precip is below this

    Returns
    -------
    DataFrame with columns: start, end, duration_h, total_mm, peak_mm, mean_temp_c
    """
    if df_split.empty or phase not in {'snow', 'rain', 'mixed'}:
        return pd.DataFrame(columns=['start','end','duration_h','total_mm','peak_mm','mean_temp_c'])

    mask = df_split['phase'] == phase
    if not mask.any():
        return pd.DataFrame(columns=['start','end','duration_h','total_mm','peak_mm','mean_temp_c'])

    times = df_split.index[mask]
    gap_td = pd.Timedelta(gap)
    group_id = (times.to_series().diff().gt(gap_td)).cumsum()
    col = f'{phase}_mm'
    sub = df_split.loc[mask, [col, 'temp_c']].copy()
    sub['gid'] = group_id.values

    events = sub.groupby('gid').agg(
        start       = ('temp_c', lambda s: s.index.min()),
        end         = ('temp_c', lambda s: s.index.max()),
        total_mm    = (col,      'sum'),
        peak_mm     = (col,      'max'),
        mean_temp_c = ('temp_c', 'mean'),
    ).reset_index(drop=True)
    events['duration_h'] = (events['end'] - events['start']).dt.total_seconds() / 3600.0
    events = events[events['total_mm'] >= min_total_mm].sort_values('total_mm', ascending=False)
    return events[['start','end','duration_h','total_mm','peak_mm','mean_temp_c']].reset_index(drop=True)


# ---- Native sensor category vocabularies ---------------------------------
# ASOS `precip_type` codes that indicate snow / mixed-frozen / rain
# (per the precip_lookup_json embedded in asos_2023-10-01_2026-04-23.nc)
ASOS_SNOW_CODES  = {'S', 'S-', 'S+'}
ASOS_MIXED_CODES = {'I', 'IP', 'IP+', 'IP-', 'P', 'P?'}   # ice / sleet / mix
ASOS_RAIN_CODES  = {'R', 'R-', 'R+'}
# Freezing-rain / ice-pellet codes only. In this dataset the bare 'P'/'P?'
# codes fire at a 7-9 °C median (up to 23 °C) — they are NOT sleet, so they
# are excluded here; genuine ice (IP/I) is essentially absent and `ER`
# (freezing rain, median ≈ 0 °C) is the only real near-freezing mix signal.
ASOS_FREEZING_CODES = {'ER', 'I', 'IP', 'IP+', 'IP-'}
# WU PWS `condition` numeric codes (see pws_wu_merged_*_condition_lookup.json)
PWS_SNOW_CODES   = {14, 15, 28, 29, 30, 46, 47, 48}        # Heavy/Light Snow, Snow, Snow/Fog, Snow/Windy, ...
PWS_MIXED_CODES  = {12, 13, 20, 21, 27, 42, 43, 49, 50, 51, 52, 58, 59}
# (Heavy/Light Sleet, Freezing Drizzle/Rain, Sleet, Snow+Sleet, Wintry Mix, ...)


# ============================================================================
# Nearest-ASOS paired phase analysis
# ============================================================================

def _station_lat_lon(ds: xr.Dataset) -> Tuple[float, float]:
    lat = float(ds['lat'].values.flat[0]) if 'lat' in ds else np.nan
    lon = float(ds['lon'].values.flat[0]) if 'lon' in ds else np.nan
    return lat, lon


def _haversine_km(a, b) -> float:
    la1, lo1 = np.radians(a); la2, lo2 = np.radians(b)
    d = np.sin((la2-la1)/2)**2 + np.cos(la1)*np.cos(la2)*np.sin((lo2-lo1)/2)**2
    return 6371.0 * 2 * np.arcsin(np.sqrt(d))


def nearest_asos_pairing(
    target_net: Dict[str, xr.Dataset],
    asos_net:   Dict[str, xr.Dataset],
    *,
    leave_one_out: bool = False,
) -> pd.DataFrame:
    """For each target station, find its nearest ASOS station.

    Returns DataFrame: station, lat, lon, ref_asos, ref_lat, ref_lon, dist_km.
    Useful for the pairing map and for reporting average pairing distance.
    """
    asos_xy = {s: _station_lat_lon(d) for s, d in asos_net.items()}
    asos_xy = {s: xy for s, xy in asos_xy.items()
               if np.isfinite(xy[0]) and np.isfinite(xy[1])}
    rows = []
    for sid, ds in target_net.items():
        xy = _station_lat_lon(ds)
        if not (np.isfinite(xy[0]) and np.isfinite(xy[1])):
            continue
        cands = {a: _haversine_km(xy, axy) for a, axy in asos_xy.items()
                 if not (leave_one_out and a == sid)}
        ref = min(cands, key=cands.get)
        rows.append({
            'station': sid, 'lat': xy[0], 'lon': xy[1],
            'ref_asos': ref, 'ref_lat': asos_xy[ref][0], 'ref_lon': asos_xy[ref][1],
            'dist_km': round(cands[ref], 2),
        })
    return pd.DataFrame(rows)


def asos_phase_table(
    ds: xr.Dataset,
    freq: str = '15min',
    *,
    snow_temp_max: float = 3.0,
) -> pd.DataFrame:
    """Per-ASOS-station phase table at `freq`.

    A 15-min slot is assigned a phase only when precip is actually MEASURED
    (`rainfall_amount > 0`) AND the present-weather code matches:
        snow  : precip_type ∈ ASOS_SNOW_CODES  AND rain>0 AND temp < snow_temp_max
        mixed : precip_type ∈ ASOS_MIXED_CODES AND rain>0
        rain  : precip_type ∈ ASOS_RAIN_CODES  AND rain>0

    Returns DataFrame indexed at `freq` with columns: asos_rain_mm, snow, mixed, rain.
    """
    pt = ds['precip_type'].squeeze(drop=True).to_series().astype(str).str.strip()
    pt.index = pd.to_datetime(pt.index)
    rain = ds['rainfall_amount'].squeeze(drop=True).to_series()
    rain.index = pd.to_datetime(rain.index)
    temp = ds['temperature'].squeeze(drop=True).to_series()
    temp.index = pd.to_datetime(temp.index)

    snow_c = pt.isin(ASOS_SNOW_CODES ).resample(freq).max().fillna(0).astype(bool)
    mix_c  = pt.isin(ASOS_MIXED_CODES).resample(freq).max().fillna(0).astype(bool)
    rain_c = pt.isin(ASOS_RAIN_CODES ).resample(freq).max().fillna(0).astype(bool)
    rsum   = rain.resample(freq).sum(min_count=1)
    tmean  = temp.resample(freq).mean()
    has    = rsum > 0

    return pd.DataFrame({
        'asos_rain_mm': rsum,
        'snow' : snow_c & has & (tmean < snow_temp_max),
        'mixed': mix_c  & has,
        'rain' : rain_c & has,
    })


def paired_phase_response(
    target_net: Dict[str, xr.Dataset],
    asos_net:   Dict[str, xr.Dataset],
    *,
    freq: str = '15min',
    window: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None,
    snow_temp_max: float = 3.0,
    precip_var: str = 'rainfall_amount',
    leave_one_out: bool = False,
    phases: Sequence[str] = ('snow', 'mixed', 'rain'),
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Pair each target station to its NEAREST ASOS station and score its
    precipitation response during that ASOS's phase slots.

    For target station Y paired with ASOS X, within X's phase slots:
        total_mm   = Σ Y precip            (single-station accumulation)
        detect_pct = #(Y>0) / #(Y reporting, non-NaN) × 100
        intensity  = mean Y precip over slots where Y>0
        masscap_%  = total_mm(Y) / Σ X.asos_rain_mm over the same slots × 100

    `leave_one_out=True` (use when target_net IS asos_net): each ASOS station
    is paired with its nearest OTHER ASOS, so nothing is scored against itself.

    Returns (summary, per_station):
        summary    — index=phase, aggregated MEAN across target stations
        per_station — one row per (station, phase)
    """
    # ASOS coords + precomputed phase tables
    asos_xy = {s: _station_lat_lon(d) for s, d in asos_net.items()}
    asos_xy = {s: xy for s, xy in asos_xy.items() if np.isfinite(xy[0]) and np.isfinite(xy[1])}
    asos_tab = {s: asos_phase_table(asos_net[s], freq, snow_temp_max=snow_temp_max)
                for s in asos_xy}
    if window is not None:
        t0, t1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])
        asos_tab = {s: t.loc[t0:t1] for s, t in asos_tab.items()}

    def _nearest(sid, xy):
        cands = {a: _haversine_km(xy, axy) for a, axy in asos_xy.items()
                 if not (leave_one_out and a == sid)}
        return min(cands, key=cands.get), min(cands.values())

    rows = []
    for sid, ds in target_net.items():
        xy = _station_lat_lon(ds)
        if not (np.isfinite(xy[0]) and np.isfinite(xy[1])):
            continue
        ref, dist = _nearest(sid, xy)
        tab = asos_tab[ref]
        y = ds[precip_var].squeeze(drop=True).to_series()
        y.index = pd.to_datetime(y.index)
        y = y.resample(freq).sum(min_count=1).reindex(tab.index)
        for ph in phases:
            mask = tab[ph].values.astype(bool)
            n_slots = int(mask.sum())
            if n_slots == 0:
                continue
            yp = y[mask]
            reporting = int(yp.notna().sum())
            total = float(yp.sum(skipna=True))
            asos_ref = float(tab['asos_rain_mm'][mask].sum())
            wet = yp > 0
            rows.append({
                'station'   : sid,
                'ref_asos'  : ref,
                'dist_km'   : round(dist, 1),
                'phase'     : ph,
                'n_slots'   : n_slots,
                'reporting' : reporting,
                'coverage_pct': 100.0 * reporting / n_slots if n_slots else np.nan,
                'total_mm'  : total,
                # detection = % of the reference phase slots the station caught (precip>0),
                # counting only slots where the station was online (reporting). Offline slots
                # are not penalized (a station with no data couldn't have caught the snow).
                'detect_pct': (100.0 * int(wet.sum()) / reporting) if reporting else np.nan,
                'intensity_mm': float(yp[wet].mean()) if wet.any() else np.nan,
                'masscap_pct': (100.0 * total / asos_ref) if asos_ref > 0 else np.nan,
            })

    per_station = pd.DataFrame(rows)
    if per_station.empty:
        return pd.DataFrame(), per_station

    summary = per_station.groupby('phase').agg(
        n_stations   = ('station',     'nunique'),
        mean_n_slots = ('n_slots',     'mean'),
        mean_total_mm= ('total_mm',    'mean'),
        masscap_pct  = ('masscap_pct', 'mean'),
        intensity_mm = ('intensity_mm','mean'),
        detect_pct   = ('detect_pct',  'mean'),
        mean_dist_km = ('dist_km',     'mean'),
    )
    # order snow -> mixed -> rain
    order = [p for p in ('snow', 'mixed', 'rain') if p in summary.index]
    return summary.reindex(order), per_station


def phase_hours_native(
    net_dict: Dict[str, xr.Dataset],
    *,
    freq: str = '1h',
    cat_var: Optional[str] = None,
    snow_codes: Optional[set] = None,
    mixed_codes: Optional[set] = None,
    temp_var: str = 'temperature',
    precip_var: str = 'rainfall_amount',
    snow_max_c: float = 0.0,
    rain_min_c: float = 2.0,
    min_precip_mm: float = 0.1,
) -> pd.DataFrame:
    """Hourly snow/mixed classification using each station's *native sensor category*.

    For ASOS pass `cat_var='precip_type'` with `ASOS_SNOW_CODES` / `ASOS_MIXED_CODES`.
    For WU PWS pass `cat_var='condition'` with `PWS_SNOW_CODES` / `PWS_MIXED_CODES`.
    For Mesonet pass `cat_var=None` — uses a per-station T-rule fallback
    (precip ≥ min_precip_mm AND T ≤ snow_max_c for snow; 0 < T < rain_min_c for mixed).

    Aggregation across stations uses the **any-station** rule
    (a network hour is "snow" if ≥1 station fires), implemented as `max`.
    The per-station fraction is also returned for diagnostics.

    Returns DataFrame indexed by `freq`-stamped time with columns:
        snow_any   (0/1) — any station flagged snow that hour
        mixed_any  (0/1) — any station flagged mixed/sleet that hour
        snow_frac  (0-1) — fraction of stations flagging snow
        mixed_frac (0-1) — fraction flagging mixed
        temp_c           — network-median temperature in the hour
        precip_mm        — network-median precip in the hour
    """
    flags_s, flags_m = {}, {}
    temps,   precs   = {}, {}

    for sid, ds in net_dict.items():
        # Per-station snow / mixed flag (native cat where available, T-rule fallback)
        if cat_var is not None and cat_var in ds:
            cat = ds[cat_var].squeeze(drop=True).to_series()
            cat.index = pd.to_datetime(cat.index)
            if cat.dtype == object:
                cat = cat.astype(str).str.strip()
            snow_codes_  = snow_codes  or set()
            mixed_codes_ = mixed_codes or set()
            flags_s[sid] = cat.isin(snow_codes_ ).astype(float).resample(freq).max()
            flags_m[sid] = cat.isin(mixed_codes_).astype(float).resample(freq).max()
        elif temp_var in ds and precip_var in ds:
            t = ds[temp_var].squeeze(drop=True).to_series()
            t.index = pd.to_datetime(t.index)
            p = ds[precip_var].squeeze(drop=True).to_series()
            p.index = pd.to_datetime(p.index)
            t_h = t.resample(freq).mean()
            p_h = p.resample(freq).sum(min_count=1)
            wet = p_h >= min_precip_mm
            flags_s[sid] = (wet & (t_h <= snow_max_c)).astype(float)
            flags_m[sid] = (wet & (t_h >  snow_max_c) & (t_h < rain_min_c)).astype(float)

        # Always collect temp / precip for the network median
        if temp_var in ds:
            t = ds[temp_var].squeeze(drop=True).to_series()
            t.index = pd.to_datetime(t.index)
            temps[sid] = t.resample(freq).mean()
        if precip_var in ds:
            p = ds[precip_var].squeeze(drop=True).to_series()
            p.index = pd.to_datetime(p.index)
            precs[sid] = p.resample(freq).sum(min_count=1)

    def _frac(d):
        if not d: return pd.Series(dtype=float)
        return pd.concat(d, axis=1).mean(axis=1)
    def _any(d):
        if not d: return pd.Series(dtype=float)
        return pd.concat(d, axis=1).max(axis=1)
    def _med(d):
        if not d: return pd.Series(dtype=float)
        return pd.concat(d, axis=1).median(axis=1)

    return pd.DataFrame({
        'snow_any'  : _any(flags_s).fillna(0).astype(int),
        'mixed_any' : _any(flags_m).fillna(0).astype(int),
        'snow_frac' : _frac(flags_s),
        'mixed_frac': _frac(flags_m),
        'temp_c'    : _med(temps),
        'precip_mm' : _med(precs),
    })


def asos_bin_mask(
    asos_net: Dict[str, xr.Dataset],
    codes: set,
    freq: str = '30min',
    *,
    cat_var: str = 'precip_type',
    name: str = 'asos_bin',
    temp_range: Optional[Tuple[Optional[float], Optional[float]]] = None,
    temp_var: str = 'temperature',
) -> pd.Series:
    """Boolean Series at `freq` cadence: True iff any ASOS station reported
    a `precip_type` value in `codes` inside that bin (any-station rule).

    Optionally intersect with a temperature gate `temp_range=(t_min, t_max)`
    using the ASOS network-mean temperature in the bin (either bound may be
    None). Use this to remove ASOS `precip_type` sensor false-positives —
    e.g. `temp_range=(None, 0)` for "snow only when actually cold",
    `temp_range=(2, None)` for "rain only when actually warm".

    Use with `ASOS_SNOW_CODES` for active-snow bins, `ASOS_MIXED_CODES` for
    sleet/freezing-rain/wintry-mix bins.
    """
    flags = []
    for sid, ds in asos_net.items():
        if cat_var not in ds:
            continue
        s = ds[cat_var].squeeze(drop=True).to_series()
        s.index = pd.to_datetime(s.index)
        if s.dtype == object:
            s = s.astype(str).str.strip()
        flag = s.isin(codes).astype(float).resample(freq).max()
        flags.append(flag)
    if not flags:
        return pd.Series(dtype=bool, name=name)
    any_station = pd.concat(flags, axis=1).max(axis=1).fillna(0).astype(bool)
    any_station.name = name

    if temp_range is not None:
        from analysis.pws_qc import network_resample
        t = network_resample(asos_net, temp_var, freq, 'mean').mean(axis=1)
        t = t.reindex(any_station.index)
        t_min, t_max = temp_range
        gate = pd.Series(True, index=any_station.index)
        if t_min is not None:
            gate &= (t >= t_min)
        if t_max is not None:
            gate &= (t <= t_max)
        any_station = any_station & gate.fillna(False)

    return any_station


def asos_snow_bin_mask(asos_net, freq: str = '30min', **kw) -> pd.Series:
    """30-min mask of bins where any ASOS station reported pure snow (S/S-/S+)."""
    return asos_bin_mask(asos_net, ASOS_SNOW_CODES,
                         freq=freq, name='asos_snow_bin', **kw)


def asos_mixed_bin_mask(asos_net, freq: str = '30min', **kw) -> pd.Series:
    """30-min mask of bins where any ASOS station reported mixed/ice precipitation
    (I, IP, IP±, P, P?  — sleet / ice pellets / wintry-mix codes)."""
    return asos_bin_mask(asos_net, ASOS_MIXED_CODES,
                         freq=freq, name='asos_mixed_bin', **kw)


def asos_rain_bin_mask(asos_net, freq: str = '30min', **kw) -> pd.Series:
    """30-min mask of bins where any ASOS station reported rain (R/R-/R+)."""
    return asos_bin_mask(asos_net, ASOS_RAIN_CODES,
                         freq=freq, name='asos_rain_bin', **kw)


def network_catch_by_phase(
    asos_net: Dict[str, xr.Dataset],
    target_net: Dict[str, xr.Dataset],
    *,
    freq: str = '15min',
    precip_var: str = 'rainfall_amount',
    window: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None,
    exclude_stations: Optional[Iterable[str]] = None,
    phases: Optional[Dict[str, set]] = None,
) -> pd.DataFrame:
    """For each ASOS-flagged phase at `freq` cadence, score the target network's
    detection rate.

    A bin is "caught" if at least one station in `target_net` reports
    precipitation > 0 during that bin.

    Parameters
    ----------
    asos_net          : truth network (its `precip_type` defines phase bins)
    target_net        : the network whose catch rate we score (e.g. WU PWS
                        without airport-collocated stations)
    freq              : pandas offset ('15min', '30min', ...)
    exclude_stations  : station IDs to drop from `target_net` before scoring
    phases            : optional override of {phase_name: code_set}; defaults
                        to {'rain': ASOS_RAIN_CODES, 'mixed': ASOS_MIXED_CODES,
                            'snow': ASOS_SNOW_CODES}

    Returns
    -------
    DataFrame indexed by phase with columns:
        n_asos_bins         — bins ASOS flagged this phase
        n_caught            — bins ≥1 target station had precip > 0
        catch_pct           — n_caught / n_asos_bins * 100
        target_total_mm     — sum of target-network MEAN precip across those bins
        asos_total_mm       — sum of ASOS-network MEAN precip across those bins
        target_asos_pct     — target_total_mm / asos_total_mm * 100
        mean_intensity_mm   — mean target-network precip in caught bins (mm/bin)
        n_target_stations   — count of target stations after exclusion
    """
    from analysis.pws_qc import network_resample

    phases = phases or {'rain': ASOS_RAIN_CODES,
                        'mixed': ASOS_MIXED_CODES,
                        'snow':  ASOS_SNOW_CODES}

    excl = set(exclude_stations or ())
    target = {sid: ds for sid, ds in target_net.items() if sid not in excl}

    # Per-station, per-bin precip sum
    if not target:
        raise ValueError('target_net is empty after exclusion')
    tgt_precip = network_resample(target,   precip_var, freq, 'sum')
    asos_precip = network_resample(asos_net, precip_var, freq, 'sum')

    if window is not None:
        t0, t1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])
        tgt_precip  = tgt_precip.loc[t0:t1]
        asos_precip = asos_precip.loc[t0:t1]

    # Align ASOS and target onto a common index (union of their resampled grids)
    common_idx = tgt_precip.index.union(asos_precip.index).sort_values()
    tgt_max  = tgt_precip.max(axis=1).reindex(common_idx)
    tgt_mean = tgt_precip.mean(axis=1).reindex(common_idx)
    aso_mean = asos_precip.mean(axis=1).reindex(common_idx)

    rows = {}
    for ph_name, codes in phases.items():
        mask = asos_bin_mask(asos_net, codes, freq=freq)
        if window is not None:
            mask = mask.loc[window[0]:window[1]]
        mask = mask.reindex(common_idx).fillna(False).astype(bool)
        n_phase = int(mask.sum())
        if n_phase == 0:
            rows[ph_name] = dict(n_asos_bins=0, n_caught=0, catch_pct=np.nan,
                                  target_total_mm=0.0, asos_total_mm=0.0,
                                  target_asos_pct=np.nan, mean_intensity_mm=np.nan,
                                  n_target_stations=len(target))
            continue
        caught = (tgt_max[mask] > 0).fillna(False)
        target_total = float(tgt_mean[mask].fillna(0).sum())
        asos_total   = float(aso_mean[mask].fillna(0).sum())
        rows[ph_name] = dict(
            n_asos_bins       = n_phase,
            n_caught          = int(caught.sum()),
            catch_pct         = float(caught.mean() * 100),
            target_total_mm   = target_total,
            asos_total_mm     = asos_total,
            target_asos_pct   = (target_total / asos_total * 100) if asos_total > 0 else np.nan,
            mean_intensity_mm = float(tgt_mean[mask & (tgt_max > 0)].mean()),
            n_target_stations = len(target),
        )
    return pd.DataFrame(rows).T[
        ['n_asos_bins','n_caught','catch_pct',
         'target_total_mm','asos_total_mm','target_asos_pct',
         'mean_intensity_mm','n_target_stations']
    ]


def snow_response_timeseries(
    snow_day_index,
    networks: Dict[str, Dict[str, xr.Dataset]],
    *,
    freq: str = '30min',
    precip_var: str = 'rainfall_amount',
    temp_var:   str = 'temperature',
    pad_hours:  int = 0,
    active_mask: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """30-min (configurable) network-mean precip + temp **during snow days only**.

    For each network in `networks`:
      1. Resample every station to `freq` — precip with `sum(min_count=1)`,
         temperature with `mean`.
      2. Take the **mean across stations** at every timestep (the paper-grade
         "network response" reduction — uses every station equally).
      3. Mask to timestamps that fall inside one of the dates in
         `snow_day_index` (optionally widened by `pad_hours` on either side).

    Parameters
    ----------
    snow_day_index : index of pd.Timestamp / datetime (one per snow day)
    networks       : {network_name: {station_id: xr.Dataset}}
    freq           : pandas offset string ('30min', '15min', '1h', ...)
    pad_hours      : widen each snow day by ±pad_hours (catches storms that
                     wrap past midnight)

    Returns
    -------
    DataFrame indexed at `freq` cadence, restricted to snow-day windows,
    with two columns per network: `precip_{name}_mm`, `temp_{name}_c`.
    The aggregation across stations is **mean**, not median.
    """
    from analysis.pws_qc import network_resample
    days = pd.to_datetime(pd.Index(snow_day_index)).normalize().unique()
    if len(days) == 0:
        return pd.DataFrame()

    pieces = {}
    for net_name, net in networks.items():
        if not net:
            continue
        p = network_resample(net, precip_var, freq, 'sum')
        t = network_resample(net, temp_var,   freq, 'mean')
        pieces[f'precip_{net_name}_mm'] = p.mean(axis=1) if not p.empty else pd.Series(dtype=float)
        pieces[f'temp_{net_name}_c']    = t.mean(axis=1) if not t.empty else pd.Series(dtype=float)
    df = pd.concat(pieces, axis=1).sort_index()

    pad = pd.Timedelta(hours=pad_hours)
    keep = pd.Series(False, index=df.index)
    for d in days:
        t0 = d - pad
        t1 = d + pd.Timedelta(days=1) + pad
        keep |= (df.index >= t0) & (df.index < t1)

    # Optional: further restrict to bins where snow is actively falling
    if active_mask is not None and not active_mask.empty:
        m = active_mask.reindex(df.index).fillna(False).astype(bool)
        keep &= m

    return df[keep]


def load_ghcn_daily(
    csv_path: Union[str, Path],
    window: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None,
) -> pd.DataFrame:
    """Load the GHCN-Daily combined CSV (NOAA's QC'd daily summary).

    Columns expected: datetime, station_id, snowfall (mm liquid eq),
    snow_depth (mm), temperature_min/max/mean, precip_amount.

    Returns long-format DataFrame indexed by date with station_id column.
    """
    df = pd.read_csv(csv_path, parse_dates=['datetime']).rename(columns={'datetime': 'date'})
    if window is not None:
        df = df[(df['date'] >= pd.Timestamp(window[0])) & (df['date'] <= pd.Timestamp(window[1]))]
    return df.set_index('date')


def ghcn_snow_days(
    ghcn_df: pd.DataFrame,
    *,
    snowfall_min_mm:   float = 0.1,
    snow_depth_min_mm: float = 0.0,
) -> pd.DataFrame:
    """Reduce GHCN long-format daily to one row per snow day.

    A day is a snow day if any station had `snowfall >= snowfall_min_mm`
    OR any station had `snow_depth > snow_depth_min_mm`.
    """
    daily = ghcn_df.groupby(ghcn_df.index).agg(
        snowfall_max_mm   = ('snowfall',        'max'),
        snowfall_mean_mm  = ('snowfall',        'mean'),
        snowfall_n_st     = ('snowfall',        lambda s: int((s > 0).sum())),
        snow_depth_max_mm = ('snow_depth',      'max'),
        snow_depth_mean_mm= ('snow_depth',      'mean'),
        snow_depth_n_st   = ('snow_depth',      lambda s: int((s > 0).sum())),
        tmin_ghcn         = ('temperature_min', 'min'),
        tmax_ghcn         = ('temperature_max', 'max'),
        precip_ghcn_mm    = ('precip_amount',   'max'),
    )
    daily.index = pd.to_datetime(daily.index)
    is_snow_day = ((daily['snowfall_max_mm']   >= snowfall_min_mm) |
                   (daily['snow_depth_max_mm']  > snow_depth_min_mm))
    return daily[is_snow_day].sort_index()


def snow_day_stats(
    asos_net: Dict[str, xr.Dataset],
    pws_net:  Dict[str, xr.Dataset],
    meso_net: Dict[str, xr.Dataset],
    *,
    ghcn_df:  Optional[pd.DataFrame] = None,
    window:   Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None,
    snowfall_min_mm:      float = 0.1,
    snow_depth_min_mm:    float = 0.0,
    snow_depth_cm_thresh: float = 5.0,
    delta_snow_cm_thresh: float = 2.0,
) -> pd.DataFrame:
    """One row per *snow day*, aggregating every available source.

    **Snow day definition**:
      - If `ghcn_df` is provided → GHCN-Daily is the ground truth.
        A day is a snow day when any GHCN station has
        `snowfall >= snowfall_min_mm` or `snow_depth > snow_depth_min_mm`.
        GHCN is NOAA's QC'd daily product (sub-daily ASOS `precip_type` noise
        is filtered out), so this is the most reliable snow-day index.
      - If `ghcn_df` is None → falls back to the heuristic union of
        native-category hour flags + Mesonet snow_depth signals (noisy:
        ASOS `precip_type` produces summer false-positives).

    Per-station hourly classification (for the in-day columns):
        ASOS    — `precip_type` ∈ ASOS_SNOW_CODES / ASOS_MIXED_CODES (1-min)
        WU PWS  — `condition`   ∈ PWS_SNOW_CODES  / PWS_MIXED_CODES  (~hourly)
        Mesonet — no category code; per-station T-rule fallback
                  (precip ≥ 0.1 mm AND T ≤ 0 °C → snow; 0 < T < 2 °C → mixed)

    Aggregation: **any-station** rule per hour.

    Columns (suffix _A=ASOS, _P=PWS, _M=Mesonet):
        # GHCN truth (when ghcn_df supplied):
        snowfall_max_mm, snowfall_n_st, snow_depth_max_mm,
        snow_depth_n_st, tmin_ghcn, tmax_ghcn, precip_ghcn_mm
        # in-day from the high-cadence networks:
        snow_hours_A,  mixed_hours_A,  snow_mm_A,  mixed_mm_A,  min_t_A
        snow_hours_P,  mixed_hours_P,  total_precip_mm_P,        min_t_P
        snow_hours_M,  mixed_hours_M,  snow_mm_M,  mixed_mm_M,  min_t_M
        snow_depth_cm, d_snow_depth_cm    (Mesonet ultrasonic, cm)

    PWS doesn't report `snow_mm` (tipping-bucket misses frozen precip);
    `total_precip_mm_P` shows all PWS precip that day (catches delayed melt).
    """
    from analysis.pws_qc import network_resample

    hourly_A = phase_hours_native(asos_net,
                                  cat_var='precip_type',
                                  snow_codes=ASOS_SNOW_CODES,
                                  mixed_codes=ASOS_MIXED_CODES)
    hourly_P = phase_hours_native(pws_net,
                                  cat_var='condition',
                                  snow_codes=PWS_SNOW_CODES,
                                  mixed_codes=PWS_MIXED_CODES)
    hourly_M = phase_hours_native(meso_net, cat_var=None)  # T-rule fallback

    if window is not None:
        t0, t1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])
        hourly_A = hourly_A.loc[t0:t1]
        hourly_P = hourly_P.loc[t0:t1]
        hourly_M = hourly_M.loc[t0:t1]

    def _daily_heated(h):
        if h.empty:
            return pd.DataFrame()
        return pd.DataFrame({
            'snow_hours' : h['snow_any'].resample('1D').sum(),
            'mixed_hours': h['mixed_any'].resample('1D').sum(),
            'snow_mm'    : (h['precip_mm'] * h['snow_any']).resample('1D').sum(),
            'mixed_mm'   : (h['precip_mm'] * h['mixed_any']).resample('1D').sum(),
            'min_t'      : h['temp_c'].resample('1D').min(),
        })

    def _daily_pws(h):
        if h.empty:
            return pd.DataFrame()
        return pd.DataFrame({
            'snow_hours'      : h['snow_any'].resample('1D').sum(),
            'mixed_hours'     : h['mixed_any'].resample('1D').sum(),
            'total_precip_mm' : h['precip_mm'].resample('1D').sum(),
            'min_t'           : h['temp_c'].resample('1D').min(),
        })

    daily_A = _daily_heated(hourly_A).add_suffix('_A')
    daily_P = _daily_pws   (hourly_P).add_suffix('_P')
    daily_M = _daily_heated(hourly_M).add_suffix('_M')

    if meso_net:
        sd_cm = network_resample(meso_net, 'snow_depth', '1D', 'max')
        if window is not None:
            sd_cm = sd_cm.loc[window[0]:window[1]]
        sd_med = sd_cm.median(axis=1) if not sd_cm.empty else pd.Series(dtype=float)
        depth_df = pd.DataFrame({
            'snow_depth_cm'  : sd_med,
            'd_snow_depth_cm': sd_med.diff(),
        })
    else:
        depth_df = pd.DataFrame(columns=['snow_depth_cm','d_snow_depth_cm'])

    full = pd.concat([daily_A, daily_P, daily_M, depth_df], axis=1)
    full.index = pd.to_datetime(full.index).normalize()

    if ghcn_df is not None and not ghcn_df.empty:
        truth = ghcn_snow_days(ghcn_df,
                               snowfall_min_mm=snowfall_min_mm,
                               snow_depth_min_mm=snow_depth_min_mm)
        truth.index = pd.to_datetime(truth.index).normalize()
        if window is not None:
            truth = truth.loc[window[0]:window[1]]
        # Day index is GHCN-confirmed; attach in-day from the other networks
        return truth.join(full, how='left').sort_index()

    # Heuristic fallback (no GHCN): union of any flag
    def _col(c):
        return full[c].fillna(0) if c in full.columns else pd.Series(0, index=full.index)

    has_signal = (
        (_col('snow_hours_A')   > 0) | (_col('mixed_hours_A') > 0) |
        (_col('snow_hours_P')   > 0) | (_col('mixed_hours_P') > 0) |
        (_col('snow_hours_M')   > 0) | (_col('mixed_hours_M') > 0) |
        (_col('snow_depth_cm')  >= snow_depth_cm_thresh) |
        (_col('d_snow_depth_cm') >= delta_snow_cm_thresh)
    )
    return full[has_signal].sort_index()


# ============================================================================
# Convenience wrapper that combines all knobs
# ============================================================================

def _period_to_time_filter(
    ds: xr.Dataset,
    period,
    rainy_days, snow_days, dry_days, pad_days,
    window,
):
    """Convert a PERIOD knob to (time_window, time_mask) for resample_signal.

    Lets the caller skip decompressing the full 2.6M-step array when the
    period is a short window or a day-mask. Returns (None, None) for 'all'.
    """
    if period in (None, 'all'):
        return window, None
    if isinstance(period, (tuple, list)) and len(period) == 2 \
            and (isinstance(period[0], str) or isinstance(period[0], pd.Timestamp)) \
            and not (isinstance(period[0], str) and len(period[0]) > 10 and period[0][:1].isalpha()):
        t0 = pd.Timestamp(period[0])
        t1 = pd.Timestamp(period[1])
        return (t0, t1), None
    if period in ('rainy', 'snow', 'dry'):
        days = {'rainy': rainy_days, 'snow': snow_days, 'dry': dry_days}[period]
        if days is None or len(days) == 0:
            return window, None
        times = pd.to_datetime(ds.time.values)
        mask = np.zeros(len(times), dtype=bool)
        for d in pd.to_datetime(days.index):
            t0 = d - pd.Timedelta(days=pad_days)
            t1 = d + pd.Timedelta(days=pad_days)
            mask |= ((times.values >= np.datetime64(t0)) & (times.values <= np.datetime64(t1)))
        return window, mask
    return window, None


def build_signal(
    ds: xr.Dataset,
    link_df: pd.DataFrame,
    *,
    band: str = '5GHz',
    end: str = 'remote',
    links: Union[str, int, Tuple, Sequence] = 'all',
    period: Union[str, Tuple, Sequence] = 'all',
    time_res: str = '1h',
    agg: str = 'mean',
    window: Tuple[pd.Timestamp, pd.Timestamp] = None,
    rainy_days: Optional[pd.Series] = None,
    snow_days: Optional[pd.Series] = None,
    dry_days: Optional[pd.Series] = None,
    pad_days: int = 1,
) -> Dict[str, pd.DataFrame]:
    """Top-level "knobs" function for signal cells.

    Returns {var_name: DataFrame[time × cml_id]} for every variable implied by
    BAND × END. For band='all', end='both' you get four frames.
    """
    cml_ids = select_links(link_df, links)
    vars_ = _resolve_vars(band, end)
    tw, tm = _period_to_time_filter(ds, period, rainy_days, snow_days, dry_days, pad_days, window)
    out = {}
    for v in vars_:
        df = resample_signal(ds, cml_ids, v, time_res=time_res, agg=agg,
                             time_window=tw, time_mask=tm)
        # Final, exact masking (in case time_mask was coarse / no rolling slack)
        df = select_period(df, period, rainy_days=rainy_days, snow_days=snow_days,
                           dry_days=dry_days, pad_days=pad_days, window=window)
        out[v] = df
    return out


def build_weather(
    networks: Dict[str, Dict[str, xr.Dataset]],
    *,
    networks_keys: Union[str, Sequence[str]] = 'all',
    area: Union[str, Sequence, Tuple] = 'all',
    period: Union[str, Tuple, Sequence] = 'all',
    time_res: str = '1h',
    var: str = 'rainfall_amount',
    agg: str = 'sum',
    window: Tuple[pd.Timestamp, pd.Timestamp] = None,
    rainy_days: Optional[pd.Series] = None,
    snow_days: Optional[pd.Series] = None,
    dry_days: Optional[pd.Series] = None,
    pad_days: int = 1,
) -> Dict[str, pd.DataFrame]:
    """Top-level "knobs" function for weather cells.

    `networks` is a {name: {station: xr.Dataset}} dict (as returned by
    `load_weather_networks`). `area` accepts:
        'all'
        ['KJFK', 'KLGA']
        ('bbox', (lat_min, lat_max), (lon_min, lon_max))
        ('nearest', k, (lat0, lon0))
    """
    from analysis.pws_qc import network_resample, filter_stations_by_bbox

    def _haversine_km(lat1, lon1, lat2, lon2):
        R = 6371.0
        from math import radians, sin, cos, sqrt, atan2
        dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        return 2 * R * atan2(sqrt(a), sqrt(1 - a))

    def _xy(ds):
        for spot in (ds.coords, ds.data_vars):
            if 'lat' in spot and 'lon' in spot:
                return float(spot['lat'].values.flat[0]), float(spot['lon'].values.flat[0])
        return None, None

    def _apply_area(net, area_spec):
        if area_spec == 'all' or area_spec is None:
            return net
        if isinstance(area_spec, (list, set, tuple)) and area_spec \
                and all(isinstance(x, str) for x in area_spec):
            return {sid: net[sid] for sid in area_spec if sid in net}
        if isinstance(area_spec, tuple) and area_spec[0] == 'bbox':
            _, lat_range, lon_range = area_spec
            return filter_stations_by_bbox(net, lat_range, lon_range)
        if isinstance(area_spec, tuple) and area_spec[0] == 'nearest':
            _, k, (lat0, lon0) = area_spec
            scored = []
            for sid, ds in net.items():
                lat, lon = _xy(ds)
                if lat is None or np.isnan(lat) or np.isnan(lon):
                    continue
                scored.append((sid, _haversine_km(lat0, lon0, lat, lon)))
            scored.sort(key=lambda x: x[1])
            return {sid: net[sid] for sid, _ in scored[:k]}
        raise ValueError(f'unknown AREA spec: {area_spec!r}')

    names = list(networks) if networks_keys == 'all' else \
            [n for n in networks_keys if n in networks]
    out = {}
    for name in names:
        net = _apply_area(networks[name], area)
        if not net:
            out[name] = pd.DataFrame()
            continue
        df = network_resample(net, var, time_res, agg)
        df = select_period(df, period, rainy_days=rainy_days, snow_days=snow_days,
                           dry_days=dry_days, pad_days=pad_days, window=window)
        out[name] = df
    return out


# ============================================================================
# Geographic map of links + optional weather overlay
# ============================================================================

BAND_RANGES_MHZ = {
    '5GHz' : (4_000, 8_000),
    '24GHz': (20_000, 28_000),
    '60GHz': (55_000, 72_000),
}
BAND_COLORS = {
    '5GHz' : '#1f77b4',
    '24GHz': '#2ca02c',
    '60GHz': '#d62728',
    'other': '#999999',
    'unknown': '#bbbbbb',
}
STATION_COLORS = {'ASOS': 'red', 'WU PWS': 'orange', 'Mesonet': 'green'}


def _freq_to_band(f) -> str:
    if pd.isna(f):
        return 'unknown'
    for name, (lo, hi) in BAND_RANGES_MHZ.items():
        if lo <= f <= hi:
            return name
    return 'other'


def _filter_meta_for_map(
    meta: pd.DataFrame,
    *,
    area,
    n_links,
    band,
    min_coverage_days,
    active_only,
) -> pd.DataFrame:
    """Return a filtered copy of META suitable for the map plot.

    Adds a derived `band_` column so we don't collide with any pre-existing
    `band` column on a merged frame.
    """
    m = meta.copy()
    m['band_'] = m['frequency'].apply(_freq_to_band) if 'frequency' in m else 'unknown'
    if active_only and 'active' in m:
        m = m[m['active'].fillna(False)]
    if min_coverage_days and 'coverage_days' in m:
        m = m[m['coverage_days'].fillna(0) >= min_coverage_days]
    if band != 'all':
        m = m[m['band_'] == band]
    m = m.dropna(subset=['site_0_lat', 'site_0_lon', 'site_1_lat', 'site_1_lon'])

    if isinstance(area, tuple) and area and area[0] == 'bbox':
        (la0, la1), (lo0, lo1) = area[1], area[2]
        mid_lat = (m['site_0_lat'] + m['site_1_lat']) / 2
        mid_lon = (m['site_0_lon'] + m['site_1_lon']) / 2
        m = m[mid_lat.between(la0, la1) & mid_lon.between(lo0, lo1)]
    elif isinstance(area, tuple) and area and area[0] == 'nearest':
        _, k, (lat0, lon0) = area
        mid_lat = (m['site_0_lat'] + m['site_1_lat']) / 2
        mid_lon = (m['site_0_lon'] + m['site_1_lon']) / 2
        m = m.iloc[np.hypot(mid_lat - lat0, mid_lon - lon0).argsort().values[:k]]
    elif area not in ('all', None):
        raise ValueError(f'unknown AREA spec: {area!r}')

    if n_links is not None and 'coverage_days' in m:
        m = m.sort_values('coverage_days', ascending=False).head(n_links)
    return m


def _station_xy(ds: xr.Dataset) -> Tuple[Optional[float], Optional[float]]:
    for spot in (ds.coords, ds.data_vars):
        if 'lat' in spot and 'lon' in spot:
            return float(spot['lat'].values.flat[0]), float(spot['lon'].values.flat[0])
    return None, None


def plot_link_map(
    meta: pd.DataFrame,
    *,
    networks: Optional[Dict[str, Dict[str, xr.Dataset]]] = None,
    area: Union[str, Tuple] = 'all',
    n_links: Optional[int] = None,
    band: str = 'all',
    min_coverage_days: float = 0,
    active_only: bool = True,
    overlay: Sequence[str] = (),
    color_by: str = 'band',
    figsize: Tuple[float, float] = (10, 9),
    ax=None,
    save_path: Optional[Union[str, Path]] = None,
    verbose: bool = True,
):
    """Plot NYC Mesh links as line segments on lat/lon axes.

    Parameters
    ----------
    meta : pd.DataFrame
        Per-cml_id metadata (as loaded from `links_metadata_mapped.csv`).
        Required columns: site_0_lat, site_0_lon, site_1_lat, site_1_lon,
        frequency. Optional: active, coverage_days, length.
    networks : dict, optional
        {network_name: {sid: xr.Dataset}} for weather overlay. Datasets must
        carry `lat`/`lon` as coords or vars.
    area : 'all' | ('bbox', (lat0, lat1), (lon0, lon1)) | ('nearest', k, (lat0, lon0))
    n_links : keep only the top-N best-covered links after filtering.
    band : 'all' | '5GHz' | '24GHz' | '60GHz'
    min_coverage_days : drop links with fewer than this many valid days.
    active_only : keep only currently-active links.
    overlay : sequence of network names to draw as triangle markers.
              `()` or `[]` draws no weather points.
    color_by : 'band' | 'coverage' | 'length'
    save_path : if provided, save the figure here. **Defaults to no save.**

    Returns
    -------
    dict with keys 'fig', 'ax', 'meta' (filtered), 'sites' (unique endpoints).
    """
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    m = _filter_meta_for_map(
        meta, area=area, n_links=n_links, band=band,
        min_coverage_days=min_coverage_days, active_only=active_only,
    )

    if color_by == 'band':
        line_color = m['band_'].map(BAND_COLORS).values
    elif color_by == 'coverage':
        v = m['coverage_days'].fillna(0).values
        line_color = plt.cm.viridis((v - v.min()) / max(v.max() - v.min(), 1))
    elif color_by == 'length':
        v = m['length'].fillna(0).values
        line_color = plt.cm.plasma((v - v.min()) / max(v.max() - v.min(), 1))
    else:
        raise ValueError(f'unknown color_by: {color_by!r}')

    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure

    for col, (_, r) in zip(line_color, m.iterrows()):
        ax.plot([r['site_0_lon'], r['site_1_lon']],
                [r['site_0_lat'], r['site_1_lat']],
                color=col, lw=0.9, alpha=0.75, zorder=2)

    sites = pd.concat(
        [m[['site_0_lat', 'site_0_lon']].rename(columns={'site_0_lat': 'lat', 'site_0_lon': 'lon'}),
         m[['site_1_lat', 'site_1_lon']].rename(columns={'site_1_lat': 'lat', 'site_1_lon': 'lon'})],
        ignore_index=True,
    ).drop_duplicates()
    ax.scatter(sites['lon'], sites['lat'], s=10, color='black', alpha=0.55,
               zorder=3, label=f'mesh sites (n={len(sites)})')

    if networks and overlay:
        for net_name in overlay:
            if net_name not in networks:
                continue
            coords = [_station_xy(ds) for ds in networks[net_name].values()]
            coords = [(la, lo) for la, lo in coords if la is not None and np.isfinite(la)]
            if not coords:
                continue
            lats, lons = zip(*coords)
            ax.scatter(lons, lats, s=80, marker='^',
                       color=STATION_COLORS.get(net_name, 'purple'),
                       edgecolor='black', linewidth=0.6, zorder=4,
                       label=f'{net_name} (n={len(lats)})')

    extra = []
    if color_by == 'band':
        counts = m['band_'].value_counts()
        extra = [Line2D([0], [0], color=BAND_COLORS[b], lw=2,
                        label=f'{b}  (n={counts[b]})')
                 for b in counts.index]
    ax.legend(handles=extra + ax.get_legend_handles_labels()[0],
              loc='lower left', fontsize=9, framealpha=0.9)

    ax.set_xlabel('longitude')
    ax.set_ylabel('latitude')
    if len(sites):
        ax.set_aspect(1 / np.cos(np.deg2rad(sites['lat'].mean())))
    ax.grid(True, alpha=0.3)
    ax.set_title(f'NYC Mesh links  •  n_links={len(m)}  •  AREA={area!r}  '
                 f'•  BAND={band}  •  COLOR_BY={color_by}')
    fig.tight_layout()

    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')

    if verbose:
        print(f'Links shown: {len(m)}  •  unique sites: {len(sites)}')
        print('By band:')
        print(m['band_'].value_counts().to_string())
        if 'length' in m:
            L = m['length'].dropna()
            if len(L):
                print(f'Length (m)      : median={L.median():.0f}  '
                      f'min={L.min():.0f}  max={L.max():.0f}')
        if 'coverage_days' in m:
            C = m['coverage_days'].dropna()
            if len(C):
                print(f'Coverage (days) : median={C.median():.0f}  '
                      f'max={C.max():.0f}')

    return {'fig': fig, 'ax': ax, 'meta': m, 'sites': sites}


# ============================================================================
# Plot helpers (signal-vs-weather, CDFs, correlation matrix)
# ============================================================================

def signal_summary(df_rsl: pd.DataFrame, label: str = 'RSL') -> pd.DataFrame:
    """One-row summary across links for a signal DataFrame."""
    if df_rsl.empty:
        return pd.DataFrame()
    arr = df_rsl.values
    valid = np.isfinite(arr).sum()
    return pd.DataFrame([{
        'label'    : label,
        'links'    : df_rsl.shape[1],
        'samples'  : int(valid),
        'mean_dBm' : np.nanmean(arr),
        'median_dBm': np.nanmedian(arr),
        'p05_dBm'  : np.nanpercentile(arr, 5)  if valid else np.nan,
        'p95_dBm'  : np.nanpercentile(arr, 95) if valid else np.nan,
        'std_dBm'  : np.nanstd(arr),
    }])


def pair_signal_weather(
    signal_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    signal_agg: str = 'median',
    weather_agg: str = 'median',
) -> pd.DataFrame:
    """Align a signal frame and a weather frame on a common time index.

    Both DataFrames are reduced across their station-/link- columns using the
    given aggregator, then joined by index.
    """
    if signal_df.empty or weather_df.empty:
        return pd.DataFrame()
    def _reduce(df, how):
        return getattr(df, how)(axis=1)
    s = _reduce(signal_df, signal_agg)
    w = _reduce(weather_df, weather_agg)
    out = pd.concat({'signal': s, 'weather': w}, axis=1).dropna()
    return out


# ============================================================================
# Top-level plot wrappers — one per notebook cell. Never save by default.
# ============================================================================

def plot_signal_timeseries(
    signal, link_df, *,
    band='5GHz', end='remote',
    links=('top_valid', 20, 'rsl_remote'),
    period='all', time_res='1h', agg='mean',
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    figsize=None, save_path=None, verbose=True,
):
    """Per-link RSL traces + median, one panel per resolved RSL variable."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    sig = build_signal(signal, link_df, band=band, end=end, links=links,
                       period=period, time_res=time_res, agg=agg,
                       window=window, rainy_days=rainy_days,
                       snow_days=snow_days, dry_days=dry_days)
    if figsize is None:
        figsize = (13, max(3.0, 3.0 * len(sig)))
    fig, axes = plt.subplots(len(sig), 1, figsize=figsize, sharex=True, squeeze=False)
    for ax, (var, df) in zip(axes.flat, sig.items()):
        if df.empty:
            ax.text(0.5, 0.5, f'{var}: no data for these knobs',
                    transform=ax.transAxes, ha='center')
            continue
        for col in df.columns:
            ax.plot(df.index, df[col], lw=0.6, alpha=0.55)
        ax.plot(df.index, df.median(axis=1), color='black', lw=1.5, label='median')
        ax.set_ylabel(f'{var} (dBm)')
        ax.set_title(f'{var}  •  {df.shape[1]} links  •  PERIOD={period!r}  '
                     f'TIME_RES={time_res}')
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    fmt = (mdates.DateFormatter('%b %Y')
           if time_res in ('1D', '1h') and period == 'all'
           else mdates.DateFormatter('%m-%d %Hh'))
    axes[-1, 0].xaxis.set_major_formatter(fmt)
    for lab in axes[-1, 0].get_xticklabels():
        lab.set_rotation(30)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    if verbose:
        nonempty = {v: df for v, df in sig.items() if not df.empty}
        if nonempty:
            print('Signal summary across links:')
            print(pd.concat([signal_summary(df, var) for var, df in nonempty.items()],
                            ignore_index=True).to_string(index=False))
    return {'fig': fig, 'axes': axes, 'signal': sig}


def plot_ecdf_dry_vs_rainy(
    signal, link_df, *,
    band='all', end='remote',
    links=('top_valid', 50, 'rsl_remote'),
    time_res='1h', agg='mean', pad_days=0,
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    save_path=None, verbose=True,
):
    """Side-by-side ECDFs of RSL conditioned on dry vs rainy days."""
    import matplotlib.pyplot as plt

    def _ecdf(arr):
        arr = np.sort(arr[np.isfinite(arr)])
        if arr.size == 0:
            return np.array([]), np.array([])
        return arr, np.arange(1, arr.size + 1) / arr.size

    common = dict(band=band, end=end, links=links, time_res=time_res, agg=agg,
                  window=window, rainy_days=rainy_days, snow_days=snow_days,
                  dry_days=dry_days, pad_days=pad_days)
    sig_dry   = build_signal(signal, link_df, period='dry',   **common)
    sig_rainy = build_signal(signal, link_df, period='rainy', **common)
    vars_present = [v for v in sig_dry
                    if not sig_dry[v].empty or not sig_rainy[v].empty]
    fig, axes = plt.subplots(1, len(vars_present),
                             figsize=(5 * max(1, len(vars_present)), 4),
                             sharey=True, squeeze=False)
    for ax, var in zip(axes.flat, vars_present):
        x_d, y_d = (_ecdf(sig_dry[var].values.ravel())
                    if not sig_dry[var].empty else (np.array([]), np.array([])))
        x_r, y_r = (_ecdf(sig_rainy[var].values.ravel())
                    if not sig_rainy[var].empty else (np.array([]), np.array([])))
        if x_d.size:
            ax.plot(x_d, y_d, color='#1f77b4', lw=1.6,
                    label=f'dry   (n={x_d.size:,}, median={np.median(x_d):.1f})')
        if x_r.size:
            ax.plot(x_r, y_r, color='#d62728', lw=1.6,
                    label=f'rainy (n={x_r.size:,}, median={np.median(x_r):.1f})')
        ax.set_xlabel(f'{var} (dBm)')
        ax.set_ylabel('ECDF')
        ax.set_title(var)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8, loc='lower right')
    fig.suptitle(f'RSL ECDF — dry vs rainy  •  LINKS={links!r}', y=1.02)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'axes': axes, 'dry': sig_dry, 'rainy': sig_rainy}


def plot_signal_vs_rain(
    signal, link_df, networks, *,
    band='all', end='remote',
    links=('top_valid', 50, 'rsl_remote'),
    period='all', time_res='1h',
    weather_networks=('ASOS',), weather_area='all',
    weather_var='rainfall_amount',
    use_fade=True, fade_window='24h', fade_quantile=0.95,
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    save_path=None, verbose=True,
):
    """Per-timestamp scatter of weather (rain) vs link-median signal/fade."""
    import matplotlib.pyplot as plt
    sig = build_signal(signal, link_df, band=band, end=end, links=links,
                       period=period, time_res=time_res, agg='mean',
                       window=window, rainy_days=rainy_days,
                       snow_days=snow_days, dry_days=dry_days)
    wx = build_weather(networks, networks_keys=list(weather_networks),
                       area=weather_area, period=period, time_res=time_res,
                       var=weather_var, agg='sum', window=window,
                       rainy_days=rainy_days, snow_days=snow_days, dry_days=dry_days)
    wkey = next((k for k, v in wx.items() if not v.empty), None)
    if wkey is None:
        raise RuntimeError('No weather frames produced; '
                           'check weather_networks / weather_area.')
    rain = wx[wkey].median(axis=1)
    vars_present = [v for v in sig if not sig[v].empty]
    if not vars_present:
        if verbose:
            print('No non-empty signal frames; check links / period.')
        return {'fig': None, 'axes': None, 'signal': sig, 'rain': rain}
    fig, axes = plt.subplots(1, len(vars_present),
                             figsize=(5.2 * len(vars_present), 4.6),
                             squeeze=False)
    for ax, var in zip(axes.flat, vars_present):
        df_rsl = sig[var]
        if use_fade:
            df_rsl = signal_drop_from_baseline(df_rsl, window=fade_window,
                                               quantile=fade_quantile)
        y = df_rsl.median(axis=1)
        pair = pd.concat({'rain': rain, 'y': y}, axis=1).dropna()
        pair_r = pair[pair['rain'] > 0]
        if pair_r.shape[0] < 10:
            ax.text(0.5, 0.5, f'{var}: too few rainy points',
                    transform=ax.transAxes, ha='center')
            continue
        x, yv = pair_r['rain'].values, pair_r['y'].values
        ax.scatter(x, yv, s=8, alpha=0.35)
        slope, intercept = np.polyfit(x, yv, 1)
        ss_res = ((yv - (slope * x + intercept)) ** 2).sum()
        ss_tot = ((yv - yv.mean()) ** 2).sum()
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
        r = np.corrcoef(x, yv)[0, 1] if np.std(yv) > 0 else np.nan
        xx = np.linspace(0, x.max(), 100)
        ax.plot(xx, slope * xx + intercept, 'r-', lw=1.2,
                label=f'slope={slope:.2f}  R²={r2:.2f}  r={r:.2f}  n={len(x)}')
        ax.set_xlabel(f'{weather_var} {time_res} (mm)')
        ax.set_ylabel(f'{"fade (dB)" if use_fade else "RSL (dBm)"}: {var}')
        ax.set_title(var)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8, loc='upper right')
    fig.suptitle(f'Signal vs rain  •  LINKS={links!r}  •  PERIOD={period!r}', y=1.02)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'axes': axes, 'signal': sig, 'rain': rain}


def plot_signal_weather_corr(
    signal, link_df, networks, *,
    weather_vars=(('rainfall_amount', 'sum'),
                  ('temperature', 'mean'),
                  ('dewpoint', 'mean'),
                  ('wind_velocity', 'mean')),
    band='all', end='remote',
    links=('top_valid', 50, 'rsl_remote'),
    period='all', time_res='1h',
    weather_networks=('ASOS',), weather_area='all',
    use_fade=True,
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    save_path=None, verbose=True,
):
    """Pearson r heatmap: each signal variable vs each weather feature."""
    import matplotlib.pyplot as plt
    sig = build_signal(signal, link_df, band=band, end=end, links=links,
                       period=period, time_res=time_res, agg='mean',
                       window=window, rainy_days=rainy_days,
                       snow_days=snow_days, dry_days=dry_days)
    wx_med = {}
    for wv, agg in weather_vars:
        wx = build_weather(networks, networks_keys=list(weather_networks),
                           area=weather_area, period=period, time_res=time_res,
                           var=wv, agg=agg, window=window,
                           rainy_days=rainy_days, snow_days=snow_days, dry_days=dry_days)
        wkey = next((k for k, v in wx.items() if not v.empty), None)
        if wkey is not None:
            wx_med[wv] = wx[wkey].median(axis=1)
    if not wx_med:
        if verbose:
            print('No weather variables available — check weather_vars / weather_networks.')
        return {'corr_df': None, 'fig': None, 'ax': None}
    rows = []
    for var, df in sig.items():
        if df.empty:
            continue
        y = df.median(axis=1)
        if use_fade:
            y = signal_drop_from_baseline(df, window='24h', quantile=0.95).median(axis=1)
        row = {'signal': f'{var}{" (fade dB)" if use_fade else " (dBm)"}'}
        for wv, ws in wx_med.items():
            j = pd.concat({'a': y, 'b': ws}, axis=1).dropna()
            row[wv] = j['a'].corr(j['b']) if len(j) > 5 else np.nan
        row['n'] = int(
            pd.concat({'a': y, **{wv: ws for wv, ws in wx_med.items()}}, axis=1)
              .dropna().shape[0])
        rows.append(row)
    corr_df = pd.DataFrame(rows).set_index('signal').round(3)
    if verbose:
        print('Pearson correlation (signal vs weather):')
        print(corr_df.to_string())
    fig, ax = plt.subplots(figsize=(1.5 + 1.4 * len(wx_med),
                                    0.7 + 0.5 * len(corr_df)))
    m = corr_df.drop(columns=['n']).values.astype(float)
    im = ax.imshow(m, cmap='RdBu_r', vmin=-1, vmax=1, aspect='auto')
    cols = list(corr_df.columns.drop('n'))
    ax.set_xticks(range(m.shape[1]))
    ax.set_xticklabels(cols, rotation=30, ha='right')
    ax.set_yticks(range(m.shape[0]))
    ax.set_yticklabels(corr_df.index)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            ax.text(j, i, f'{m[i, j]:.2f}', ha='center', va='center',
                    color='white' if abs(m[i, j]) > 0.5 else 'black', fontsize=9)
    fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    ax.set_title(f'Signal–weather Pearson r  •  PERIOD={period!r}')
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'corr_df': corr_df, 'fig': fig, 'ax': ax}


def plot_event_zoom(
    signal, link_df, networks, *,
    period='auto-rainy',
    links=('top_valid', 30, 'rsl_remote'),
    band='5GHz', end='remote', time_res='15min',
    weather_networks='all', weather_area='all',
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    network_colors=None,
    save_path=None, verbose=True,
):
    """Multi-panel zoom on one event: rainfall (top), then fade + raw RSL.

    `period='auto-rainy'` picks the top rainy day (±1 day window).
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    if period == 'auto-rainy' and rainy_days is not None and len(rainy_days):
        d = rainy_days.index[0]
        period = ((d - pd.Timedelta(days=1)).strftime('%Y-%m-%d'),
                  (d + pd.Timedelta(days=2)).strftime('%Y-%m-%d'))
        if verbose:
            print(f'auto PERIOD: {period}')
    sig = build_signal(signal, link_df, band=band, end=end, links=links,
                       period=period, time_res=time_res, agg='mean',
                       window=window, rainy_days=rainy_days,
                       snow_days=snow_days, dry_days=dry_days)
    nets_arg = (list(weather_networks)
                if isinstance(weather_networks, (list, tuple))
                else weather_networks)
    wx_rain = build_weather(networks, networks_keys=nets_arg, area=weather_area,
                            period=period, time_res=time_res,
                            var='rainfall_amount', agg='sum', window=window,
                            rainy_days=rainy_days, snow_days=snow_days,
                            dry_days=dry_days)
    vars_present = [v for v in sig if not sig[v].empty]
    n_rows = 1 + 2 * max(len(vars_present), 1)
    fig, axes = plt.subplots(n_rows, 1, figsize=(13, 1.8 * n_rows), sharex=True)
    if n_rows == 1:
        axes = [axes]
    nc = network_colors or {}
    for name, df in wx_rain.items():
        if df.empty:
            continue
        c = nc.get(name.split()[0], '#666')
        axes[0].plot(df.index, df.median(axis=1), color=c, lw=1.4,
                     label=f'{name} median')
    axes[0].set_ylabel(f'rain {time_res} (mm)')
    axes[0].set_title(f'Event zoom — PERIOD={period!r}  BAND={band}')
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(fontsize=8, ncol=3)
    i_ax = 1
    for var in vars_present:
        df_rsl = sig[var]
        df_fade = signal_drop_from_baseline(df_rsl, window='24h', quantile=0.95)
        axes[i_ax].fill_between(df_fade.index, df_fade.quantile(0.25, axis=1),
                                df_fade.quantile(0.75, axis=1),
                                color='#d62728', alpha=0.2)
        axes[i_ax].plot(df_fade.index, df_fade.median(axis=1),
                        color='#d62728', lw=1.4, label=f'{var} fade median')
        axes[i_ax].set_ylabel('fade (dB)')
        axes[i_ax].grid(True, alpha=0.3)
        axes[i_ax].legend(fontsize=8)
        i_ax += 1
        for col in df_rsl.columns:
            axes[i_ax].plot(df_rsl.index, df_rsl[col], lw=0.5, alpha=0.5)
        axes[i_ax].plot(df_rsl.index, df_rsl.median(axis=1),
                        color='black', lw=1.4, label='median')
        axes[i_ax].set_ylabel(f'{var} (dBm)')
        axes[i_ax].grid(True, alpha=0.3)
        axes[i_ax].legend(fontsize=8)
        i_ax += 1
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %Hh'))
    for lab in axes[-1].get_xticklabels():
        lab.set_rotation(30)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'axes': axes, 'signal': sig, 'rain': wx_rain,
            'period': period}


def per_link_stats(
    signal, link_df, *,
    links=('top_valid', 50, 'rsl_remote'),
    band='5GHz', end='remote', time_res='1h',
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    plot_hist=True,
    save_table_path=None, save_hist_path=None,
    verbose=True,
):
    """Per-link summary + rainy-vs-dry comparison. Optional histogram of effect."""
    import matplotlib.pyplot as plt
    cml_ids = select_links(link_df, links)
    var_name = _resolve_vars(band, end)[0]
    df_all = resample_signal(signal, cml_ids, var_name, time_res, 'mean')
    df_all = select_period(df_all, 'all', rainy_days=rainy_days,
                           snow_days=snow_days, dry_days=dry_days, window=window)
    df_dry = select_period(df_all, 'dry', dry_days=dry_days, pad_days=0)
    df_rainy = select_period(df_all, 'rainy', rainy_days=rainy_days, pad_days=0)
    dev_lookup = link_df.set_index('cml_id')['device_name'].to_dict()
    rows = []
    for cid in df_all.columns:
        s = df_all[cid].dropna()
        s_dry = df_dry[cid].dropna() if cid in df_dry else pd.Series(dtype=float)
        s_rn = df_rainy[cid].dropna() if cid in df_rainy else pd.Series(dtype=float)
        rows.append({
            'cml_id': cid,
            'device_name': dev_lookup.get(cid, ''),
            'n_samples': int(len(s)),
            'mean_dBm': float(np.mean(s)) if len(s) else np.nan,
            'median_dBm': float(np.median(s)) if len(s) else np.nan,
            'std_dBm': float(np.std(s)) if len(s) else np.nan,
            'p05_dBm': float(np.percentile(s, 5)) if len(s) else np.nan,
            'p95_dBm': float(np.percentile(s, 95)) if len(s) else np.nan,
            'median_dry_dBm': float(np.median(s_dry)) if len(s_dry) else np.nan,
            'median_rainy_dBm': float(np.median(s_rn)) if len(s_rn) else np.nan,
            'rain_minus_dry_dB': (float(np.median(s_rn) - np.median(s_dry))
                                   if (len(s_rn) and len(s_dry)) else np.nan),
            'n_rainy': int(len(s_rn)),
            'n_dry': int(len(s_dry)),
        })
    stats = pd.DataFrame(rows).sort_values('rain_minus_dry_dB').round(3)
    if verbose:
        print(f'Per-link stats: {var_name}  •  {time_res}  •  {links}  •  '
              f'{len(stats)} links')
        print(stats.head(15).to_string(index=False))
    if save_table_path is not None:
        stats.to_csv(save_table_path, index=False)
        if verbose:
            print(f'saved table → {save_table_path}')
    out = {'stats': stats}
    if plot_hist:
        fig, ax = plt.subplots(figsize=(7, 4))
        v = stats['rain_minus_dry_dB'].dropna()
        if len(v):
            ax.hist(v, bins=30, color='#1f77b4', alpha=0.8)
            ax.axvline(0, color='black', lw=1)
            ax.axvline(v.median(), color='red', lw=1.5,
                       label=f'median = {v.median():.2f} dB')
            ax.legend()
        ax.set_xlabel('median RSL (rainy) − median RSL (dry)  [dB]')
        ax.set_ylabel('# links')
        ax.set_title(f'Per-link rain effect  ({band} {end}, {len(v)} links)')
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        if save_hist_path is not None:
            fig.savefig(save_hist_path)
            if verbose:
                print(f'saved hist → {save_hist_path}')
        out['fig'] = fig
        out['ax'] = ax
    return out


# ============================================================================
# Weather-only wrappers (used by weather_overview.ipynb / weather_inspect.ipynb)
# ============================================================================

def _resampled_nets(
    networks, *, var, agg, area='all', period='all', time_res='1h',
    networks_keys='all', window=None,
    rainy_days=None, snow_days=None, dry_days=None, pad_days=1,
):
    """Thin convenience: call build_weather with sensible defaults."""
    return build_weather(
        networks, networks_keys=networks_keys, area=area, period=period,
        time_res=time_res, var=var, agg=agg, window=window,
        rainy_days=rainy_days, snow_days=snow_days, dry_days=dry_days,
        pad_days=pad_days,
    )


def plot_station_locations_map(networks, *, basemap='folium', title=None):
    """Plot weather-station map. `basemap='folium'` for interactive HTML,
    `'static'` for a matplotlib fallback."""
    from analysis.pws_qc import station_map_folium, station_map_static
    if basemap == 'folium':
        return station_map_folium(networks)
    import matplotlib.pyplot as plt
    out = station_map_static(networks)
    if title:
        plt.title(title)
    return out


def plot_cumulative_rainfall(
    networks, *,
    area='all', period='all', time_res='1h', networks_keys='all',
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    overlay=True, save_path=None, verbose=True,
):
    """Cumulative rainfall per network (and optional overlay of hourly series)."""
    from analysis.pws_qc import plot_accumulation, plot_overlay
    nets = _resampled_nets(networks, var='rainfall_amount', agg='sum',
                           area=area, period=period, time_res=time_res,
                           networks_keys=networks_keys, window=window,
                           rainy_days=rainy_days, snow_days=snow_days,
                           dry_days=dry_days)
    fig_acc = plot_accumulation(nets)
    fig_ovl = plot_overlay(nets) if overlay else None
    if save_path is not None:
        fig_acc.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'nets': nets, 'fig_acc': fig_acc, 'fig_overlay': fig_ovl}


def plot_daily_temperature(
    networks, *,
    area='all', period='all', time_res='1D', networks_keys='all',
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    save_path=None, verbose=True,
):
    """Temperature time-series across networks (median + mean per network)."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from analysis.pws_qc import DEFAULT_COLORS
    nets = _resampled_nets(networks, var='temperature', agg='mean',
                           area=area, period=period, time_res=time_res,
                           networks_keys=networks_keys, window=window,
                           rainy_days=rainy_days, snow_days=snow_days,
                           dry_days=dry_days)
    fig, ax = plt.subplots(figsize=(14, 4))
    for name, df in nets.items():
        if df.empty:
            continue
        c = DEFAULT_COLORS.get(name.split()[0], '#666')
        ax.plot(df.index, df.median(axis=1), color=c, lw=1.4,
                label=f'{name} median ({df.shape[1]} st)')
        ax.plot(df.index, df.mean(axis=1), color=c, lw=1.0, ls='--',
                label=f'{name} mean')
    ax.axhline(0, color='black', lw=0.5, alpha=0.5)
    ax.set_ylabel('°C')
    ax.set_title(f'Temperature  •  TIME_RES={time_res}  PERIOD={period!r}  AREA={area!r}')
    fmt = (mdates.DateFormatter('%b %Y') if time_res in ('1D', '6h')
           else mdates.DateFormatter('%m-%d %Hh'))
    ax.xaxis.set_major_formatter(fmt)
    for lab in ax.get_xticklabels():
        lab.set_rotation(30)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'ax': ax, 'nets': nets}


def plot_snow_depth(
    networks, *,
    network_key='Mesonet',
    area='all', period='all', time_res='1D',
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    save_path=None, verbose=True,
):
    """Per-station snow depth (Mesonet by default) + median."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    nets = _resampled_nets(networks, var='snow_depth', agg='mean',
                           area=area, period=period, time_res=time_res,
                           networks_keys=[network_key], window=window,
                           rainy_days=rainy_days, snow_days=snow_days,
                           dry_days=dry_days)
    df = nets.get(network_key, pd.DataFrame())
    if df.empty:
        if verbose:
            print(f'No snow data for {network_key} with these knobs.')
        return {'fig': None, 'ax': None, 'df': df}
    fig, ax = plt.subplots(figsize=(14, 4))
    for sid in df.columns:
        ax.plot(df.index, df[sid], lw=1.2, label=sid)
    ax.plot(df.index, df.median(axis=1), lw=2.5, color='black', alpha=0.7,
            label='median')
    ax.set_ylabel('snow_depth')
    ax.set_title(f'{network_key} snow_depth  •  TIME_RES={time_res}  PERIOD={period!r}')
    ax.xaxis.set_major_formatter(
        mdates.DateFormatter('%b %Y') if time_res == '1D'
        else mdates.DateFormatter('%m-%d %Hh'))
    for lab in ax.get_xticklabels():
        lab.set_rotation(30)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'ax': ax, 'df': df}


def plot_weather_event(
    networks, period, *,
    area='all', time_res='1h', networks_keys='all',
    snow_network='Mesonet',
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    save_path=None, verbose=True,
):
    """3-panel event zoom: rainfall (top), temperature (mid), snow depth (bottom)."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from analysis.pws_qc import DEFAULT_COLORS
    rain_n = _resampled_nets(networks, var='rainfall_amount', agg='sum',
                             area=area, period=period, time_res=time_res,
                             networks_keys=networks_keys, window=window,
                             rainy_days=rainy_days, snow_days=snow_days,
                             dry_days=dry_days)
    temp_n = _resampled_nets(networks, var='temperature', agg='mean',
                             area=area, period=period, time_res=time_res,
                             networks_keys=networks_keys, window=window,
                             rainy_days=rainy_days, snow_days=snow_days,
                             dry_days=dry_days)
    snow_n = _resampled_nets(networks, var='snow_depth', agg='mean',
                             area=area, period=period, time_res=time_res,
                             networks_keys=[snow_network], window=window,
                             rainy_days=rainy_days, snow_days=snow_days,
                             dry_days=dry_days)
    fig, axes = plt.subplots(3, 1, figsize=(13, 7), sharex=True)
    for name, df in rain_n.items():
        if df.empty:
            continue
        c = DEFAULT_COLORS.get(name.split()[0], '#666')
        lo = df.quantile(0.25, axis=1)
        hi = df.quantile(0.75, axis=1)
        axes[0].fill_between(df.index, lo, hi, color=c, alpha=0.15)
        axes[0].plot(df.index, df.median(axis=1), color=c, lw=1.4,
                     label=f'{name} med')
        axes[0].plot(df.index, df.mean(axis=1), color=c, lw=1.0, ls='--',
                     label=f'{name} mean')
    axes[0].set_ylabel(f'rain {time_res} (mm)')
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(fontsize=7, ncol=2)
    for name, df in temp_n.items():
        if df.empty:
            continue
        c = DEFAULT_COLORS.get(name.split()[0], '#666')
        axes[1].plot(df.index, df.median(axis=1), color=c, lw=1.4,
                     label=f'{name} med')
    axes[1].axhline(0, color='black', lw=0.5, alpha=0.5)
    axes[1].set_ylabel('°C')
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(fontsize=8)
    snow_df = snow_n.get(snow_network, pd.DataFrame())
    if not snow_df.empty:
        for sid in snow_df.columns:
            axes[2].plot(snow_df.index, snow_df[sid], lw=1.0, label=sid)
        axes[2].legend(fontsize=8)
    axes[2].set_ylabel('snow_depth')
    axes[2].grid(True, alpha=0.3)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %Hh'))
    for lab in axes[-1].get_xticklabels():
        lab.set_rotation(30)
    fig.suptitle(f'Event zoom — PERIOD={period!r}  AREA={area!r}  TIME_RES={time_res}',
                 y=1.01)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'axes': axes,
            'rain': rain_n, 'temp': temp_n, 'snow': snow_df}


def weather_summary_table(
    networks, *,
    area='all', period='all', time_res='1h', networks_keys='all',
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    verbose=True,
) -> pd.DataFrame:
    """One-row-per-network summary: stations, total rain, mean/min/max temp, max snow."""
    rain_n = _resampled_nets(networks, var='rainfall_amount', agg='sum',
                             area=area, period=period, time_res=time_res,
                             networks_keys=networks_keys, window=window,
                             rainy_days=rainy_days, snow_days=snow_days,
                             dry_days=dry_days)
    temp_n = _resampled_nets(networks, var='temperature', agg='mean',
                             area=area, period=period, time_res=time_res,
                             networks_keys=networks_keys, window=window,
                             rainy_days=rainy_days, snow_days=snow_days,
                             dry_days=dry_days)
    snow_n = _resampled_nets(networks, var='snow_depth', agg='mean',
                             area=area, period=period, time_res='1D',
                             networks_keys=['Mesonet'], window=window,
                             rainy_days=rainy_days, snow_days=snow_days,
                             dry_days=dry_days)
    snow_df = snow_n.get('Mesonet', pd.DataFrame())
    rows = []
    for name, rh in rain_n.items():
        th = temp_n.get(name, pd.DataFrame())
        rows.append({
            'network'      : name,
            'stations'     : rh.shape[1],
            'total_rain_mm': round(rh.median(axis=1).sum(), 1) if not rh.empty else None,
            'rainy_hours'  : int((rh.median(axis=1) > 0.1).sum()) if not rh.empty else None,
            'max_hourly_mm': round(rh.max().max(), 1) if not rh.empty else None,
            'mean_temp_C'  : round(th.median(axis=1).mean(), 2) if not th.empty else None,
            'min_temp_C'   : round(th.median(axis=1).min(), 2)  if not th.empty else None,
            'max_temp_C'   : round(th.median(axis=1).max(), 2)  if not th.empty else None,
        })
    df = pd.DataFrame(rows)
    if not snow_df.empty:
        df.loc[df['network'] == 'Mesonet', 'max_snow']  = round(snow_df.max().max(), 2)
        df.loc[df['network'] == 'Mesonet', 'mean_snow'] = round(snow_df.mean(axis=1).mean(), 2)
    if verbose:
        print(df.to_string(index=False))
    return df


def plot_nan_coverage(
    networks, *,
    var='rainfall_amount', agg='sum', time_res='1h',
    area='all', period='all', networks_keys='all',
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    save_path=None, verbose=True,
):
    """Per-station percent-NaN bar charts, one panel per network."""
    import matplotlib.pyplot as plt
    from analysis.pws_qc import DEFAULT_COLORS
    nets = _resampled_nets(networks, var=var, agg=agg, area=area,
                           period=period, time_res=time_res,
                           networks_keys=networks_keys, window=window,
                           rainy_days=rainy_days, snow_days=snow_days,
                           dry_days=dry_days)
    n_panels = max(len(nets), 1)
    fig, axes = plt.subplots(1, n_panels, figsize=(5 * n_panels, 3.5))
    if n_panels == 1:
        axes = [axes]
    for ax, (name, df) in zip(axes, nets.items()):
        if df.empty:
            ax.text(0.5, 0.5, f'{name}: empty',
                    transform=ax.transAxes, ha='center')
            continue
        pct = (100 * df.isna().sum(axis=0) / df.shape[0]).sort_values()
        c = DEFAULT_COLORS.get(name.split()[0], '#666')
        ax.bar(range(len(pct)), pct.values, color=c)
        ax.set_title(f'{name}  median NaN={pct.median():.1f}%')
        ax.set_xlabel('station (sorted)')
        ax.set_ylabel('% NaN')
        ax.grid(True, alpha=0.3)
    fig.suptitle(f'NaN coverage  •  {var}  •  {time_res}', y=1.02)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'axes': axes, 'nets': nets}


def plot_network_scatter(
    networks, *,
    var='rainfall_amount', agg='sum', time_res='1h',
    area='all', period='all', networks_keys='all',
    rainy_only=True, rainy_threshold=0.1,
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    save_path=None, verbose=True,
):
    """Pairwise scatter of network-median values (one panel per pair)."""
    import matplotlib.pyplot as plt
    nets = _resampled_nets(networks, var=var, agg=agg, area=area,
                           period=period, time_res=time_res,
                           networks_keys=networks_keys, window=window,
                           rainy_days=rainy_days, snow_days=snow_days,
                           dry_days=dry_days)
    med = pd.DataFrame({n: df.median(axis=1)
                        for n, df in nets.items() if not df.empty}).dropna(how='all')
    names = list(med.columns)
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]]
    if not pairs:
        if verbose:
            print('Need at least 2 non-empty networks for scatter.')
        return {'fig': None, 'axes': None, 'med': med}
    fig, axes = plt.subplots(1, len(pairs), figsize=(5 * len(pairs), 4.5))
    if len(pairs) == 1:
        axes = [axes]
    for ax, (a, b) in zip(axes, pairs):
        sub = med[[a, b]].dropna()
        if rainy_only:
            sub = sub[(sub[a] > rainy_threshold) | (sub[b] > rainy_threshold)]
        if len(sub) < 10:
            ax.text(0.5, 0.5, 'too few points',
                    transform=ax.transAxes, ha='center')
            continue
        x, y = sub[a].values, sub[b].values
        ax.scatter(x, y, s=8, alpha=0.4)
        lim = max(x.max(), y.max()) * 1.05
        ax.plot([0, lim], [0, lim], 'k--', lw=0.6, label='y = x')
        slope = (x * y).sum() / (x * x).sum() if (x * x).sum() > 0 else np.nan
        ss_res = ((y - slope * x) ** 2).sum()
        ss_tot = ((y - y.mean()) ** 2).sum()
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
        ax.plot([0, lim], [0, slope * lim], 'r-', lw=1.2,
                label=f'slope={slope:.2f}  R²={r2:.2f}')
        ax.set_xlabel(a); ax.set_ylabel(b)
        ax.set_xlim(0, lim); ax.set_ylim(0, lim)
        ax.grid(True, alpha=0.3); ax.legend(fontsize=8)
        ax.set_title(f'n={len(sub)}')
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'axes': axes, 'med': med}


def _condition_str_to_phase(cond) -> Optional[str]:
    """Map a WU `condition` string to snow / mixed / rain by keyword.

    Returns None for conditions that name no precip type (Cloudy, Fog, Mist,
    Haze, …) so the caller can fall back. Order matters: the mixed test
    (sleet / freezing / wintry / ice pellets) runs first, so 'Snow and Sleet'
    and 'Light Freezing Rain' resolve to mixed rather than snow / rain.
    """
    if not cond or not isinstance(cond, str):
        return None
    c = cond.lower()
    if 'sleet' in c or 'freezing' in c or 'wintry' in c or 'ice pellet' in c:
        return 'mixed'
    if 'snow' in c:
        return 'snow'
    if 'rain' in c or 'drizzle' in c or 'storm' in c or 'thunder' in c:
        return 'rain'
    return None


def _wu_airport_phase(
    pws_net,
    *,
    window,
    freq: str = '1h',
    rule: str = 'mode',
    airport_ids: Sequence[str] = ('KJFK', 'KLGA'),
) -> pd.Series:
    """Per-bin phase from WU airport-station `condition` strings.

    Pools the named airport stations present in `pws_net`, decodes each
    station's numeric `condition` via the `condition_lookup` attached at load
    time, maps the string to snow/mixed/rain by keyword (`_condition_str_to_
    phase`), and reduces per bin:

    rule='mode' — plurality across all airport station-obs in the bin.
    rule='any'  — bin flagged for a category if any airport reported it
                  (mixed > snow > rain priority).

    Bins where no airport named a precip type are absent from the returned
    series, so the caller can cascade to another source.
    """
    t0, t1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    series = []
    for sid in airport_ids:
        ds = pws_net.get(sid)
        if ds is None or 'condition' not in ds:
            continue
        lookup = ds.attrs.get('condition_lookup')
        if not lookup:
            continue
        s = ds['condition'].squeeze(drop=True).to_series()
        s.index = pd.to_datetime(s.index)
        s = s.loc[t0:t1].dropna()
        if s.empty:
            continue
        ph = (s.astype(int).map(lookup)
                .map(_condition_str_to_phase).dropna())
        if not ph.empty:
            series.append(ph)
    if not series:
        return pd.Series(dtype=object)
    allph = pd.concat(series).sort_index()

    if rule == 'mode':
        return allph.groupby(pd.Grouper(freq=freq)).agg(
            lambda x: x.value_counts().idxmax() if len(x) else np.nan).dropna()
    if rule == 'any':
        d = pd.get_dummies(allph).groupby(pd.Grouper(freq=freq)).max()
        phase = pd.Series(index=d.index, dtype=object)
        has = lambda c: d[c] > 0 if c in d else pd.Series(False, index=d.index)
        phase[has('rain')]  = 'rain'
        phase[has('snow')]  = 'snow'
        phase[has('mixed')] = 'mixed'
        return phase.dropna()
    raise ValueError(f"rule must be 'mode' or 'any', got {rule!r}")


def rh_from_dewpoint(T_c, Td_c):
    """Relative humidity (%) from air temperature and dew point via the Magnus
    formula (Alduchov & Eskridge 1996 coefficients).

        e(T)  = 6.112 * exp(a*T / (b+T))            saturation vapour pressure
        RH    = 100 * e(Td) / e(T)
              = 100 * exp( a*Td/(b+Td) - a*T/(b+T) )
        a = 17.625,  b = 243.04 °C

    T_c, Td_c may be scalars, numpy arrays, or pandas objects (elementwise).
    Result is clipped to [0, 100] %. Used to feed `wet_bulb_stull`.

    Ref: Stull (2011); Magnus form per Alduchov & Eskridge (1996),
    J. Appl. Meteorol. 35, 601-609.
    """
    a, b = 17.625, 243.04
    rh = 100.0 * np.exp(a * Td_c / (b + Td_c) - a * T_c / (b + T_c))
    return np.clip(rh, 0.0, 100.0)


def wet_bulb_stull(T_c, RH_pct):
    """Wet-bulb temperature (°C) from air temperature (°C) and relative humidity
    (%) using Stull's (2011) empirical fit:

        Tw = T * arctan(0.151977 * sqrt(RH + 8.313659))
           + arctan(T + RH) - arctan(RH - 1.676331)
           + 0.00391838 * RH**1.5 * arctan(0.023101 * RH)
           - 4.686035

    arctan in radians; RH in %. The fit is valid roughly for -20..50 °C and
    5..99 % RH at sea-level pressure; outside that range it degrades but stays
    well-behaved. By construction Tw <= T (equality only at RH = 100 %).

    T_c, RH_pct may be scalars, numpy arrays, or pandas objects (elementwise).

    Ref: Stull, R. (2011). "Wet-bulb temperature from relative humidity and air
    temperature." J. Appl. Meteorol. Climatol. 50(11), 2267-2269.
    """
    T, RH = T_c, RH_pct
    Tw = (T * np.arctan(0.151977 * np.sqrt(RH + 8.313659))
          + np.arctan(T + RH) - np.arctan(RH - 1.676331)
          + 0.00391838 * RH ** 1.5 * np.arctan(0.023101 * RH)
          - 4.686035)
    # Enforce the physical constraint Tw <= T. Near saturation (RH ~ 99-100 %)
    # Stull's empirical fit can overshoot the dry-bulb by < 0.05 °C; clamp it.
    return np.minimum(Tw, T)


# Variable names a station may use for the inputs, in priority order.
_TEMP_VARS     = ('temperature',)
_RH_VARS       = ('relative_humidity',)
_DEWPOINT_VARS = ('dew_point', 'dewpoint')


def _first_series(ds: xr.Dataset, names) -> Optional[pd.Series]:
    """First present variable in `names` as a time-indexed Series, else None."""
    for v in names:
        if v in ds:
            s = ds[v].squeeze(drop=True).to_series()
            s.index = pd.to_datetime(s.index)
            return s
    return None


def _station_rh(ds: xr.Dataset) -> Optional[pd.Series]:
    """Per-station relative humidity (%) at the station's NATIVE resolution,
    using the station's OWN fields, in source-priority order:

      1. reported `relative_humidity`  — WU PWS / WU airports — clipped [0, 100].
      2. Magnus(temperature, dewpoint) — ASOS / NOAA, which carries no direct RH
         — via `rh_from_dewpoint`.

    Returns None if the station has neither (the caller cross-fills from the
    other networks). No resampling: the Series keeps the station's cadence.
    """
    rh = _first_series(ds, _RH_VARS)
    if rh is not None:
        return rh.clip(0.0, 100.0)
    T  = _first_series(ds, _TEMP_VARS)
    Td = _first_series(ds, _DEWPOINT_VARS)
    if T is not None and Td is not None:
        return rh_from_dewpoint(T, Td.reindex(T.index))
    return None


def _pool_across(networks, getter, freq='10min') -> Optional[pd.Series]:
    """Network-pooled mean of `getter(ds)` over every station in every network,
    on a common `freq` grid. Used only as the cross-fill source when a station
    lacks a parameter in its own fields."""
    cols = []
    for net in networks.values():
        for ds in net.values():
            s = getter(ds)
            if s is not None and not s.empty:
                cols.append(s.resample(freq).mean())
    if not cols:
        return None
    return pd.concat(cols, axis=1).mean(axis=1)


def add_wet_bulb_to_networks(
    networks: Dict[str, Dict[str, xr.Dataset]],
    *,
    out_var: str = 'wet_bulb',
    cross_fill: bool = True,
    pool_freq: str = '10min',
    fill_tolerance: str = '1h',
    verbose: bool = True,
) -> Dict[str, Dict[str, xr.Dataset]]:
    """Add a native-resolution wet-bulb temperature (`out_var`, °C) to every
    station in a {network: {sid: xr.Dataset}} dict (the shape returned by
    `load_weather_networks`). Returns a new dict; station Datasets are copied,
    inputs untouched.

    Per station, wet-bulb is `wet_bulb_stull(T, RH)` evaluated on the station's
    OWN time grid (no resampling), where:
      - T  : the station's own `temperature` (°C).
      - RH : the station's own RH via `_station_rh` — reported
             `relative_humidity` for WU (airports + PWS), else Magnus from
             `dewpoint` for ASOS/NOAA.
    If a station is missing a parameter in its own fields and `cross_fill` is
    set, the gap is filled from the pooled mean of all OTHER stations across all
    networks (`_pool_across` at `pool_freq`), reindexed onto the station's
    timestamps with `method='nearest'` within `fill_tolerance`. Wet-bulb keeps
    the Tw <= T clamp from `wet_bulb_stull`.

    The new variable carries units='degC' and a `rh_source` attribute recording
    which path produced its RH ('reported' | 'magnus' | 'cross_fill').
    """
    pooled_RH = _pool_across(networks, _station_rh, pool_freq) if cross_fill else None
    tol = pd.Timedelta(fill_tolerance)

    def _fill_from_pool(pool, index):
        if pool is None:
            return pd.Series(np.nan, index=index)
        return pool.reindex(index, method='nearest', tolerance=tol)

    out, tally = {}, {'reported': 0, 'magnus': 0, 'cross_fill': 0, 'skipped': 0}
    for net_name, net in networks.items():
        new_net = {}
        for sid, ds in net.items():
            T = _first_series(ds, _TEMP_VARS)
            if T is None:                                   # no own temperature
                # No target time axis to build wet-bulb on — skip (both ASOS and
                # WU always carry temperature, so this is purely defensive).
                tally['skipped'] += 1
                new_net[sid] = ds
                continue

            rh_src = 'reported' if any(v in ds for v in _RH_VARS) else (
                     'magnus' if any(v in ds for v in _DEWPOINT_VARS) else None)
            RH = _station_rh(ds)
            if RH is None and cross_fill:                   # borrow RH from others
                RH = _fill_from_pool(pooled_RH, T.index)
                rh_src = 'cross_fill'
            if RH is None:
                tally['skipped'] += 1
                new_net[sid] = ds
                continue

            RH = RH.reindex(T.index)
            if RH.isna().any() and cross_fill:              # patch residual gaps
                RH = RH.fillna(_fill_from_pool(pooled_RH, T.index))

            tw = wet_bulb_stull(T.to_numpy(), RH.to_numpy())
            tdim = ds[next(v for v in _TEMP_VARS if v in ds)].squeeze(drop=True).dims[0]
            da = xr.DataArray(
                tw, dims=[tdim], coords={tdim: T.index.values},
                attrs={'units': 'degC', 'long_name': 'wet-bulb temperature',
                       'method': 'Stull 2011', 'rh_source': rh_src or 'unknown'})
            ds2 = ds.copy()
            ds2[out_var] = da
            new_net[sid] = ds2
            tally[rh_src] = tally.get(rh_src, 0) + 1
        out[net_name] = new_net

    if verbose:
        print(f"  add_wet_bulb_to_networks → '{out_var}': "
              f"{tally['reported']} reported-RH, {tally['magnus']} Magnus, "
              f"{tally['cross_fill']} cross-filled, {tally['skipped']} skipped")
    return out


def _network_temp_frame(net_dict, freq, *, temp_type='air',
                        temp_var='temperature', dewpoint_var='dewpoint'):
    """Per-station temperature DataFrame (time x station) for a network.

    temp_type='air'  → the raw `temp_var` resampled to `freq` (mean).
    temp_type='bulb' → wet-bulb temperature: RH from temperature+dewpoint
                       (Magnus), then Stull (2011). Stations lacking dewpoint
                       contribute NaN; if the network has no dewpoint at all the
                       frame falls back to air temperature (so panels are not
                       silently emptied) — only ASOS carries dewpoint here.
    """
    from analysis.pws_qc import network_resample
    T = network_resample(net_dict, temp_var, freq, 'mean')
    if temp_type == 'air':
        return T
    if temp_type != 'bulb':
        raise ValueError(f"temp_type must be 'air' or 'bulb', got {temp_type!r}")
    Td = network_resample(net_dict, dewpoint_var, freq, 'mean')
    if Td.empty:
        return T                                  # no dewpoint -> fall back to air
    Td = Td.reindex(index=T.index, columns=T.columns)
    RH = rh_from_dewpoint(T, Td)
    return wet_bulb_stull(T, RH)


def _build_code_phase(
    networks,
    *,
    classify: str,
    window,
    freq: str = '1h',
    code_rule: str = 'mode',
    phase_ref: Optional[str] = None,
    snow_max_c: float = 0.0,
    rain_min_c: float = 2.0,
    reduce: str = 'mean',
    temp_var: str = 'temperature',
    temp_type: str = 'air',
    verbose: bool = True,
) -> Optional[pd.Series]:
    """Per-bin categorical phase series for the code-based classify modes.

    Returns None for classify='temp' (the caller derives phase from a temp
    band). For 'asos_codes' returns the ASOS present-weather phase; for
    'wu_airport' returns the cascade WU-airport-condition → ASOS-code →
    ASOS-temp-band. Shared by `plot_phase_temp_scatter` and
    `plot_precip_agreement_scatter` so the classification can't drift.
    """
    from analysis.pws_qc import network_resample
    if classify == 'temp':
        return None
    if classify == 'asos_codes':
        src = phase_ref or 'ASOS'
        if not networks.get(src):
            raise ValueError(f"classify='asos_codes' needs network {src!r} (with precip_type)")
        return _asos_code_phase(networks[src], window=window, freq=freq, rule=code_rule)
    if classify == 'wu_airport':
        if not networks.get('ASOS'):
            raise ValueError("classify='wu_airport' needs the ASOS network for fallback")
        t0, t1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])
        cond_phase = _wu_airport_phase(networks.get('WU PWS', {}), window=window,
                                       freq=freq, rule=code_rule)
        asos_code = _asos_code_phase(networks['ASOS'], window=window, freq=freq,
                                     rule=code_rule)
        Tasos = _network_temp_frame(networks['ASOS'], freq, temp_type=temp_type,
                                    temp_var=temp_var).loc[t0:t1]
        asos_temp = getattr(Tasos, reduce)(axis=1)
        temp_band = pd.Series(
            np.select([asos_temp <= snow_max_c, asos_temp < rain_min_c],
                      ['snow', 'mixed'], default='rain'),
            index=asos_temp.index, dtype=object)
        code_phase = cond_phase.combine_first(asos_code).combine_first(temp_band)
        if verbose:
            n_cond = len(cond_phase)
            n_code = len(asos_code.index.difference(cond_phase.index))
            n_temp = len(code_phase) - n_cond - n_code
            print(f'  wu_airport cascade — bins: {n_cond} WU-airport, '
                  f'{n_code} ASOS-code, {n_temp} ASOS-temp')
        return code_phase
    raise ValueError(
        f"classify must be 'temp', 'asos_codes' or 'wu_airport', got {classify!r}")


def _asos_code_phase(
    asos_net,
    *,
    window,
    freq: str = '1h',
    rule: str = 'mode',
    snow_codes: set = ASOS_SNOW_CODES,
    mixed_codes: set = ASOS_FREEZING_CODES,
    rain_codes: set = ASOS_RAIN_CODES,
    cat_var: str = 'precip_type',
) -> pd.Series:
    """Per-bin phase from ASOS observed `precip_type` present-weather codes.

    rule='mode' (default)
        The most-common precip category across *all* ASOS station-minutes in
        the bin (a plurality vote). Rare types like freezing rain stay rare.
    rule='any'
        Bin flagged for a category if *any* station reported it in the bin,
        with mixed overriding — this inflates rare types and is kept only for
        comparison.

    `mixed_codes` defaults to ASOS_FREEZING_CODES (ER / IP / I): the bare
    'P'/'P?' codes are excluded because in this dataset they fire at 7-9 °C
    and are not sleet. Bins with no precip code → 'dry'.
    """
    cat_map = {**{c: 'snow' for c in snow_codes},
               **{c: 'mixed' for c in mixed_codes},
               **{c: 'rain' for c in rain_codes}}
    t0, t1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    cats = []
    for sid, ds in asos_net.items():
        if cat_var not in ds:
            continue
        s = ds[cat_var].squeeze(drop=True).to_series()
        s.index = pd.to_datetime(s.index)
        s = s.astype(str).str.strip().map(cat_map).dropna().loc[t0:t1]
        if not s.empty:
            cats.append(s)
    if not cats:
        return pd.Series(dtype=object)
    allcat = pd.concat(cats).sort_index()

    if rule == 'mode':
        return allcat.groupby(pd.Grouper(freq=freq)).agg(
            lambda x: x.value_counts().idxmax() if len(x) else 'dry')
    if rule == 'any':
        d = pd.get_dummies(allcat).groupby(pd.Grouper(freq=freq)).max()
        phase = pd.Series('dry', index=d.index, dtype=object)
        has = lambda c: d[c] > 0 if c in d else pd.Series(False, index=d.index)
        phase[has('snow')] = 'snow'
        phase[has('rain')] = 'rain'
        phase[has('snow') & has('rain')] = 'mixed'
        phase[has('mixed')] = 'mixed'
        return phase
    raise ValueError(f"rule must be 'mode' or 'any', got {rule!r}")


def _phase_temp_frame(
    net_dict,
    *,
    window,
    freq: str = '1h',
    points: str = 'network',
    reduce: str = 'mean',
    snow_max_c: float = 0.0,
    rain_min_c: float = 2.0,
    min_precip_mm: float = 0.1,
    rain_var: str = 'rainfall_amount',
    temp_var: str = 'temperature',
    temp_type: str = 'air',
    ref_temp: Optional[pd.Series] = None,
    code_phase: Optional[pd.Series] = None,
    temp_guard: bool = True,
    snow_temp_ceiling: float = 6.0,
    mixed_temp_ceiling: float = 8.0,
) -> pd.DataFrame:
    """(time, precip_mm, temp_c, phase) rows for one network.

    points='network' → one row per bin from the network-reduced series.
    points='station' → one row per (station, bin), on its own precip.
    ref_temp : if given (a time-indexed temperature series), phase and the
        temp axis come from this reference instead of `net_dict`'s own
        temperature, so every network is classified on the same scale.
    temp_guard : physical-consistency veto. A categorical 'snow' label above
        `snow_temp_ceiling` °C, or 'mixed' above `mixed_temp_ceiling` °C, is
        non-physical (the ASOS present-weather code is unreliable at warm
        temperatures) and is reclassified to 'rain'. The temperature used is
        the same `temp_c` shown on the axis (ASOS when ref_temp is set).
    """
    from analysis.pws_qc import network_resample
    cols = ['time', 'precip_mm', 'temp_c', 'phase']
    t0, t1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    P = network_resample(net_dict, rain_var, freq, 'sum').loc[t0:t1]
    if P.empty:
        return pd.DataFrame(columns=cols)

    if points == 'network':
        precip = getattr(P, reduce)(axis=1)
        if ref_temp is None:
            T = _network_temp_frame(net_dict, freq, temp_type=temp_type,
                                    temp_var=temp_var).loc[t0:t1]
            if T.empty:
                return pd.DataFrame(columns=cols)
            temp = getattr(T, reduce)(axis=1).reindex(precip.index)
        else:
            temp = ref_temp.reindex(precip.index)
        df = pd.DataFrame({'time': precip.index,
                           'precip_mm': precip.to_numpy(),
                           'temp_c': temp.to_numpy()})
    elif points == 'station':
        precip = P.stack().rename('precip_mm')
        precip.index = precip.index.set_names(['time', 'station'])
        df = precip.reset_index()
        if ref_temp is None:
            T = _network_temp_frame(net_dict, freq, temp_type=temp_type,
                                    temp_var=temp_var).loc[t0:t1]
            if T.empty:
                return pd.DataFrame(columns=cols)
            temp = T.stack().rename('temp_c')
            temp.index = temp.index.set_names(['time', 'station'])
            df = df.merge(temp.reset_index(), on=['time', 'station'], how='inner')
        else:
            df['temp_c'] = df['time'].map(ref_temp)
    else:
        raise ValueError(f"points must be 'network' or 'station', got {points!r}")

    df = df.dropna(subset=['precip_mm', 'temp_c'])
    if code_phase is not None:
        cp = df['time'].map(code_phase).fillna('dry').to_numpy()
        df['phase'] = np.where(df['precip_mm'].to_numpy() < min_precip_mm, 'dry', cp)
    else:
        df['phase'] = np.select(
            [df['precip_mm'] < min_precip_mm,
             df['temp_c'] <= snow_max_c,
             df['temp_c'] < rain_min_c],
            ['dry', 'snow', 'mixed'], default='rain',
        )

    # Physical-consistency guard: a snow/mixed label too warm to be real
    # (unreliable warm ASOS present-weather codes) is reclassified to rain.
    if temp_guard:
        temp = df['temp_c'].to_numpy()
        ph   = df['phase'].to_numpy()
        ph = np.where((ph == 'snow')  & (temp > snow_temp_ceiling),  'rain', ph)
        ph = np.where((ph == 'mixed') & (temp > mixed_temp_ceiling), 'rain', ph)
        df['phase'] = ph
    return df[cols]


def plot_phase_temp_scatter(
    networks,
    *,
    window,
    freq: str = '1h',
    points: str = 'network',
    yscale: str = 'log',
    reduce: str = 'mean',
    classify: str = 'temp',
    code_rule: str = 'mode',
    phase_ref: Optional[str] = None,
    snow_max_c: float = 0.0,
    rain_min_c: float = 2.0,
    min_precip_mm: float = 0.1,
    common_bins: bool = True,
    temp_guard: bool = True,
    snow_temp_ceiling: float = 6.0,
    mixed_temp_ceiling: float = 8.0,
    colors: Optional[dict] = None,
    edge_colors: Optional[dict] = None,
    figsize: Tuple[float, float] = (18, 6),
    point_size: float = 8,
    alpha: float = 0.5,
    title_fs: float = 12,
    label_fs: float = 11,
    tick_fs: float = 10,
    legend_fs: float = 8,
    network_keys: Sequence[str] = ('ASOS', 'WU PWS', 'Mesonet'),
    rain_var: str = 'rainfall_amount',
    temp_var: str = 'temperature',
    temp_type: str = 'air',
    save_path=None,
    verbose: bool = True,
):
    """Precip-vs-temperature scatter, one panel per network, coloured by phase.

    Knobs
    -----
    freq        '5min' | '10min' | '1h' — bin width the split is computed at.
    points      'network' (one point per bin, reduced) | 'station'
                (one point per station-bin, classified on its own temp).
    yscale      'linear' | 'log'.
    classify    'temp'       → phase from a temperature band (snow_max_c /
                               rain_min_c); the 2 °C edge is a heuristic.
                'asos_codes' → snow/mixed/rain from ASOS observed present-
                               weather (`precip_type`); mixed = freezing rain
                               / ice only (warm 'P'/'P?' excluded). rain_min_c
                               is unused.
                'wu_airport' → per-bin cascade: WU airport-station `condition`
                               (KJFK / KLGA) where it names a precip type,
                               else ASOS present-weather codes, else the ASOS
                               temperature band. The most direct categorical
                               label available, with graceful fallback.
    code_rule   asos_codes / wu_airport aggregation: 'mode' = most-common type
                per bin; 'any' = any-source flag.
    phase_ref   None → each network is classified by its own temperature;
                a network key (e.g. 'ASOS') → that network's temperature
                decides the phase for every panel, so the snow/mixed/rain
                membership of each bin is identical across panels.
    common_bins restrict every network to the bin intervals shared by all
                of them, so the panels are computed over the same grid.
    temp_guard  physical-consistency veto on the categorical phase: 'snow'
                above snow_temp_ceiling °C and 'mixed' above mixed_temp_ceiling
                °C are reclassified to 'rain' (the warm ASOS present-weather
                codes are unreliable). Uses the displayed (ASOS) temperature.
    temp_type   'air' (default) → dry-bulb temperature; 'bulb' → wet-bulb
                temperature (Stull 2011) from ASOS temp + dewpoint, used for the
                temp axis, the temp-band fallback and temp_guard. Wet-bulb is the
                more physical predictor of precipitation phase (Jennings et al.
                2018). Only ASOS carries dewpoint, so use phase_ref='ASOS'.
    colors      dict to override face colours per phase, e.g.
                {'snow': '#00e5ff', 'mixed': '#e377c2', 'rain': '#2166ac'};
                any subset is merged over the defaults.
    edge_colors dict to override marker edge colours per phase; by default the
                snow/mixed edges auto-darken from their face colour (rain = none).
    figsize     overall figure size; point_size / alpha control the markers.
    title_fs / label_fs / tick_fs / legend_fs
                font sizes for titles, axis labels, tick labels, legend.

    Network means skip NaNs: each bin's value is the mean over the stations
    that actually reported in that bin (pandas `.mean` is skipna=True).

    Note: at `freq` finer than a network's native cadence (ASOS ≈ 1 min,
    Mesonet ≈ 5 min, WU PWS ≈ 1 h) that network's bins go mostly empty.
    """
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        'font.size': 12,
        'axes.labelsize': 13,
        'xtick.labelsize': 11,
        'ytick.labelsize': 11,
        'legend.fontsize': 11,
        'legend.title_fontsize': 11,
    })

    keys = [k for k in network_keys if networks.get(k)]
    if not keys:
        if verbose:
            print('No non-empty networks to plot.')
        return {'fig': None, 'axes': None}

    ref_temp = None
    if phase_ref is not None:
        if not networks.get(phase_ref):
            raise ValueError(f"phase_ref={phase_ref!r} is not a non-empty network")
        t0, t1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])
        Tref = _network_temp_frame(networks[phase_ref], freq, temp_type=temp_type,
                                   temp_var=temp_var).loc[t0:t1]
        ref_temp = getattr(Tref, reduce)(axis=1)

    code_phase = _build_code_phase(
        networks, classify=classify, window=window, freq=freq, code_rule=code_rule,
        phase_ref=phase_ref, snow_max_c=snow_max_c, rain_min_c=rain_min_c,
        reduce=reduce, temp_var=temp_var, temp_type=temp_type, verbose=verbose)

    frames = {
        name: _phase_temp_frame(
            networks[name], window=window, freq=freq, points=points,
            reduce=reduce, snow_max_c=snow_max_c, rain_min_c=rain_min_c,
            min_precip_mm=min_precip_mm, rain_var=rain_var, temp_var=temp_var,
            temp_type=temp_type, ref_temp=ref_temp, code_phase=code_phase,
            temp_guard=temp_guard, snow_temp_ceiling=snow_temp_ceiling,
            mixed_temp_ceiling=mixed_temp_ceiling,
        )
        for name in keys
    }
    if common_bins:
        time_sets = [set(f['time']) for f in frames.values() if not f.empty]
        shared = set.intersection(*time_sets) if time_sets else set()
        frames = {n: f[f['time'].isin(shared)] for n, f in frames.items()}

    fig, axes = plt.subplots(1, len(keys), figsize=figsize, sharey=True)
    if len(keys) == 1:
        axes = [axes]
    # High-contrast palette. Rain is a light semi-transparent wash (it
    # dominates); snow/mixed are opaque with a crisp dark edge so each point is
    # outlined and stays distinct on top of the blue rain cloud. Snow is pushed
    # to a brighter electric cyan to separate it from the rain blue. Pass
    # `colors`/`edge_colors` dicts to override any of these per phase.
    import matplotlib.colors as _mc

    def _darken(c, f=0.45):
        r, g, b = _mc.to_rgb(c)
        return (r * f, g * f, b * f)

    ph_colors = {'rain': '#2166ac', 'mixed': '#e377c2', 'snow': '#00e5ff'}
    if colors:
        ph_colors.update(colors)
    # Edges auto-darken from the face colour so any custom palette stays crisp;
    # rain keeps no edge. Override with `edge_colors` if desired.
    ph_edge = {'rain': 'none',
               'mixed': _darken(ph_colors['mixed']),
               'snow':  _darken(ph_colors['snow'])}
    if edge_colors:
        ph_edge.update(edge_colors)
    ph_alpha  = {'rain': min(alpha, 0.32), 'mixed': 0.95, 'snow': 1.0}
    ph_lw     = {'rain': 0.0,       'mixed': 0.5,        'snow': 0.7}
    xlabel = 'Wet-bulb temperature (°C)' if temp_type == 'bulb' else 'Temperature (°C)'

    for idx, (ax, name) in enumerate(zip(axes, keys)):
        wet = frames[name][frames[name]['phase'] != 'dry']
        handles = {}
        # Draw rain first (bottom), then mixed, then snow on top so the rare
        # phases are not buried under the dominant rain cloud.
        for ph in ('rain', 'mixed', 'snow'):
            sub = wet[wet['phase'] == ph]
            if sub.empty:
                continue
            handles[ph] = ax.scatter(
                sub['temp_c'], sub['precip_mm'], s=point_size,
                alpha=ph_alpha[ph], color=ph_colors[ph], label=ph,
                edgecolors=ph_edge[ph], linewidths=ph_lw[ph])
        ax.axvline(snow_max_c, color='k', lw=0.7, ls='--', alpha=0.5)
        if classify in ('temp', 'wu_airport'):
            ax.axvline(rain_min_c, color='k', lw=0.7, ls='--', alpha=0.5)
        ax.set_xlabel(xlabel, fontsize=label_fs)
        ax.set_title(name, fontsize=(title_fs or 13), fontweight='bold')
        ax.grid(True, which='both', alpha=0.3)
        if tick_fs is not None:
            ax.tick_params(labelsize=tick_fs)
        # Legend only in the first panel, ordered rarest → most common.
        if idx == 0:
            order = [p for p in ('snow', 'mixed', 'rain') if p in handles]
            if order:
                leg = ax.legend([handles[p] for p in order], order,
                                title='Precip Type', frameon=True,
                                edgecolor='gray', framealpha=0.9,
                                fontsize=legend_fs)
                for lh in getattr(leg, 'legend_handles',
                                  getattr(leg, 'legendHandles', [])):
                    lh.set_alpha(1.0)

    axes[0].set_ylabel('Hourly Precipitation (mm)', fontsize=label_fs)
    axes[0].set_yscale(yscale)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'axes': axes}


def plot_precip_agreement_scatter(
    networks,
    *,
    window,
    x_net: str = 'ASOS',
    y_net: str = 'WU PWS',
    freq: str = '1h',
    reduce: str = 'mean',
    classify: str = 'wu_airport',
    code_rule: str = 'mode',
    phase_ref: str = 'ASOS',
    snow_max_c: float = 0.0,
    rain_min_c: float = 2.0,
    temp_guard: bool = True,
    snow_temp_ceiling: float = 6.0,
    mixed_temp_ceiling: float = 8.0,
    rainy_threshold: float = 0.1,
    scale: str = 'linear',
    colors: Optional[dict] = None,
    edge_colors: Optional[dict] = None,
    figsize: Tuple[float, float] = (7, 7),
    point_size: float = 14,
    alpha: float = 0.5,
    title_fs: Optional[float] = None,
    label_fs: float = 12,
    tick_fs: float = 12,
    legend_fs: float = 11,
    rain_var: str = 'rainfall_amount',
    temp_var: str = 'temperature',
    temp_type: str = 'air',
    save_path=None,
    verbose: bool = True,
):
    """Hourly precip agreement: one network vs another, points coloured by phase.

    For each shared bin the precip of `x_net` (x) and `y_net` (y) are plotted,
    coloured snow/mixed/rain by the same classification machinery as
    `plot_phase_temp_scatter` (`classify` = 'temp' | 'asos_codes' |
    'wu_airport', with the warm-temp `temp_guard`). Per phase a through-origin
    slope and R² are fitted; a y=x reference line is drawn. The story for a
    snowfall paper: rain hugs y=x while snow sits below it — `y_net`
    (e.g. WU PWS tipping buckets) under-catches snow relative to `x_net`
    (e.g. official ASOS).

    Returns {'fig', 'ax', 'stats'} where `stats` is a per-phase DataFrame:
    n, {x_net}_mm, {y_net}_mm, catch_ratio (y/x), r (Pearson), slope.
    """
    import matplotlib.pyplot as plt
    import matplotlib.colors as _mc
    from analysis.pws_qc import network_resample

    plt.rcParams.update({
        'font.size': 12, 'axes.labelsize': 13, 'xtick.labelsize': 11,
        'ytick.labelsize': 11, 'legend.fontsize': 11, 'legend.title_fontsize': 11,
    })
    for n in (x_net, y_net):
        if not networks.get(n):
            raise ValueError(f"network {n!r} is empty or missing")

    t0, t1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    Px = getattr(network_resample(networks[x_net], rain_var, freq, 'sum').loc[t0:t1],
                 reduce)(axis=1)
    Py = getattr(network_resample(networks[y_net], rain_var, freq, 'sum').loc[t0:t1],
                 reduce)(axis=1)
    Tref = getattr(_network_temp_frame(networks[phase_ref], freq, temp_type=temp_type,
                                       temp_var=temp_var).loc[t0:t1],
                   reduce)(axis=1)

    code_phase = _build_code_phase(
        networks, classify=classify, window=window, freq=freq, code_rule=code_rule,
        phase_ref=phase_ref, snow_max_c=snow_max_c, rain_min_c=rain_min_c,
        reduce=reduce, temp_var=temp_var, temp_type=temp_type, verbose=verbose)

    df = pd.DataFrame({'x': Px, 'y': Py, 'temp': Tref}).dropna(subset=['x', 'y'])
    if code_phase is not None:
        df['phase'] = df.index.map(code_phase)
        # fill gaps with a temp band so every wet bin gets a phase
        band = np.select([df['temp'] <= snow_max_c, df['temp'] < rain_min_c],
                         ['snow', 'mixed'], default='rain')
        df['phase'] = df['phase'].fillna(pd.Series(band, index=df.index))
    else:
        df['phase'] = np.select([df['temp'] <= snow_max_c, df['temp'] < rain_min_c],
                                ['snow', 'mixed'], default='rain')

    if temp_guard:
        ph = df['phase'].to_numpy(); tp = df['temp'].to_numpy()
        ph = np.where((ph == 'snow')  & (tp > snow_temp_ceiling),  'rain', ph)
        ph = np.where((ph == 'mixed') & (tp > mixed_temp_ceiling), 'rain', ph)
        df['phase'] = ph

    # keep bins wet in either network
    df = df[(df['x'] > rainy_threshold) | (df['y'] > rainy_threshold)]

    # palette (shared defaults with plot_phase_temp_scatter)
    def _darken(c, f=0.45):
        r, g, b = _mc.to_rgb(c); return (r * f, g * f, b * f)
    ph_colors = {'rain': '#2166ac', 'mixed': '#e377c2', 'snow': '#00e5ff'}
    if colors:
        ph_colors.update(colors)
    ph_edge = {'rain': 'none', 'mixed': _darken(ph_colors['mixed']),
               'snow': _darken(ph_colors['snow'])}
    if edge_colors:
        ph_edge.update(edge_colors)
    ph_alpha = {'rain': min(alpha, 0.32), 'mixed': 0.95, 'snow': 1.0}
    ph_lw    = {'rain': 0.0, 'mixed': 0.5, 'snow': 0.7}

    # per-phase fit + stats
    rows = {}
    fit = {}
    for ph in ('snow', 'mixed', 'rain'):
        sub = df[df['phase'] == ph]
        n = len(sub)
        if n == 0:
            rows[ph] = dict(n=0, x_mm=0.0, y_mm=0.0, catch_ratio=np.nan,
                            r=np.nan, slope=np.nan)
            continue
        x, y = sub['x'].to_numpy(), sub['y'].to_numpy()
        slope = (x * y).sum() / (x * x).sum() if (x * x).sum() > 0 else np.nan
        r = np.corrcoef(x, y)[0, 1] if n > 1 else np.nan
        rows[ph] = dict(n=n, x_mm=float(x.sum()), y_mm=float(y.sum()),
                        catch_ratio=(float(y.sum() / x.sum())
                                     if x.sum() > 0 else np.nan),
                        r=float(r), slope=float(slope))
        fit[ph] = slope

    stats = pd.DataFrame(rows).T[['n', 'x_mm', 'y_mm', 'catch_ratio', 'r', 'slope']]
    stats = stats.rename(columns={'x_mm': f'{x_net}_mm', 'y_mm': f'{y_net}_mm'})
    stats['n'] = stats['n'].astype(int)
    stats = stats.round({f'{x_net}_mm': 1, f'{y_net}_mm': 1,
                         'catch_ratio': 2, 'r': 2, 'slope': 2})

    fig, ax = plt.subplots(figsize=figsize)
    lim = max(df['x'].max(), df['y'].max()) * 1.05 if len(df) else 1.0
    for ph in ('rain', 'mixed', 'snow'):
        sub = df[df['phase'] == ph]
        if sub.empty:
            continue
        lbl = (f'{ph}  (slope {fit[ph]:.2f}, n={len(sub)})'
               if ph in fit else ph)
        ax.scatter(sub['x'], sub['y'], s=point_size, alpha=ph_alpha[ph],
                   color=ph_colors[ph], edgecolors=ph_edge[ph],
                   linewidths=ph_lw[ph], label=lbl)
        if ph in fit and np.isfinite(fit[ph]):
            ax.plot([0, lim], [0, fit[ph] * lim], color=_darken(ph_colors[ph], 0.7),
                    lw=1.3)
    ax.plot([0, lim], [0, lim], 'k--', lw=0.8, label='y = x')
    if scale == 'log':
        ax.set_xscale('log'); ax.set_yscale('log')
    else:
        ax.set_xlim(0, lim); ax.set_ylim(0, lim)
        ax.set_aspect('equal', adjustable='box')
    ax.set_xlabel(f'{x_net} hourly precip (mm)', fontsize=label_fs)
    ax.set_ylabel(f'{y_net} hourly precip (mm)', fontsize=label_fs)
    ax.set_title(f'{y_net} vs {x_net}', fontsize=(title_fs or 13), fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.tick_params(labelsize=tick_fs)
    leg = ax.legend(title='Precip Type', frameon=True, edgecolor='gray',
                    framealpha=0.9, fontsize=legend_fs)
    for lh in getattr(leg, 'legend_handles', getattr(leg, 'legendHandles', [])):
        lh.set_alpha(1.0)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'ax': ax, 'stats': stats}


def plot_network_correlation(
    networks, *,
    var='rainfall_amount', agg='sum', time_res='1h',
    area='all', period='all', networks_keys='all',
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    save_path=None, verbose=True,
):
    """Pairwise Pearson correlation between network medians (heatmap)."""
    from analysis.pws_qc import pairwise_correlation
    nets = _resampled_nets(networks, var=var, agg=agg, area=area,
                           period=period, time_res=time_res,
                           networks_keys=networks_keys, window=window,
                           rainy_days=rainy_days, snow_days=snow_days,
                           dry_days=dry_days)
    out = pairwise_correlation(nets)
    if save_path is not None:
        import matplotlib.pyplot as plt
        plt.gcf().savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'nets': nets, 'corr': out}


def plot_wu_qc_daily_heatmap(networks, network_key='WU PWS', *,
                              save_path=None, verbose=True):
    """Daily-rainfall heatmap (log10 mm+0.1), top stations by daily max — QC spot-check."""
    from analysis.pws_qc import plot_daily_heatmap
    net = networks.get(network_key, {})
    if not net:
        if verbose:
            print(f'No {network_key} stations.')
        return None
    out = plot_daily_heatmap(net,
                             title=f'{network_key} — daily rainfall (log10 mm+0.1)')
    if save_path is not None:
        import matplotlib.pyplot as plt
        plt.gcf().savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return out


def plot_qc_event_compare(
    networks, raw_pws, *, top_n=3, span_days=2,
    window=None, asos_key='ASOS', pws_key='WU PWS', mesonet_key='Mesonet',
    save_path_prefix=None, verbose=True,
):
    """For the top-N ASOS rain days, plot before/after QC comparison.

    `raw_pws` is the un-QC'd PWS network dict (`{sid: ds}`). Use
    `load_pws_grouped(<raw_path>)` to get it.
    """
    from analysis.pws_qc import network_hourly_rain, plot_event_qc_compare
    import matplotlib.pyplot as plt
    asos_h = network_hourly_rain(networks[asos_key])
    pws_h  = network_hourly_rain(networks[pws_key])
    meso_h = network_hourly_rain(networks[mesonet_key])
    pws_raw_h = network_hourly_rain(raw_pws)
    if window is not None:
        asos_h = asos_h.loc[window[0]:window[1]]
        pws_h  = pws_h.loc[window[0]:window[1]]
        meso_h = meso_h.loc[window[0]:window[1]]
        pws_raw_h = pws_raw_h.loc[window[0]:window[1]]
    daily_asos = asos_h.median(axis=1).resample('1D').sum(min_count=1)
    top_events = daily_asos.nlargest(top_n).sort_index()
    if verbose:
        print(f'Top {top_n} ASOS rain days:')
        print(top_events.round(1).to_string())
    figs = []
    for day in top_events.index:
        fig = plot_event_qc_compare(asos_h, pws_raw_h, pws_h, meso_h,
                                    day, span_days=span_days)
        if save_path_prefix is not None:
            out = f'{save_path_prefix}_{day.strftime("%Y-%m-%d")}.pdf'
            plt.gcf().savefig(out)
            if verbose:
                print(f'saved → {out}')
        figs.append(fig)
    return {'top_events': top_events, 'figs': figs}


# ============================================================================
# Snow-focused wrappers (used by weather_snow.ipynb)
# ============================================================================

def _mesonet_snow_daily(networks, *, network_key='Mesonet', window=None):
    """Daily-resampled snow_depth from Mesonet (median across stations)."""
    from analysis.pws_qc import network_resample
    net = networks.get(network_key, {})
    if not net:
        return pd.DataFrame()
    df = network_resample(net, 'snow_depth', '1D', 'max')
    if window is not None:
        df = df.loc[window[0]:window[1]]
    return df


def find_snow_events(
    networks, *,
    network_key='Mesonet',
    threshold_cm=1.0,
    gap_days=1,
    window=None,
) -> pd.DataFrame:
    """Find snow-on-ground events from Mesonet snow_depth.

    An "event" is a stretch of days where the **median** snow_depth across
    Mesonet stations is at least `threshold_cm`. Stretches separated by
    ≤ `gap_days` days of bare ground are merged into one event.

    Returns a DataFrame with one row per event:
        start, end, duration_days, peak_depth_cm, peak_date,
        delta_in_cm, delta_out_cm
    """
    df = _mesonet_snow_daily(networks, network_key=network_key, window=window)
    if df.empty:
        return pd.DataFrame()
    daily = df.median(axis=1)
    above = (daily >= threshold_cm).fillna(False).astype(int)
    if above.sum() == 0:
        return pd.DataFrame()
    # Group runs of above==1, allowing gap_days of zero between them
    out = []
    i = 0
    arr = above.values
    idx = above.index
    n = len(arr)
    while i < n:
        if arr[i] != 1:
            i += 1
            continue
        start_i = i
        last_above = i
        j = i + 1
        while j < n:
            if arr[j] == 1:
                last_above = j
                j += 1
            elif j - last_above <= gap_days:
                j += 1
            else:
                break
        end_i = last_above
        # Build event row
        ev = daily.iloc[start_i:end_i + 1]
        peak_idx = ev.idxmax()
        # Δ in/out: difference vs the day before/after
        before = daily.iloc[start_i - 1] if start_i > 0 else np.nan
        after = daily.iloc[end_i + 1] if end_i + 1 < n else np.nan
        out.append({
            'start'         : idx[start_i],
            'end'           : idx[end_i],
            'duration_days' : (idx[end_i] - idx[start_i]).days + 1,
            'peak_depth_cm' : float(ev.max()),
            'peak_date'     : peak_idx,
            'delta_in_cm'   : float(ev.iloc[0] - (before if pd.notna(before) else 0)),
            'delta_out_cm'  : float((after if pd.notna(after) else 0) - ev.iloc[-1]),
        })
        i = end_i + 1
    return pd.DataFrame(out).sort_values('peak_depth_cm', ascending=False).reset_index(drop=True)


def plot_snow_overview(
    networks, *,
    network_key='Mesonet',
    threshold_cm=1.0,
    window=None,
    figsize=(13, 4.5),
    save_path=None, verbose=True,
):
    """Daily Mesonet snow_depth (per-station lines + median) with the
    `threshold_cm` line drawn. Best used to see when snow is on the ground."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    df = _mesonet_snow_daily(networks, network_key=network_key, window=window)
    if df.empty:
        if verbose:
            print(f'No {network_key} snow_depth data in window.')
        return {'fig': None, 'ax': None, 'df': df}
    fig, ax = plt.subplots(figsize=figsize)
    for sid in df.columns:
        ax.plot(df.index, df[sid], lw=1.0, alpha=0.7, label=sid)
    med = df.median(axis=1)
    ax.plot(med.index, med, color='black', lw=2.0, alpha=0.85, label='median')
    ax.axhline(threshold_cm, color='red', lw=0.8, ls='--',
               label=f'threshold {threshold_cm} cm')
    above = med >= threshold_cm
    ax.fill_between(med.index, 0, med.where(above, 0).values,
                    color='#1f77b4', alpha=0.15, label='snow on ground')
    ax.set_ylabel(f'{network_key} snow_depth (cm)')
    ax.set_title(f'{network_key} snow_depth — daily max per station')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    for lab in ax.get_xticklabels():
        lab.set_rotation(30)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'ax': ax, 'df': df}


_PRECIP_CAT_COLORS = {
    'dry'     : '#dddddd',
    'rain'    : '#1f77b4',
    'snow'    : '#17becf',
    'ice'     : '#9467bd',
    'mix'     : '#ff7f0e',
    'missing' : '#aaaaaa',
}


def plot_precip_category_strip(
    networks, *,
    network_key='ASOS',
    period='all',
    var='precip_category',
    time_res='10min',
    window=None,
    figsize=(13, 3.5),
    save_path=None, verbose=True,
):
    """Categorical strip plot of ASOS `precip_category` — one row per station.

    Resamples each station's category to `time_res` by mode, then dots are
    colored by category. The categorical signal is the only snow-related
    field on ASOS (since it has no snow_depth)."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    net = networks.get(network_key, {})
    if not net:
        if verbose:
            print(f'No {network_key} stations.')
        return {'fig': None, 'ax': None}
    # Window
    if isinstance(period, (tuple, list)) and len(period) == 2:
        s, e = pd.Timestamp(period[0]), pd.Timestamp(period[1])
    elif window is not None:
        s, e = window
    else:
        s, e = None, None
    sids = sorted(net.keys())
    fig, ax = plt.subplots(figsize=figsize)
    seen_cats = set()
    for row, sid in enumerate(sids):
        ds = net[sid]
        if var not in ds.data_vars:
            continue
        ser = ds[var].squeeze(drop=True).to_series()
        ser.index = pd.to_datetime(ser.index)
        if s is not None and e is not None:
            ser = ser.loc[s:e]
        ser = ser.dropna()
        if ser.empty:
            continue
        # Resample by mode
        sub = (ser.resample(time_res)
                  .agg(lambda x: x.mode().iloc[0] if len(x.mode()) else None)
                  .dropna())
        for cat, color in _PRECIP_CAT_COLORS.items():
            m = sub == cat
            if m.any():
                ax.scatter(sub.index[m], [row] * int(m.sum()), s=18, marker='s',
                           color=color, label=cat if cat not in seen_cats else None)
                seen_cats.add(cat)
    ax.set_yticks(range(len(sids)))
    ax.set_yticklabels(sids)
    ax.set_title(f'{network_key} {var}  •  PERIOD={period!r}  TIME_RES={time_res}')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d %Hh'))
    for lab in ax.get_xticklabels():
        lab.set_rotation(30)
    if seen_cats:
        ax.legend(loc='upper right', fontsize=8, ncol=len(seen_cats))
    ax.grid(True, alpha=0.3, axis='x')
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'ax': ax}


def plot_snow_event(
    networks, period, *,
    area='all', time_res='1h', networks_keys='all',
    snow_network='Mesonet', asos_network='ASOS',
    window=None, rainy_days=None, snow_days=None, dry_days=None,
    save_path=None, verbose=True,
):
    """4-panel snow event zoom:
       (1) Mesonet snow_depth (per-station + median)
       (2) ASOS precip_category strip across stations
       (3) network-median temperature
       (4) hourly rainfall_amount across networks (meltwater / mixed precip)
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from analysis.pws_qc import DEFAULT_COLORS
    # Resample for each panel
    snow_n = _resampled_nets(networks, var='snow_depth', agg='mean',
                             area=area, period=period, time_res=time_res,
                             networks_keys=[snow_network], window=window,
                             rainy_days=rainy_days, snow_days=snow_days,
                             dry_days=dry_days)
    temp_n = _resampled_nets(networks, var='temperature', agg='mean',
                             area=area, period=period, time_res=time_res,
                             networks_keys=networks_keys, window=window,
                             rainy_days=rainy_days, snow_days=snow_days,
                             dry_days=dry_days)
    rain_n = _resampled_nets(networks, var='rainfall_amount', agg='sum',
                             area=area, period=period, time_res=time_res,
                             networks_keys=networks_keys, window=window,
                             rainy_days=rainy_days, snow_days=snow_days,
                             dry_days=dry_days)
    snow_df = snow_n.get(snow_network, pd.DataFrame())
    fig, axes = plt.subplots(4, 1, figsize=(13, 9), sharex=True)

    # 1) snow_depth
    if not snow_df.empty:
        for sid in snow_df.columns:
            axes[0].plot(snow_df.index, snow_df[sid], lw=1.0, alpha=0.7, label=sid)
        axes[0].plot(snow_df.index, snow_df.median(axis=1), color='black',
                     lw=1.8, label='median')
    axes[0].set_ylabel(f'{snow_network}\nsnow_depth (cm)')
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(fontsize=8, ncol=2)

    # 2) ASOS precip_category strip
    asos = networks.get(asos_network, {})
    if isinstance(period, (tuple, list)) and len(period) == 2:
        s, e = pd.Timestamp(period[0]), pd.Timestamp(period[1])
    else:
        s, e = (window if window is not None else (None, None))
    sids = sorted(asos.keys())
    seen_cats = set()
    for row, sid in enumerate(sids):
        ds = asos[sid]
        if 'precip_category' not in ds.data_vars:
            continue
        ser = ds['precip_category'].squeeze(drop=True).to_series()
        ser.index = pd.to_datetime(ser.index)
        if s is not None and e is not None:
            ser = ser.loc[s:e]
        ser = ser.dropna()
        if ser.empty:
            continue
        sub = (ser.resample('10min')
                  .agg(lambda x: x.mode().iloc[0] if len(x.mode()) else None)
                  .dropna())
        for cat, color in _PRECIP_CAT_COLORS.items():
            m = sub == cat
            if m.any():
                axes[1].scatter(sub.index[m], [row] * int(m.sum()), s=14, marker='s',
                                color=color, label=cat if cat not in seen_cats else None)
                seen_cats.add(cat)
    axes[1].set_yticks(range(len(sids)))
    axes[1].set_yticklabels(sids)
    axes[1].set_ylabel(f'{asos_network}\nprecip_category')
    axes[1].grid(True, alpha=0.3, axis='x')
    if seen_cats:
        axes[1].legend(loc='upper right', fontsize=7, ncol=len(seen_cats))

    # 3) temperature
    for name, df in temp_n.items():
        if df.empty:
            continue
        c = DEFAULT_COLORS.get(name.split()[0], '#666')
        axes[2].plot(df.index, df.median(axis=1), color=c, lw=1.3,
                     label=f'{name} med')
    axes[2].axhline(0, color='black', lw=0.5, alpha=0.6)
    axes[2].set_ylabel('°C')
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(fontsize=8)

    # 4) rainfall_amount
    for name, df in rain_n.items():
        if df.empty:
            continue
        c = DEFAULT_COLORS.get(name.split()[0], '#666')
        axes[3].plot(df.index, df.median(axis=1), color=c, lw=1.3,
                     label=f'{name} med')
    axes[3].set_ylabel(f'rain {time_res} (mm)')
    axes[3].grid(True, alpha=0.3)
    axes[3].legend(fontsize=8)

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %Hh'))
    for lab in axes[-1].get_xticklabels():
        lab.set_rotation(30)
    fig.suptitle(f'Snow event zoom — PERIOD={period!r}', y=1.005)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'axes': axes,
            'snow': snow_df, 'temp': temp_n, 'rain': rain_n}


def snow_events_table(
    networks, *,
    network_key='Mesonet', asos_network='ASOS',
    threshold_cm=1.0, gap_days=1,
    window=None, verbose=True,
) -> pd.DataFrame:
    """Per-event summary: duration, peak depth, ASOS snow-categorized hours,
    median temperature during the event, total rainfall during the event."""
    events = find_snow_events(networks, network_key=network_key,
                              threshold_cm=threshold_cm, gap_days=gap_days,
                              window=window)
    if events.empty:
        if verbose:
            print(f'No snow events ≥ {threshold_cm} cm found.')
        return events
    from analysis.pws_qc import network_resample
    # Pre-compute hourly ASOS precip_category mode + temperature + rainfall
    asos = networks.get(asos_network, {})
    cat_hourly = {}
    for sid, ds in asos.items():
        if 'precip_category' in ds.data_vars:
            ser = ds['precip_category'].squeeze(drop=True).to_series()
            ser.index = pd.to_datetime(ser.index)
            cat_hourly[sid] = (ser.resample('1h')
                                  .agg(lambda x: x.mode().iloc[0] if len(x.mode()) else None))
    temp_h = (network_resample(asos, 'temperature', '1h', 'mean')
              if asos else pd.DataFrame())
    rain_h = (network_resample(asos, 'rainfall_amount', '1h', 'sum')
              if asos else pd.DataFrame())
    rows = []
    for _, ev in events.iterrows():
        s, e = ev['start'], ev['end'] + pd.Timedelta(days=1)  # inclusive end day
        snow_hours = 0
        for ser in cat_hourly.values():
            snow_hours += int((ser.loc[s:e] == 'snow').sum())
        median_T = (temp_h.loc[s:e].median(axis=1).mean()
                    if not temp_h.empty else float('nan'))
        total_rain = (rain_h.loc[s:e].median(axis=1).sum()
                      if not rain_h.empty else float('nan'))
        rows.append({
            **ev.to_dict(),
            'asos_snow_hours' : snow_hours,
            'median_temp_C'   : round(float(median_T), 1) if pd.notna(median_T) else None,
            'asos_rain_mm'    : round(float(total_rain), 1) if pd.notna(total_rain) else None,
        })
    out = pd.DataFrame(rows)
    if verbose:
        print(f'Found {len(out)} snow events (threshold={threshold_cm} cm, '
              f'gap={gap_days} days):')
        print(out.to_string(index=False))
    return out


# ============================================================================
# PWS-in-frozen-precip diagnostics
# ============================================================================
#
# Two helpers backing the "PWS reads zero in snow/ice" observation.
#   - rainfall_by_precip_category(): per-category mean/median/zero-fraction
#                                     for every network, joined into one table
#   - plot_pws_snow_event_compare(): per-event figure (rain panels +
#                                     ASOS category strip + Mesonet snow_depth)

def rainfall_by_precip_category(
    networks, *,
    asos_key='ASOS', pws_key='WU PWS', mesonet_key='Mesonet',
    window=None, verbose=True,
) -> pd.DataFrame:
    """Stratify hourly rainfall by ASOS `precip_category` and report
    mean / median / pct-zero / total per network. Hours are tagged by the
    ASOS network-modal category at that hour, then matched against every
    network's mean hourly rainfall.

    Returns
    -------
    pd.DataFrame
        Rows: precip_category (dry, rain, snow, ice, mix, missing).
        Columns: per-network mean_mm, median_mm, pct_zero, total_mm, n_hours.
    """
    from analysis.pws_qc import network_resample  # network_hourly_rain wraps this

    asos = networks.get(asos_key, {})
    pws  = networks.get(pws_key,  {})
    meso = networks.get(mesonet_key, {})

    # 1) Per-hour ASOS-network category = mode across stations
    cat_per_station = {}
    for sid, ds in asos.items():
        if 'precip_category' not in ds.data_vars:
            continue
        ser = ds['precip_category'].squeeze(drop=True).to_series()
        ser.index = pd.to_datetime(ser.index)
        cat_per_station[sid] = (ser.resample('1h')
                                   .agg(lambda x: x.mode().iloc[0] if len(x.mode()) else None))
    if not cat_per_station:
        raise RuntimeError(f'No precip_category found in network {asos_key!r}.')
    cat_df = pd.DataFrame(cat_per_station)
    if window is not None:
        cat_df = cat_df.loc[window[0]:window[1]]
    cat_modal = cat_df.mode(axis=1).iloc[:, 0]  # 1st modal value per hour

    # 2) Per-network mean hourly rainfall
    def mean_h(d):
        if not d: return pd.Series(dtype=float)
        df = network_resample(d, 'rainfall_amount', '1h', 'sum')
        s = df.mean(axis=1)
        if window is not None:
            s = s.loc[window[0]:window[1]]
        return s

    asos_h = mean_h(asos).rename('ASOS')
    pws_h  = mean_h(pws).rename('PWS')
    meso_h = mean_h(meso).rename('Mesonet')

    rain = pd.concat([asos_h, pws_h, meso_h], axis=1).join(cat_modal.rename('cat'), how='inner')

    # 3) Aggregate per category
    rows = []
    for cat, grp in rain.groupby('cat'):
        row = {'category': cat, 'n_hours': len(grp)}
        for net in ('ASOS', 'PWS', 'Mesonet'):
            s = grp[net].dropna()
            if s.empty:
                row[f'{net}_mean_mm']   = float('nan')
                row[f'{net}_median_mm'] = float('nan')
                row[f'{net}_pct_zero']  = float('nan')
                row[f'{net}_total_mm']  = float('nan')
            else:
                row[f'{net}_mean_mm']   = round(float(s.mean()), 3)
                row[f'{net}_median_mm'] = round(float(s.median()), 3)
                row[f'{net}_pct_zero']  = round(float((s <= 0.01).mean() * 100), 1)
                row[f'{net}_total_mm']  = round(float(s.sum()), 1)
        rows.append(row)
    order = ['dry', 'rain', 'snow', 'ice', 'mix', 'missing']
    out = pd.DataFrame(rows).set_index('category')
    out = out.reindex([c for c in order if c in out.index])

    if verbose:
        print(f'Hourly rainfall stratified by ASOS precip_category '
              f'(n={len(rain):,} matched hours):')
        print(out.to_string())
        # The smoking gun: column-by-column zero-fraction comparison
        zero_cols = [c for c in out.columns if c.endswith('_pct_zero')]
        print(f'\nPct of hours with ~zero rainfall (≤0.01 mm) by category:')
        print(out[zero_cols].to_string())
    return out


def plot_pws_snow_event_compare(
    networks, t0, t1, *,
    asos_key='ASOS', pws_key='WU PWS', mesonet_key='Mesonet',
    title=None, figsize=(13, 8),
    save_path=None, verbose=True,
):
    """4-panel zoom on a single snow/ice event:
        (1) hourly rainfall per network — shows PWS reading zero while
            ASOS reports liquid-equivalent of melted frozen precip
        (2) cumulative rainfall over the event window
        (3) ASOS precip_category strip (dry/rain/snow/ice/mix/missing)
        (4) Mesonet snow_depth (cm) per station

    Parameters
    ----------
    t0, t1 : str | pd.Timestamp
        Event window (UTC).
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Patch
    from analysis.pws_qc import network_resample

    # Match the tz-naive convention used by network_resample / load_pws_grouped.
    t0 = pd.Timestamp(t0).tz_localize(None) if pd.Timestamp(t0).tz else pd.Timestamp(t0)
    t1 = pd.Timestamp(t1).tz_localize(None) if pd.Timestamp(t1).tz else pd.Timestamp(t1)

    asos = networks.get(asos_key, {})
    pws  = networks.get(pws_key,  {})
    meso = networks.get(mesonet_key, {})

    def mean_h(d):
        if not d: return pd.Series(dtype=float)
        return network_resample(d, 'rainfall_amount', '1h', 'sum').mean(axis=1).loc[t0:t1]

    a = mean_h(asos).rename('ASOS')
    p = mean_h(pws).rename('PWS')
    m = mean_h(meso).rename('Mesonet')
    rain = pd.concat([a, p, m], axis=1)

    fig, axes = plt.subplots(4, 1, figsize=figsize, sharex=True,
                             gridspec_kw={'height_ratios': [3, 2, 1, 2]})
    # Panel 1: hourly bars
    ax = axes[0]
    for col, color in zip(['ASOS', 'PWS', 'Mesonet'],
                          ['#1f77b4', '#d62728', '#2ca02c']):
        ax.plot(rain.index, rain[col], marker='.', ms=3, lw=1.0,
                color=color, label=col)
    ax.set_ylabel('Rainfall (mm/h)')
    ax.set_title(title or f'Event {t0.date()} → {t1.date()}', fontsize=11)
    ax.legend(loc='upper right', fontsize=8)
    ax.grid(alpha=0.3)

    # Panel 2: cumulative
    ax = axes[1]
    for col, color in zip(['ASOS', 'PWS', 'Mesonet'],
                          ['#1f77b4', '#d62728', '#2ca02c']):
        ax.plot(rain.index, rain[col].fillna(0).cumsum(), lw=1.5,
                color=color, label=col)
    ax.set_ylabel('Cumulative (mm)')
    ax.grid(alpha=0.3)
    ax.legend(loc='upper left', fontsize=8)

    # Panel 3: ASOS precip_category strip (one row per ASOS station)
    ax = axes[2]
    asos_stations = sorted(s for s, ds in asos.items() if 'precip_category' in ds.data_vars)
    seen_categories = set()
    for y, sid in enumerate(asos_stations):
        ser = asos[sid]['precip_category'].squeeze(drop=True).to_series()
        ser.index = pd.to_datetime(ser.index)
        ser = (ser.resample('1h').agg(lambda x: x.mode().iloc[0] if len(x.mode()) else None)
                   .loc[t0:t1])
        for t, c in ser.items():
            if c is None or (isinstance(c, float) and np.isnan(c)):
                continue
            color = _PRECIP_CAT_COLORS.get(c, '#cccccc')
            ax.axvspan(t, t + pd.Timedelta(hours=1), ymin=y/len(asos_stations),
                       ymax=(y+1)/len(asos_stations), color=color, alpha=0.85)
            seen_categories.add(c)
    ax.set_yticks([(i + 0.5)/len(asos_stations) for i in range(len(asos_stations))])
    ax.set_yticklabels(asos_stations, fontsize=7)
    ax.set_ylim(0, 1)
    ax.set_ylabel(f'{asos_key}\nprecip_category', fontsize=8)
    legend_patches = [Patch(facecolor=_PRECIP_CAT_COLORS.get(c, '#cccccc'), label=c)
                      for c in ['dry', 'rain', 'snow', 'ice', 'mix', 'missing']
                      if c in seen_categories]
    if legend_patches:
        ax.legend(handles=legend_patches, loc='upper right', fontsize=7, ncol=len(legend_patches))

    # Panel 4: Mesonet snow_depth
    ax = axes[3]
    plotted = False
    for sid, ds in meso.items():
        if 'snow_depth' not in ds.data_vars: continue
        s = ds['snow_depth'].squeeze(drop=True).to_series()
        s.index = pd.to_datetime(s.index)
        s = s.loc[t0:t1]
        if s.dropna().empty: continue
        ax.plot(s.index, s.values, lw=1.2, label=sid)
        plotted = True
    if plotted:
        ax.legend(loc='upper right', fontsize=7, ncol=4)
    ax.set_ylabel('Mesonet\nsnow_depth (cm)', fontsize=8)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))

    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path)
        if verbose:
            print(f'saved → {save_path}')

    # Verbose printout: totals + summary stats
    if verbose:
        totals = rain.sum().round(1)
        zerof  = (rain <= 0.01).mean().round(2) * 100
        print(f'Event totals (mm): {totals.to_dict()}')
        print(f'Pct of hours ≤ 0.01 mm: {zerof.to_dict()}')

    return {'fig': fig, 'axes': axes, 'rain': rain}


def pws_undercatch_summary(
    networks, *,
    asos_key='ASOS', pws_key='WU PWS', mesonet_key='Mesonet',
    detect_threshold_mm=0.5,
    window=None, verbose=True,
) -> pd.DataFrame:
    """Single-row-per-category undercatch summary for paper use.

    Each row reports, conditional on ASOS-modal `precip_category`:
        - n_hours
        - total rain captured by each network
        - PWS undercatch ratio = PWS_total / ASOS_total
        - PWS detection rate = % of hours where PWS network-mean > threshold
        - same detection rate for ASOS / Mesonet (sanity sentinels)
    """
    from analysis.pws_qc import network_resample

    asos = networks.get(asos_key, {})
    pws  = networks.get(pws_key,  {})
    meso = networks.get(mesonet_key, {})

    cat_per_station = {}
    for sid, ds in asos.items():
        if 'precip_category' not in ds.data_vars: continue
        ser = ds['precip_category'].squeeze(drop=True).to_series()
        ser.index = pd.to_datetime(ser.index)
        cat_per_station[sid] = (ser.resample('1h')
                                   .agg(lambda x: x.mode().iloc[0] if len(x.mode()) else None))
    cat_df = pd.DataFrame(cat_per_station)
    if window is not None:
        cat_df = cat_df.loc[window[0]:window[1]]
    cat_modal = cat_df.mode(axis=1).iloc[:, 0]

    def mean_h(d):
        if not d: return pd.Series(dtype=float)
        s = network_resample(d, 'rainfall_amount', '1h', 'sum').mean(axis=1)
        return s.loc[window[0]:window[1]] if window is not None else s

    rain = pd.concat([mean_h(asos).rename('ASOS'),
                      mean_h(pws).rename('PWS'),
                      mean_h(meso).rename('Mesonet')],
                     axis=1).join(cat_modal.rename('cat'), how='inner')

    rows = []
    for cat, grp in rain.groupby('cat'):
        a_tot = float(grp['ASOS'].sum(min_count=1) or 0)
        p_tot = float(grp['PWS'].sum(min_count=1) or 0)
        m_tot = float(grp['Mesonet'].sum(min_count=1) or 0)
        rows.append({
            'category'              : cat,
            'n_hours'               : len(grp),
            'ASOS_total_mm'         : round(a_tot, 1),
            'PWS_total_mm'          : round(p_tot, 1),
            'Mesonet_total_mm'      : round(m_tot, 1),
            'PWS_vs_ASOS_ratio'     : round(p_tot / a_tot, 3) if a_tot > 0.01 else float('nan'),
            'Mesonet_vs_ASOS_ratio' : round(m_tot / a_tot, 3) if a_tot > 0.01 else float('nan'),
            'ASOS_detect_rate_pct'    : round((grp['ASOS']    > detect_threshold_mm).mean() * 100, 1),
            'PWS_detect_rate_pct'     : round((grp['PWS']     > detect_threshold_mm).mean() * 100, 1),
            'Mesonet_detect_rate_pct' : round((grp['Mesonet'] > detect_threshold_mm).mean() * 100, 1),
        })
    order = ['dry', 'rain', 'snow', 'ice', 'mix', 'missing']
    out = pd.DataFrame(rows).set_index('category')
    out = out.reindex([c for c in order if c in out.index])

    if verbose:
        print(f'PWS undercatch summary (threshold = {detect_threshold_mm} mm/h, n={len(rain):,} matched hours):')
        print(out.to_string())
        snow = out.loc['snow'] if 'snow' in out.index else None
        if snow is not None:
            print(f'\nHEADLINE — during snow hours:')
            print(f'  PWS captures {snow["PWS_vs_ASOS_ratio"]*100:.1f}% of ASOS rainfall '
                  f'({snow["PWS_total_mm"]} vs {snow["ASOS_total_mm"]} mm)')
            print(f'  PWS detects rain >{detect_threshold_mm}mm in only '
                  f'{snow["PWS_detect_rate_pct"]:.1f}% of snow hours, vs '
                  f'{snow["ASOS_detect_rate_pct"]:.1f}% for ASOS and '
                  f'{snow["Mesonet_detect_rate_pct"]:.1f}% for Mesonet')
    return out


def plot_hourly_distribution_by_category(
    networks, *,
    asos_key='ASOS', pws_key='WU PWS', mesonet_key='Mesonet',
    categories=('rain', 'snow', 'mix'),
    window=None,
    figsize=(11, 4.5),
    save_path=None, verbose=True,
):
    """Box-and-whisker of hourly rainfall conditional on ASOS `precip_category`,
    one panel per category, three boxes per panel (ASOS / PWS / Mesonet).

    Wet-only (≥0.01 mm) hours, log-y, so the visual gap during `snow` is the
    central paper-figure asset.
    """
    import matplotlib.pyplot as plt
    from analysis.pws_qc import network_resample

    asos = networks.get(asos_key, {})
    pws  = networks.get(pws_key,  {})
    meso = networks.get(mesonet_key, {})

    cat_per_station = {}
    for sid, ds in asos.items():
        if 'precip_category' not in ds.data_vars: continue
        ser = ds['precip_category'].squeeze(drop=True).to_series()
        ser.index = pd.to_datetime(ser.index)
        cat_per_station[sid] = (ser.resample('1h')
                                   .agg(lambda x: x.mode().iloc[0] if len(x.mode()) else None))
    cat_df = pd.DataFrame(cat_per_station)
    if window is not None:
        cat_df = cat_df.loc[window[0]:window[1]]
    cat_modal = cat_df.mode(axis=1).iloc[:, 0]

    def mean_h(d):
        if not d: return pd.Series(dtype=float)
        s = network_resample(d, 'rainfall_amount', '1h', 'sum').mean(axis=1)
        return s.loc[window[0]:window[1]] if window is not None else s

    rain = pd.concat([mean_h(asos).rename('ASOS'),
                      mean_h(pws).rename('PWS'),
                      mean_h(meso).rename('Mesonet')],
                     axis=1).join(cat_modal.rename('cat'), how='inner')

    fig, axes = plt.subplots(1, len(categories), figsize=figsize, sharey=True)
    if len(categories) == 1:
        axes = [axes]
    colors = ['#1f77b4', '#d62728', '#2ca02c']

    for ax, cat in zip(axes, categories):
        grp = rain[rain.cat == cat]
        data, n = [], []
        for net, c in zip(['ASOS', 'PWS', 'Mesonet'], colors):
            s = grp[net].dropna()
            s = s[s >= 0.01]
            data.append(s.values)
            n.append(len(s))
        bp = ax.boxplot(data, labels=['ASOS','PWS','Mesonet'], showfliers=False,
                        patch_artist=True, widths=0.6)
        for patch, c in zip(bp['boxes'], colors):
            patch.set_facecolor(c); patch.set_alpha(0.6)
        ax.set_yscale('log')
        ax.set_title(f'{cat} (n={len(grp):,} hours)', fontsize=10)
        ax.set_ylim(0.01, 50)
        ax.grid(alpha=0.3, axis='y')
        for i, count in enumerate(n):
            ax.annotate(f'wet={count}', xy=(i+1, 0.012), ha='center',
                        fontsize=7, color='#444444')
    axes[0].set_ylabel('Hourly rainfall (mm) — wet hours, log scale')
    fig.suptitle('PWS hourly rainfall during ASOS-classified precip categories',
                 fontsize=11)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path, dpi=150)
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'axes': axes, 'rain': rain}


def pws_station_snow_response(
    networks, *,
    asos_key='ASOS', pws_key='WU PWS',
    window=None, min_n_snow=20,
    verbose=True,
) -> pd.DataFrame:
    """For each PWS station, mean rainfall during ASOS snow hours vs rain hours.

    Useful for paper: shows that the under-catch is uniform across stations, not
    one or two bad sensors driving the network mean.
    """
    from analysis.pws_qc import network_resample

    asos = networks.get(asos_key, {})
    pws  = networks.get(pws_key,  {})

    # Hourly ASOS-modal category
    cat_per_station = {}
    for sid, ds in asos.items():
        if 'precip_category' not in ds.data_vars: continue
        ser = ds['precip_category'].squeeze(drop=True).to_series()
        ser.index = pd.to_datetime(ser.index)
        cat_per_station[sid] = (ser.resample('1h')
                                   .agg(lambda x: x.mode().iloc[0] if len(x.mode()) else None))
    cat_df = pd.DataFrame(cat_per_station)
    if window is not None:
        cat_df = cat_df.loc[window[0]:window[1]]
    cat = cat_df.mode(axis=1).iloc[:, 0]

    rows = []
    for sid, ds in pws.items():
        if 'rainfall_amount' not in ds.data_vars: continue
        s = ds['rainfall_amount'].squeeze(drop=True).to_series()
        s.index = pd.to_datetime(s.index)
        s = s.resample('1h').sum(min_count=1)
        if window is not None:
            s = s.loc[window[0]:window[1]]
        df = pd.concat([s.rename('mm'), cat.rename('cat')], axis=1, join='inner')
        if len(df) == 0: continue
        snow = df[df.cat == 'snow']['mm'].dropna()
        rain = df[df.cat == 'rain']['mm'].dropna()
        if len(snow) < min_n_snow:
            continue
        rows.append({
            'station'           : sid,
            'n_snow_hours'      : len(snow),
            'n_rain_hours'      : len(rain),
            'mean_in_snow_mm'   : round(snow.mean(), 3),
            'mean_in_rain_mm'   : round(rain.mean(), 3) if len(rain) else float('nan'),
            'pct_zero_in_snow'  : round((snow <= 0.01).mean() * 100, 1),
            'pct_zero_in_rain'  : round((rain <= 0.01).mean() * 100, 1) if len(rain) else float('nan'),
            'snow_over_rain_ratio': round(snow.mean() / rain.mean(), 3) if (len(rain) and rain.mean() > 0.01) else float('nan'),
        })
    out = pd.DataFrame(rows).sort_values('mean_in_snow_mm')

    if verbose:
        if out.empty:
            print(f'No PWS stations with ≥ {min_n_snow} snow hours in window.')
        else:
            print(f'Per-PWS-station response in ASOS snow vs rain hours '
                  f'(n_stations={len(out)}, min_n_snow={min_n_snow}):')
            print(out.head(15).to_string(index=False))
            print(f'\nAcross all {len(out)} stations:')
            print(f'  median mean_in_snow_mm   : {out.mean_in_snow_mm.median():.3f}')
            print(f'  median mean_in_rain_mm   : {out.mean_in_rain_mm.median():.3f}')
            print(f'  median pct_zero_in_snow  : {out.pct_zero_in_snow.median():.1f}%')
            print(f'  median pct_zero_in_rain  : {out.pct_zero_in_rain.median():.1f}%')
            print(f'  median snow/rain ratio   : {out.snow_over_rain_ratio.median():.3f}')
            print(f'  stations with mean_in_snow < 0.1 mm/h: {(out.mean_in_snow_mm < 0.1).sum()} of {len(out)}')
    return out


# ============================================================================
# NOAA GHCN-Daily helpers
# ============================================================================
#
# Inputs are per-station CSVs written by `fetch_data.noaa_daily.save_csv`
# (columns: datetime, station_id, lat, lon, elev, precip_amount [mm],
#  snowfall [cm], snow_depth [cm], temperature_max/min/mean [°C]).
# Designed for thin notebook cells in src/temp/.

NOAA_VAR_LABELS = {
    'precip_amount'  : 'Precip (mm/day)',
    'snowfall'       : 'Snowfall (cm/day)',
    'snow_depth'     : 'Snow depth (cm)',
    'temperature'    : 'Mean temp (°C)',
    'temperature_max': 'Max temp (°C)',
    'temperature_min': 'Min temp (°C)',
}


def load_noaa_daily(
    csv_dir: Union[str, Path],
    *,
    station_name_map: Optional[Dict[str, str]] = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """Load all per-station NOAA GHCN-Daily CSVs in `csv_dir` into one long DF.

    The fetcher writes one CSV per station plus a `*_combined.csv`. We read
    the per-station files so adding/removing a station doesn't require a
    re-run of the fetcher.

    Returns
    -------
    DataFrame in long form with the original columns plus 'station_name'.
    Sorted by (station_id, datetime). Datetime is `datetime64[ns]`.
    """
    csv_dir = Path(csv_dir)
    files = sorted(p for p in csv_dir.glob('US*_noaa_daily*.csv'))
    if not files:
        raise FileNotFoundError(f'No US*_noaa_daily*.csv in {csv_dir}')
    parts = []
    for fp in files:
        df = pd.read_csv(fp, parse_dates=['datetime'])
        parts.append(df)
    out = pd.concat(parts, ignore_index=True)
    out = out.sort_values(['station_id', 'datetime']).reset_index(drop=True)
    if station_name_map:
        out['station_name'] = out['station_id'].map(station_name_map).fillna(out['station_id'])
    else:
        out['station_name'] = out['station_id']
    if verbose:
        n_st = out['station_id'].nunique()
        print(f'Loaded {len(files)} station file(s), {n_st} station(s), '
              f'{len(out):,} rows, '
              f"{out['datetime'].min().date()} → {out['datetime'].max().date()}")
    return out


def noaa_daily_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One-row-per-station summary table.

    Columns: n_days, missing_precip, precip_total_mm, n_rainy_days (≥1 mm),
    snow_total_cm, n_snow_days (≥0.1 cm), tmin_C, tmax_C, tmean_C.
    """
    rows = []
    for sid, g in df.groupby('station_id', sort=False):
        precip = g['precip_amount'] if 'precip_amount' in g else pd.Series(dtype=float)
        snow   = g['snowfall']      if 'snowfall'      in g else pd.Series(dtype=float)
        tmin   = g['temperature_min'] if 'temperature_min' in g else pd.Series(dtype=float)
        tmax   = g['temperature_max'] if 'temperature_max' in g else pd.Series(dtype=float)
        tmean  = g['temperature']     if 'temperature'     in g else pd.Series(dtype=float)
        rows.append({
            'station_id'      : sid,
            'station_name'    : g['station_name'].iloc[0],
            'n_days'          : len(g),
            'missing_precip'  : int(precip.isna().sum()),
            'precip_total_mm' : round(float(precip.sum(skipna=True)), 1),
            'n_rainy_days'    : int((precip >= 1.0).sum()),
            'snow_total_cm'   : round(float(snow.sum(skipna=True)), 1),
            'n_snow_days'     : int((snow >= 0.1).sum()),
            'tmin_C'          : round(float(tmin.min()), 1) if not tmin.empty else None,
            'tmax_C'          : round(float(tmax.max()), 1) if not tmax.empty else None,
            'tmean_C'         : round(float(tmean.mean()), 2) if not tmean.empty else None,
        })
    return pd.DataFrame(rows)


def noaa_pivot(df: pd.DataFrame, var: str) -> pd.DataFrame:
    """Wide DataFrame indexed by date with one column per station (by name)."""
    return (df.pivot_table(index='datetime', columns='station_name',
                           values=var, aggfunc='mean')
              .sort_index())


def plot_noaa_daily_timeseries(
    df: pd.DataFrame, var: str = 'precip_amount', *,
    rolling: Optional[int] = None,
    figsize: Tuple[float, float] = (14, 4),
):
    """Per-station daily series. `rolling` applies a centered mean window."""
    import matplotlib.pyplot as plt
    wide = noaa_pivot(df, var)
    if rolling:
        wide = wide.rolling(rolling, center=True, min_periods=1).mean()
    fig, ax = plt.subplots(figsize=figsize)
    for col in wide.columns:
        ax.plot(wide.index, wide[col], lw=1.0, label=col)
    ax.set_ylabel(NOAA_VAR_LABELS.get(var, var))
    title = f'NOAA daily • {var}'
    if rolling:
        title += f'  ({rolling}d rolling mean)'
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    return {'fig': fig, 'ax': ax, 'wide': wide}


def plot_noaa_monthly_climatology(
    df: pd.DataFrame, var: str = 'precip_amount', *,
    figsize: Tuple[float, float] = (12, 4),
):
    """Bar plot of monthly aggregates (sum for precip/snow, mean for temp)."""
    import matplotlib.pyplot as plt
    wide = noaa_pivot(df, var)
    agg = 'sum' if var in ('precip_amount', 'snowfall') else 'mean'
    monthly = wide.resample('MS').agg(agg)
    fig, ax = plt.subplots(figsize=figsize)
    n_st = monthly.shape[1]
    x = np.arange(len(monthly))
    w = 0.85 / max(n_st, 1)
    for i, col in enumerate(monthly.columns):
        ax.bar(x + (i - (n_st - 1) / 2) * w, monthly[col].values, width=w, label=col)
    ax.set_xticks(x)
    ax.set_xticklabels([d.strftime('%Y-%m') for d in monthly.index], rotation=45, ha='right')
    ax.set_ylabel(f"{NOAA_VAR_LABELS.get(var, var)}  ({agg}/month)")
    ax.set_title(f'NOAA monthly {agg} • {var}')
    ax.grid(True, axis='y', alpha=0.3)
    ax.legend(fontsize=8, ncol=2, title='station')
    fig.tight_layout()
    return {'fig': fig, 'ax': ax, 'monthly': monthly}


def plot_noaa_station_scatter(
    df: pd.DataFrame, var: str = 'precip_amount', *,
    reference: Optional[str] = None,
    figsize: Tuple[float, float] = (10, 3.2),
):
    """Pairwise scatter of each station vs a reference station.

    Each subplot shows one station's daily values against the reference's,
    plus the 1:1 line, Pearson r, and RMSE.
    """
    import matplotlib.pyplot as plt
    wide = noaa_pivot(df, var).dropna(how='all')
    if reference is None:
        reference = wide.columns[0]
    if reference not in wide.columns:
        raise ValueError(f'reference {reference!r} not in {list(wide.columns)}')
    others = [c for c in wide.columns if c != reference]
    fig, axes = plt.subplots(1, len(others), figsize=figsize, sharex=True, sharey=True)
    if len(others) == 1:
        axes = [axes]
    stats = {}
    for ax, col in zip(axes, others):
        x = wide[reference]; y = wide[col]
        m = x.notna() & y.notna()
        xv, yv = x[m].to_numpy(), y[m].to_numpy()
        ax.scatter(xv, yv, s=8, alpha=0.5)
        if len(xv) > 1:
            lim = float(max(xv.max(), yv.max()))
            ax.plot([0, lim], [0, lim], 'k--', lw=0.8, alpha=0.6)
            r = float(np.corrcoef(xv, yv)[0, 1])
            rmse = float(np.sqrt(np.mean((xv - yv) ** 2)))
            stats[col] = {'r': r, 'rmse': rmse, 'n': int(m.sum())}
            ax.set_title(f'{col}\nr={r:.3f}  RMSE={rmse:.2f}', fontsize=9)
        ax.set_xlabel(reference)
        ax.grid(True, alpha=0.3)
    axes[0].set_ylabel(NOAA_VAR_LABELS.get(var, var))
    fig.suptitle(f'NOAA daily {var} • vs {reference}', y=1.02)
    fig.tight_layout()
    return {'fig': fig, 'axes': axes, 'stats': pd.DataFrame(stats).T}


def _load_wu_condition_lookup(networks) -> Dict[int, str]:
    """Resolve WU `condition` integer codes → label strings.

    Pulls the lookup JSON from the WU netCDF's `qc_condition_lookup` attr
    (written by `pws_qc.save_qc`). Returns {} if not present.
    """
    import json
    wu = networks.get('WU PWS', {})
    if not wu:
        return {}
    src = None
    for ds in wu.values():
        if 'qc_condition_lookup' in ds.attrs:
            src = ds.attrs['qc_condition_lookup']
            src_path = Path('dataset/raw/full/outputs') / src
            if src_path.exists():
                break
        src_path = None
    if not src_path or not src_path.exists():
        # Last-resort search anywhere under dataset/
        candidates = list(Path('dataset').rglob('*condition_lookup*.json'))
        if not candidates:
            return {}
        src_path = candidates[0]
    raw = json.loads(src_path.read_text())
    return {int(k): v for k, v in raw.items()}


def wu_snow_codes(networks, *, patterns=('snow', 'sleet', 'wintry')) -> Dict[int, str]:
    """Return {code: label} for WU condition codes whose label matches any pattern."""
    lookup = _load_wu_condition_lookup(networks)
    return {c: lab for c, lab in lookup.items()
            if any(p in lab.lower() for p in patterns)}


def mesonet_daily_new_snow(networks, *, drop_threshold_cm: float = 0.5) -> pd.DataFrame:
    """Daily new snow accumulation per Mesonet station.

    For each station: resample hourly `snow_depth` to a daily end-of-day value,
    take the first-difference. Positive differences = new snow (cm/day).
    Drops below `drop_threshold_cm` (sub-cm jumps tend to be sensor noise).
    """
    meso = networks.get('Mesonet', {})
    cols = {}
    for sid, ds in meso.items():
        if 'snow_depth' not in ds.data_vars:
            continue
        s = ds['snow_depth'].squeeze(drop=True).to_series()
        s.index = pd.to_datetime(s.index)
        daily = s.resample('1D').last()
        new = daily.diff().clip(lower=0).where(lambda x: x >= drop_threshold_cm, 0.0)
        cols[sid] = new
    if not cols:
        return pd.DataFrame()
    out = pd.concat(cols, axis=1).sort_index()
    out.index.name = 'date'
    return out


def plot_mesonet_vs_noaa_daily_snow(
    networks, noaa_df: pd.DataFrame, *,
    window: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None,
    drop_threshold_cm: float = 0.5,
    figsize: Tuple[float, float] = (14, 4),
):
    """Bar plot: Mesonet daily Δsnow_depth (per station) overlaid with NOAA
    mean daily snowfall (line). Filters to days where any source > 0."""
    import matplotlib.pyplot as plt
    meso = mesonet_daily_new_snow(networks, drop_threshold_cm=drop_threshold_cm)
    noaa = (noaa_pivot(noaa_df, 'snowfall')
            if 'snowfall' in noaa_df.columns else pd.DataFrame())
    if window is not None:
        s, e = pd.Timestamp(window[0]), pd.Timestamp(window[1])
        meso = meso.loc[s:e]
        noaa = noaa.loc[s:e]
    # Restrict to days with snow anywhere
    mask = (meso.sum(axis=1) > 0) | (noaa.sum(axis=1) > 0)
    meso, noaa = meso.loc[mask], noaa.loc[mask]
    if meso.empty and noaa.empty:
        print('No snow days in window.')
        return None
    idx = meso.index.union(noaa.index).sort_values()
    fig, ax = plt.subplots(figsize=figsize)
    n_st = max(meso.shape[1], 1)
    x = np.arange(len(idx))
    w = 0.85 / n_st
    for i, col in enumerate(meso.columns):
        vals = meso[col].reindex(idx).fillna(0).values
        ax.bar(x + (i - (n_st - 1) / 2) * w, vals, width=w, label=f'Mesonet {col}', alpha=0.85)
    if not noaa.empty:
        ax.plot(x, noaa.mean(axis=1).reindex(idx).values, 'k-o', ms=4, lw=1.4,
                label='NOAA mean daily snowfall')
        ax.plot(x, noaa.max(axis=1).reindex(idx).values, color='dimgray', ls='--', lw=1.0,
                label='NOAA max (any station)')
    ax.set_xticks(x)
    ax.set_xticklabels([d.strftime('%Y-%m-%d') for d in idx], rotation=60, ha='right', fontsize=8)
    ax.set_ylabel('cm/day')
    ax.set_title('Mesonet daily Δsnow_depth  vs  NOAA daily snowfall')
    ax.grid(True, axis='y', alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    return {'fig': fig, 'ax': ax, 'mesonet': meso, 'noaa': noaa}


def snow_detection_timeline(
    networks, noaa_df: pd.DataFrame, *,
    window: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None,
    threshold_cm: float = 0.1,
    wu_airports_only: bool = True,
    figsize: Tuple[float, float] = (14, 6),
):
    """Daily snow-detection grid across NOAA / Mesonet / WU stations.

    Each row is one station; each column is one day; a cell is shaded if snow
    was detected on that day. Detection rules:
      - NOAA (each station)  : daily `snowfall` ≥ threshold_cm
      - Mesonet (each station): any hour with positive Δsnow_depth (cumulative
                                daily new snow ≥ threshold_cm)
      - WU      (each station): any hour where `condition` resolves to a label
                                containing 'snow' / 'sleet' / 'wintry'
    Set `wu_airports_only=True` to restrict WU to 4-letter airport-coded sids
    (KJFK, KLGA, KNYC, KEWR, KTEB).
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    # --- NOAA per-station daily snow flag -------------------------------
    noaa_wide = (noaa_pivot(noaa_df, 'snowfall')
                 if 'snowfall' in noaa_df.columns else pd.DataFrame())
    noaa_flag = (noaa_wide >= threshold_cm) if not noaa_wide.empty else pd.DataFrame()

    # --- Mesonet per-station daily snow flag ---------------------------
    meso_daily = mesonet_daily_new_snow(networks, drop_threshold_cm=threshold_cm)
    meso_flag = (meso_daily >= threshold_cm) if not meso_daily.empty else pd.DataFrame()

    # --- WU per-station daily snow flag (any snow-coded hour) ----------
    snow_codes = set(wu_snow_codes(networks).keys())
    wu = networks.get('WU PWS', {})
    wu_cols = {}
    if snow_codes and wu:
        airport_re = re.compile(r'^K[A-Z]{3}$')
        for sid, ds in wu.items():
            if wu_airports_only and not airport_re.match(sid):
                continue
            if 'condition' not in ds.data_vars:
                continue
            s = ds['condition'].squeeze(drop=True).to_series()
            s.index = pd.to_datetime(s.index)
            is_snow = s.isin(snow_codes).astype(int)
            daily = is_snow.resample('1D').max().astype(bool)
            wu_cols[sid] = daily
    wu_flag = pd.concat(wu_cols, axis=1).sort_index() if wu_cols else pd.DataFrame()

    # --- Align all to a shared daily index -----------------------------
    pieces = [df for df in (noaa_flag, meso_flag, wu_flag) if not df.empty]
    if not pieces:
        print('No snow data available.')
        return None
    full_idx = pieces[0].index
    for p in pieces[1:]:
        full_idx = full_idx.union(p.index)
    full_idx = full_idx.sort_values()
    if window is not None:
        s, e = pd.Timestamp(window[0]), pd.Timestamp(window[1])
        full_idx = full_idx[(full_idx >= s) & (full_idx <= e)]
    # Filter to days where at least one station detected snow (sparse view)
    rows, labels, group_colors = [], [], []
    GROUP_COLOR = {'NOAA': '#1f77b4', 'Mesonet': '#2ca02c', 'WU': '#d62728'}
    for group, df in [('NOAA', noaa_flag), ('Mesonet', meso_flag), ('WU', wu_flag)]:
        if df.empty:
            continue
        df_a = df.reindex(full_idx).fillna(False).astype(bool)
        for col in df_a.columns:
            rows.append(df_a[col].values.astype(int))
            labels.append(f'{group}: {col}')
            group_colors.append(GROUP_COLOR[group])
    if not rows:
        print('Nothing to plot.')
        return None
    grid = np.array(rows)
    snow_days = grid.any(axis=0)
    if snow_days.sum() == 0:
        print('No snow days detected by any station.')
        return None
    grid = grid[:, snow_days]
    x_labels = [d.strftime('%Y-%m-%d') for d in full_idx[snow_days]]

    fig, ax = plt.subplots(figsize=figsize)
    # Use a row-colored grid: each row tinted with its group color, alpha=value
    rgba = np.zeros((*grid.shape, 4))
    for i, gc in enumerate(group_colors):
        from matplotlib.colors import to_rgba
        r, g, b, _ = to_rgba(gc)
        rgba[i, :, 0] = r; rgba[i, :, 1] = g; rgba[i, :, 2] = b
        rgba[i, :, 3] = grid[i] * 0.85  # transparent where no snow
    ax.imshow(rgba, aspect='auto', interpolation='nearest')
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xticks(range(grid.shape[1]))
    ax.set_xticklabels(x_labels, rotation=60, ha='right', fontsize=7)
    ax.set_title(
        f'Snow detection timeline  •  threshold={threshold_cm} cm  •  '
        f'{grid.shape[0]} stations × {grid.shape[1]} snow days'
    )
    # Group divider lines
    boundaries = np.cumsum([
        noaa_flag.shape[1] if not noaa_flag.empty else 0,
        meso_flag.shape[1] if not meso_flag.empty else 0,
    ])
    for b in boundaries:
        if 0 < b < len(labels):
            ax.axhline(b - 0.5, color='white', lw=1.5)
    ax.grid(False)
    fig.tight_layout()
    return {
        'fig': fig, 'ax': ax,
        'noaa': noaa_flag, 'mesonet': meso_flag, 'wu': wu_flag,
        'snow_days': full_idx[snow_days],
    }


def noaa_snow_event_table(
    df: pd.DataFrame, *,
    threshold_cm: float = 0.1,
    gap_days: int = 1,
) -> pd.DataFrame:
    """Return a table of multi-station snow events.

    A snow *day* is any date with snowfall ≥ threshold at any station.
    Consecutive snow days (with gaps ≤ gap_days) are merged into one event.
    Per event we report: start, end, n_days, n_stations_with_snow,
    max_snowfall_cm (any station, any day), and max_snow_depth_cm (peak).
    """
    if 'snowfall' not in df.columns:
        return pd.DataFrame()
    wide_sf = noaa_pivot(df, 'snowfall')
    snow_days = (wide_sf >= threshold_cm).any(axis=1)
    dates = wide_sf.index[snow_days]
    if len(dates) == 0:
        return pd.DataFrame()
    diffs = np.diff(dates.values).astype('timedelta64[D]').astype(int)
    breaks = np.where(diffs > gap_days)[0]
    starts = np.concatenate([[0], breaks + 1])
    ends   = np.concatenate([breaks, [len(dates) - 1]])
    wide_sd = noaa_pivot(df, 'snow_depth') if 'snow_depth' in df.columns else None
    rows = []
    for s, e in zip(starts, ends):
        d0, d1 = dates[s], dates[e]
        window_sf = wide_sf.loc[d0:d1]
        n_st = int((window_sf >= threshold_cm).any(axis=0).sum())
        rows.append({
            'start'             : d0.date(),
            'end'               : d1.date(),
            'n_days'            : int((d1 - d0).days) + 1,
            'n_stations_snow'   : n_st,
            'max_snowfall_cm'   : round(float(window_sf.max().max()), 1),
            'max_snow_depth_cm' : (round(float(wide_sd.loc[d0:d1].max().max()), 1)
                                   if wide_sd is not None else None),
        })
    return pd.DataFrame(rows)


# ============================================================================
# CML attenuation vs precip phase  (Part 2 of the methods/ CML study)
# ============================================================================
def plot_cml_phase_scatter(
    df: pd.DataFrame,
    *,
    facet: str = 'band_tier',
    facet_order: Sequence[str] = ('sub6', 'K', 'V-low', 'V-high'),
    x: str = 'precip_mm',
    y: str = 'att_per_km',
    phase_col: str = 'phase',
    failure_col: Optional[str] = 'failure',
    xscale: str = 'log',
    yscale: str = 'linear',
    ylim: Optional[Tuple[float, float]] = None,
    colors: Optional[dict] = None,
    edge_colors: Optional[dict] = None,
    mark_failures: bool = True,
    figsize: Tuple[float, float] = (18, 6),
    point_size: float = 10,
    alpha: float = 0.5,
    title_fs: Optional[float] = 13,
    label_fs: float = 12,
    tick_fs: float = 11,
    legend_fs: float = 10,
    x_label: Optional[str] = None,
    y_label: Optional[str] = None,
    suptitle: Optional[str] = None,
    save_path=None,
    verbose: bool = True,
):
    """Multi-panel CML attenuation-vs-precip scatter, coloured by precip phase.

    Style-matched to `plot_phase_temp_scatter`: identical snow/mixed/rain
    palette, same draw order (rain wash on the bottom, then mixed, then snow on
    top so rare phases are not buried), legend only in the first panel.

    One panel per unique value of `facet` (default the band tier), so the panel
    count auto-scales to whatever subset is passed (one band, four bands, or any
    other grouping column such as a per-link id or a list of datasets).

    Parameters
    ----------
    df          long-form frame; needs columns [facet, x, y, phase_col] and
                optionally `failure_col`. 'dry' rows are dropped before plotting.
    x / y       column names. Defaults plot specific attenuation `att_per_km`
                (dB/km, y) against the hourly precip rate `precip_mm` (x).
    facet_order preferred panel order; values not present are skipped and any
                extra facet values are appended after these.
    failure_col 1 = mid-event link outage (see cml_baseline.detect_failures).
                When `mark_failures`, those points are overdrawn as open
                crossed markers ('X', no fill) so imputed/failed samples are
                visible, exactly as required by the Part-2 spec.
    colors / edge_colors
                per-phase overrides merged over the shared defaults.

    Returns {'fig', 'axes'}.
    """
    import matplotlib.pyplot as plt
    import matplotlib.colors as _mc

    def _darken(c, f=0.45):
        r, g, b = _mc.to_rgb(c)
        return (r * f, g * f, b * f)

    # Shared palette (matches plot_phase_temp_scatter).
    ph_colors = {'rain': '#2166ac', 'mixed': '#e377c2', 'snow': '#00e5ff'}
    if colors:
        ph_colors.update(colors)
    ph_edge = {'rain': 'none',
               'mixed': _darken(ph_colors['mixed']),
               'snow':  _darken(ph_colors['snow'])}
    if edge_colors:
        ph_edge.update(edge_colors)
    ph_alpha = {'rain': min(alpha, 0.32), 'mixed': 0.95, 'snow': 1.0}
    ph_lw = {'rain': 0.0, 'mixed': 0.5, 'snow': 0.7}

    work = df.dropna(subset=[x, y]).copy()
    work = work[work[phase_col] != 'dry']
    if work.empty:
        if verbose:
            print('No wet CML points to plot.')
        return {'fig': None, 'axes': None}

    present = list(pd.unique(work[facet]))
    panels = [v for v in facet_order if v in present]
    panels += [v for v in present if v not in panels]
    if not panels:
        return {'fig': None, 'axes': None}

    fig, axes = plt.subplots(1, len(panels), figsize=figsize, sharey=True, sharex=True)
    if len(panels) == 1:
        axes = [axes]

    for idx, (ax, fv) in enumerate(zip(axes, panels)):
        sub_all = work[work[facet] == fv]
        handles = {}
        for ph in ('rain', 'mixed', 'snow'):
            sub = sub_all[sub_all[phase_col] == ph]
            if sub.empty:
                continue
            handles[ph] = ax.scatter(
                sub[x], sub[y], s=point_size, alpha=ph_alpha[ph],
                color=ph_colors[ph], label=ph,
                edgecolors=ph_edge[ph], linewidths=ph_lw[ph])
        # Failure overlay: small semi-transparent crosses so imputed/outage
        # points are visible on inspection without swamping the real data.
        if mark_failures and failure_col in sub_all:
            fpts = sub_all[sub_all[failure_col].astype(float) > 0]
            if not fpts.empty:
                ax.scatter(fpts[x], fpts[y], s=point_size * 1.4, marker='x',
                           c='0.25', linewidths=0.5, alpha=0.35,
                           label='link outage', zorder=4)
        n = len(sub_all)
        ax.set_title(f'{fv}  (n={n})', fontsize=(title_fs or 13), fontweight='bold')
        ax.set_xlabel(x_label or 'Hourly precipitation (mm)', fontsize=label_fs)
        ax.grid(True, which='both', alpha=0.3)
        ax.tick_params(labelsize=tick_fs)
        if idx == 0:
            order = [p for p in ('snow', 'mixed', 'rain') if p in handles]
            extra = ([ax.scatter([], [], s=point_size * 1.4, marker='x',
                                  c='0.25', linewidths=0.5)]
                     if mark_failures else [])
            extra_lbl = ['link outage'] if mark_failures else []
            if order or extra:
                leg = ax.legend([handles[p] for p in order] + extra,
                                order + extra_lbl,
                                title='Precip type', frameon=True,
                                edgecolor='gray', framealpha=0.9, fontsize=legend_fs)
                for lh in getattr(leg, 'legend_handles',
                                  getattr(leg, 'legendHandles', [])):
                    lh.set_alpha(1.0)

    axes[0].set_ylabel(y_label or 'Specific attenuation (dB/km)', fontsize=label_fs)
    axes[0].set_xscale(xscale)
    axes[0].set_yscale(yscale)
    if ylim is not None:
        axes[0].set_ylim(*ylim)
    if suptitle:
        fig.suptitle(suptitle, fontsize=(title_fs or 13) + 2, fontweight='bold')
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path, dpi=140, bbox_inches='tight')
        if verbose:
            print(f'saved → {save_path}')
    return {'fig': fig, 'axes': axes}
