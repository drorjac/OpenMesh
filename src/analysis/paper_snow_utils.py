"""
paper_snow_utils.py
===================
Focused helpers for the snow-sensing paper sub-study
(`dataset/raw/full/paper/`). Built for the OpenSense-CML netCDF layout
(`ds_opensense_cml.nc`: dims cml_id x sublink_id x time, single `rsl`
variable, `frequency` as a per-sublink coordinate) and the grouped ASOS
netCDF (one group per station, per-minute `precip_category`).

Design: notebook cells stay thin (knobs + one call); all logic lives here.

Attenuation convention
----------------------
Links record received signal level RSL(t) [dBm]. Clear-sky RSL is the upper
envelope; precipitation pushes RSL down (more negative). We define

    A(t) = baseline_RSL - RSL(t)   (clipped at 0)

so attenuation is >= 0 and grows with hydrometeor / accretion loss. The
per-link baseline is the median RSL over dry-labelled bins (fallback: 90th
percentile of in-window RSL).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
import xarray as xr
import netCDF4 as nc

# ---------------------------------------------------------------------------
# Frequency bands
# ---------------------------------------------------------------------------
# Four bands matching the paper: sub-6 C-band, K-band, V-band 60 GHz, V-band 65-70 GHz.
BANDS = {
    'sub6': (0,      8_000),     # C-band ~5 GHz
    'K':    (20_000, 30_000),    # 24 GHz
    'V60':  (55_000, 63_000),    # 58-62 GHz  (short-range high-freq)
    'V65':  (63_000, 72_000),    # 64-70 GHz  <- long high-freq links (paper focus)
}
BAND_ORDER = ['sub6', 'K', 'V60', 'V65']
HIGH_FREQ_BAND = 'V65'

# precip-category priority when several minutes fall in one bin / several
# stations disagree: keep the "most frozen / most severe" label.
CAT_PRIORITY = {'snow': 4, 'mix': 3, 'ice': 3, 'rain': 2, 'dry': 1, 'missing': 0}
WEATHER_CLASSES = ['dry', 'rain', 'mix', 'snow']


def band_of(freq_mhz: float) -> str:
    for name, (lo, hi) in BANDS.items():
        if lo <= freq_mhz <= hi:
            return name
    return '?'


# ---------------------------------------------------------------------------
# ASOS reference weather
# ---------------------------------------------------------------------------
def _decode(arr) -> np.ndarray:
    return np.array([x.decode() if isinstance(x, bytes) else str(x)
                     for x in np.array(arr).ravel()])


def load_asos_reference(asos_nc: str | Path, station: str = 'LGA',
                        start: str = '2023-11-01', end: str = '2024-04-30',
                        freq: str = '10min') -> pd.DataFrame:
    """Per-`freq` weather reference from one ASOS station group.

    Returns DataFrame indexed by time with columns:
      cat  : dominant precip category in the bin (priority snow>mix>rain>dry)
      temp : mean air temperature [C]
      rain : summed liquid rainfall in the bin [mm]
    """
    d = nc.Dataset(str(asos_nc))
    g = d.groups[station]
    t = pd.to_datetime(np.array(g.variables['time'][:]), unit='s', utc=True).tz_convert(None)
    cols = {
        'cat':  _decode(g.variables['precip_category'][:]),
        'temp': np.array(g.variables['temperature'][:]).ravel().astype(float),
        'rain': np.array(g.variables['rainfall_amount'][:]).ravel().astype(float),
    }
    if 'dewpoint' in g.variables:
        cols['dewpoint'] = np.array(g.variables['dewpoint'][:]).ravel().astype(float)
    df = pd.DataFrame(cols, index=t)
    d.close()
    df = df[~df.index.duplicated()].sort_index().loc[start:end]

    def _dom(s):
        s = [c for c in s if c != 'missing']
        return max(s, key=lambda c: CAT_PRIORITY.get(c, 0)) if s else 'missing'

    agg = {'cat': _dom, 'temp': 'mean', 'rain': 'sum'}
    if 'dewpoint' in df.columns:
        agg['dewpoint'] = 'mean'
    return df.resample(freq).agg(agg)


def wet_bulb(temp_c, dewpoint_c):
    """Stull (2011) wet-bulb approximation [C] from air temp and dewpoint.
    Wet-bulb ~0 C is the classic snow/rain melting boundary."""
    T = np.asarray(temp_c, dtype=float)
    Td = np.asarray(dewpoint_c, dtype=float)
    # relative humidity from T and Td (Magnus)
    rh = 100.0 * (np.exp((17.625 * Td) / (243.04 + Td)) /
                  np.exp((17.625 * T) / (243.04 + T)))
    rh = np.clip(rh, 1.0, 100.0)
    tw = (T * np.arctan(0.151977 * np.sqrt(rh + 8.313659))
          + np.arctan(T + rh) - np.arctan(rh - 1.676331)
          + 0.00391838 * rh ** 1.5 * np.arctan(0.023101 * rh) - 4.686035)
    return tw


def _runs(cat: pd.Series, target: str, min_bins: int) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    m = (cat == target).values
    out, i, n = [], 0, len(m)
    while i < n:
        if m[i]:
            j = i
            while j < n and m[j]:
                j += 1
            if j - i >= min_bins:
                out.append((cat.index[i], cat.index[j - 1]))
            i = j
        else:
            i += 1
    return out


def detect_events(ref: pd.DataFrame, n_snow=5, n_rain=5, n_mix=3, n_dry=3,
                  bin_min: int = 10) -> pd.DataFrame:
    """Auto-detect representative event windows from the ASOS reference.

    Picks the longest contiguous runs per class. Dry windows are the longest
    fully-dry stretches (sampled across the period so they are not adjacent).
    Returns columns: class, start, end, name, dur_min, t_min, t_max, rain_mm.
    """
    cat = ref['cat']
    spec = {'snow': (n_snow, 6), 'rain': (n_rain, 6), 'mix': (n_mix, 3)}
    rows = []
    for cls, (n, mb) in spec.items():
        runs = sorted(_runs(cat, cls, mb), key=lambda ab: ab[1] - ab[0], reverse=True)[:n]
        for a, b in runs:
            sub = ref.loc[a:b]
            rows.append(dict(cls=cls, start=a, end=b))
    # dry windows: longest dry runs, then spread across the timeline
    dry = sorted(_runs(cat, 'dry', 18), key=lambda ab: ab[1] - ab[0], reverse=True)
    picked = []
    for a, b in dry:
        # cap each dry window to 6h so it is comparable to the wet events
        b = min(b, a + pd.Timedelta(hours=6))
        if all(abs((a - pa).days) >= 3 for pa, _ in picked):
            picked.append((a, b))
        if len(picked) >= n_dry:
            break
    for a, b in picked:
        rows.append(dict(cls='dry', start=a, end=b))

    df = pd.DataFrame(rows)
    df['dur_min'] = ((df['end'] - df['start']).dt.total_seconds() / 60).astype(int) + bin_min
    meta = []
    for _, r in df.iterrows():
        sub = ref.loc[r['start']:r['end']]
        meta.append((round(sub['temp'].min(), 1), round(sub['temp'].max(), 1),
                     round(sub['rain'].sum(), 1)))
    df[['t_min', 't_max', 'rain_mm']] = meta
    df['name'] = df['start'].dt.strftime('%Y-%m-%d_%H%M') + '_' + df['cls']
    return df.sort_values(['cls', 'start']).reset_index(drop=True)


# ---------------------------------------------------------------------------
# CML link selection + attenuation
# ---------------------------------------------------------------------------
def list_links(cml_ds: xr.Dataset, band: Optional[str] = None) -> pd.DataFrame:
    """One row per (cml_id, sublink) with frequency/band/geometry.

    band: restrict to a band key in BANDS (e.g. 'V' for high-freq). None = all.
    """
    freq = cml_ds['frequency'].values  # (cml_id, sublink_id)
    cid = cml_ds['cml_id'].values
    sid = cml_ds['sublink_id'].values
    rows = []
    for i in range(freq.shape[0]):
        for j in range(freq.shape[1]):
            f = freq[i, j]
            if not np.isfinite(f):
                continue
            rows.append(dict(i=i, j=j, cml_id=str(cid[i]), sublink=str(sid[j]),
                             freq_mhz=float(f), freq_ghz=round(float(f) / 1000, 1),
                             band=band_of(f)))
    df = pd.DataFrame(rows)
    if 'length' in cml_ds.coords:
        L = cml_ds['length'].values
        df['length_m'] = [float(L[r.i, r.j]) if np.ndim(L) == 2 else float(L[r.i])
                          for r in df.itertuples()]
    if band is not None:
        df = df[df['band'] == band].reset_index(drop=True)
    return df


def _clean_series(rsl: np.ndarray, times: pd.DatetimeIndex, keep: np.ndarray) -> pd.Series:
    """Mask to `keep` window, drop NaN, dedupe duplicate stamps, sort."""
    v = rsl[keep]
    idx = times[keep]
    s = pd.Series(v, index=idx).dropna()
    if s.index.has_duplicates:
        s = s.groupby(level=0).median()
    return s.sort_index()


def build_keep_mask(times: pd.DatetimeIndex, windows: pd.DataFrame,
                    pad_min: int = 60) -> np.ndarray:
    """Boolean mask over `times` covering every window (+/- pad)."""
    keep = np.zeros(len(times), dtype=bool)
    tv = times.values
    pad = np.timedelta64(pad_min, 'm')
    for _, r in windows.iterrows():
        a = np.datetime64(r['start']) - pad
        b = np.datetime64(r['end']) + pad
        keep |= (tv >= a) & (tv <= b)
    return keep


def pick_links(cml_ds: xr.Dataset, band: str = HIGH_FREQ_BAND, n: int = 30,
               per_cml: int = 2, by: str = 'freq') -> pd.DataFrame:
    """Link selection for a band.

    by='freq'   : round-robin across frequency sub-bands (diverse sampling)
    by='length' : longest physical links first (representative long links)
    `per_cml` caps sublinks per cml_id; total <= n.
    """
    df = list_links(cml_ds, band=band)
    if df.empty:
        return df
    if by == 'length' and 'length_m' in df.columns:
        df = df.sort_values('length_m', ascending=False)
        keep, seen = [], {}
        for r in df.itertuples():
            if seen.get(r.cml_id, 0) >= per_cml:
                continue
            keep.append(r.Index)
            seen[r.cml_id] = seen.get(r.cml_id, 0) + 1
        out = df.loc[keep]
    else:
        df = df.sort_values(['freq_ghz', 'cml_id'])
        keep, seen = [], {}
        for fghz, grp in df.groupby('freq_ghz'):
            for r in grp.itertuples():
                if seen.get(r.cml_id, 0) >= per_cml:
                    continue
                keep.append(r.Index)
                seen[r.cml_id] = seen.get(r.cml_id, 0) + 1
        out = df.loc[keep]
    return out.head(n).sort_values(['cml_id', 'freq_ghz']).reset_index(drop=True)


def pick_long_links_4band(cml_ds: xr.Dataset, n_per_band: int = 40,
                          per_cml: int = 1) -> pd.DataFrame:
    """Candidate *long* links from each of the four bands (one sublink per
    cml_id by default, so they are distinct physical links), longest first.
    Pass a generous `n_per_band`; reads cost the same regardless of link count,
    and `representative_long_links` then keeps the longest well-covered ones."""
    parts = [pick_links(cml_ds, b, n=n_per_band, per_cml=per_cml, by='length')
             for b in BAND_ORDER]
    return pd.concat([p for p in parts if not p.empty], ignore_index=True)


def representative_long_links(tidy: pd.DataFrame, n_per_band: int = 5,
                              min_bins: int = 40) -> pd.DataFrame:
    """From an extracted tidy table, pick the longest well-covered links per
    band (>= min_bins event bins). Returns one row per chosen link with
    band, cml_id, freq_ghz, length_m, n_bins."""
    per = (tidy.groupby(['band', 'cml_id'])
           .agg(freq_ghz=('freq_ghz', 'first'), length_m=('length_m', 'first'),
                n_bins=('attenuation', 'size')).reset_index())
    per = per[per['n_bins'] >= min_bins]
    out = []
    for b in BAND_ORDER:
        sub = per[per['band'] == b].sort_values('length_m', ascending=False).head(n_per_band)
        out.append(sub)
    res = pd.concat(out, ignore_index=True)
    res['band'] = pd.Categorical(res['band'], BAND_ORDER, ordered=True)
    return res.sort_values(['band', 'length_m'], ascending=[True, False]).reset_index(drop=True)


def subset_to_links(tidy: pd.DataFrame, rep: pd.DataFrame) -> pd.DataFrame:
    """Filter a tidy table to the (band, cml_id) pairs in `rep`."""
    keys = set(zip(rep['band'].astype(str), rep['cml_id'].astype(str)))
    m = [ (b, c) in keys for b, c in zip(tidy['band'].astype(str), tidy['cml_id'].astype(str)) ]
    return tidy[pd.Series(m, index=tidy.index)].reset_index(drop=True)


def extract_attenuation(cml_ds: xr.Dataset, links: pd.DataFrame,
                        ref: pd.DataFrame, windows: pd.DataFrame,
                        time_res: str = '10min', pad_min: int = 60,
                        min_event_bins: int = 12,
                        min_dry_bins: int = 6) -> pd.DataFrame:
    """Tidy long table of per-bin attenuation for the selected links.

    Reads one `cml_id` block (all sublinks) at a time to amortise the HDF5
    decompress, restricts to the union of event windows, resamples to
    `time_res` (median), derives a per-link dry baseline, computes
    A = baseline - RSL (clipped >=0), and labels every bin with the ASOS
    class + temperature.

    Links with fewer than `min_event_bins` populated bins are dropped.

    Returns columns: time, cml_id, sublink, freq_ghz, band, length_m,
    rsl, baseline, attenuation, cls, temp, event
    """
    times = pd.to_datetime(cml_ds['time'].values)
    keep = build_keep_mask(times, windows, pad_min=pad_min)

    # per-bin class + temp (+ dewpoint, rain) from the reference (already at
    # ~time_res), and the event-name label per bin
    rcols = ['cat', 'temp'] + [c for c in ('dewpoint', 'rain') if c in ref.columns]
    ref_r = ref[rcols]
    ev = pd.Series('none', index=ref_r.index, dtype=object)
    for _, r in windows.iterrows():
        ev.loc[r['start']:r['end']] = r['name']

    # Fast read: the chunk layout makes per-sublink reads wasteful, but a
    # contiguous time-slice across all links is chunk-aligned and cheap. The
    # kept timesteps form a handful of contiguous storage runs -> read those.
    idx = np.where(keep)[0]
    if idx.size == 0:
        return pd.DataFrame()
    splits = np.where(np.diff(idx) > 1)[0] + 1
    runs = [(int(g[0]), int(g[-1]) + 1) for g in np.split(idx, splits)]

    # accumulate kept RSL per selected (i,j) across runs
    pairs = list(zip(links['i'].astype(int), links['j'].astype(int)))
    acc = {p: [] for p in pairs}
    tt = []
    for s, e in runs:
        block = cml_ds['rsl'].isel(time=slice(s, e)).values  # (cml, sublink, n)
        tt.append(times[s:e].values)
        for (i, j) in pairs:
            acc[(i, j)].append(block[i, j])
        del block
    tcat = pd.DatetimeIndex(np.concatenate(tt))

    out = []
    for r in links.itertuples():
        v = np.concatenate(acc[(int(r.i), int(r.j))])
        s = pd.Series(v, index=tcat).dropna()
        if not s.empty:
            if s.index.has_duplicates:
                s = s.groupby(level=0).median()
            b = s.sort_index().resample(time_res).median().dropna()
        else:
            continue
        df = pd.DataFrame({'rsl': b})
        df['cls'] = ref_r['cat'].reindex(df.index)
        df['temp'] = ref_r['temp'].reindex(df.index)
        if 'dewpoint' in ref_r.columns:
            df['dewpoint'] = ref_r['dewpoint'].reindex(df.index)
        if 'rain' in ref_r.columns:
            df['rain_mm'] = ref_r['rain'].reindex(df.index)
        df['event'] = ev.reindex(df.index).fillna('none')
        df = df.dropna(subset=['cls'])
        df = df[df['cls'].isin(WEATHER_CLASSES)]
        if len(df) < min_event_bins:
            continue
        dry = df.loc[df['cls'] == 'dry', 'rsl']
        baseline = dry.median() if len(dry) >= min_dry_bins else df['rsl'].quantile(0.90)
        df['baseline'] = baseline
        df['attenuation'] = (baseline - df['rsl']).clip(lower=0)
        length_m = getattr(r, 'length_m', np.nan)
        # specific (length-normalised) attenuation [dB/km] — the right quantity
        # for comparing path-integrated loss across links of different lengths.
        df['attenuation_per_km'] = df['attenuation'] / (length_m / 1000.0) \
            if length_m and np.isfinite(length_m) and length_m > 0 else np.nan
        df['cml_id'] = r.cml_id
        df['sublink'] = r.sublink
        df['freq_ghz'] = r.freq_ghz
        df['band'] = r.band
        df['length_m'] = length_m
        out.append(df.reset_index().rename(columns={'index': 'time'}))
    if not out:
        return pd.DataFrame()
    tidy = pd.concat(out, ignore_index=True)
    return tidy.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def per_class_stats(tidy: pd.DataFrame, by_band: bool = False) -> pd.DataFrame:
    """Mean/std/median/p90 attenuation per weather class (optionally per band)."""
    keys = (['band', 'cls'] if by_band else ['cls'])
    g = tidy.groupby(keys)['attenuation']
    stats = g.agg(n='count', mean='mean', std='std', median='median',
                  p90=lambda x: x.quantile(0.90), p99=lambda x: x.quantile(0.99))
    stats = stats.reset_index()
    corder = {c: i for i, c in enumerate(WEATHER_CLASSES)}
    if by_band:
        border = {b: i for i, b in enumerate(BAND_ORDER)}
        stats = stats.sort_values(['band', 'cls'],
                                  key=lambda s: s.map(border) if s.name == 'band' else s.map(corder))
    else:
        stats = stats.sort_values('cls', key=lambda s: s.map(corder))
    return stats.round(2)


def per_band_summary(tidy: pd.DataFrame) -> pd.DataFrame:
    """One row per band: #links, freq range, mean link length, and mean
    attenuation in each weather class (the headline 4-band statistics table)."""
    rows = []
    for b in BAND_ORDER:
        d = tidy[tidy['band'] == b]
        if d.empty:
            continue
        means = d.groupby('cls')['attenuation'].mean()
        rows.append(dict(
            band=b, n_links=d['cml_id'].nunique(), n_bins=len(d),
            freq_ghz=f"{d['freq_ghz'].min():.0f}-{d['freq_ghz'].max():.0f}",
            mean_len_m=round(d.groupby('cml_id')['length_m'].first().mean(), 0),
            dry=round(means.get('dry', np.nan), 2), rain=round(means.get('rain', np.nan), 2),
            mix=round(means.get('mix', np.nan), 2), snow=round(means.get('snow', np.nan), 2),
        ))
    return pd.DataFrame(rows)


def per_event_means(tidy: pd.DataFrame) -> pd.DataFrame:
    """Mean attenuation + mean temp per event window (V-band only rows in)."""
    g = tidy.groupby(['event', 'cls']).agg(
        att_mean=('attenuation', 'mean'),
        att_p90=('attenuation', lambda x: x.quantile(0.90)),
        temp=('temp', 'mean'), n=('attenuation', 'count')).reset_index()
    return g[g['event'] != 'none'].round(2)


# ---------------------------------------------------------------------------
# Plotting  (no file output — each returns a Figure for inline display)
# ---------------------------------------------------------------------------
import matplotlib.pyplot as plt

CLASS_COLORS = {'dry': '#7f7f7f', 'rain': '#1f77b4', 'mix': '#9467bd', 'snow': '#d62728',
                'snow_dry': '#2ca02c', 'snow_wet': '#d62728'}
_CLIP = 60.0  # dB display cap for distribution plots (outage tail beyond)
SNOW_SPLIT_CLASSES = ['dry', 'rain', 'snow_dry', 'snow_wet']


def add_snow_phase(tidy: pd.DataFrame, t_dry: float = -2.0,
                   method: str = 'temp') -> pd.DataFrame:
    """Return a copy with a `cls2` column where snow is split into
    'snow_dry' / 'snow_wet'. Other classes are unchanged.

    method='temp'    : split on air temperature  (snow_dry if T <  t_dry)
    method='wetbulb' : split on wet-bulb temp ~0 C (snow_dry if Tw < t_dry);
                       needs a 'dewpoint' column (uses t_dry default ~0 here).
    """
    d = tidy.copy()
    if method == 'wetbulb' and 'dewpoint' in d.columns:
        feat = wet_bulb(d['temp'].values, d['dewpoint'].values)
    else:
        feat = d['temp'].values
    is_snow = (d['cls'] == 'snow').values
    d['cls2'] = d['cls']
    d.loc[is_snow & (feat < t_dry), 'cls2'] = 'snow_dry'
    d.loc[is_snow & (feat >= t_dry), 'cls2'] = 'snow_wet'
    return d


def snow_phase_stats(tidy: pd.DataFrame, band: str = HIGH_FREQ_BAND,
                     t_dry: float = -2.0, method: str = 'temp') -> pd.DataFrame:
    """Mean/median/p90 attenuation for dry vs wet snow (+ rain, dry) on a band."""
    d = add_snow_phase(tidy[tidy['band'] == band], t_dry=t_dry, method=method)
    g = d.groupby('cls2').agg(n=('attenuation', 'size'),
                              mean_A=('attenuation', 'mean'),
                              median_A=('attenuation', 'median'),
                              p90_A=('attenuation', lambda x: x.quantile(0.90)),
                              mean_temp=('temp', 'mean')).reset_index()
    order = {c: i for i, c in enumerate(SNOW_SPLIT_CLASSES + ['mix'])}
    return g.sort_values('cls2', key=lambda s: s.map(order)).round(2)


def _classes_and_col(tidy, snow_split, t_dry, method):
    """Resolve the (dataframe, class-column, class-list) for distribution plots,
    optionally splitting snow into dry/wet."""
    if snow_split:
        return (add_snow_phase(tidy, t_dry=t_dry, method=method),
                'cls2', SNOW_SPLIT_CLASSES)
    return tidy, 'cls', WEATHER_CLASSES


def plot_pdf(tidy: pd.DataFrame, band: str = HIGH_FREQ_BAND, bins=40,
             snow_split: bool = False, t_dry: float = -2.0, method: str = 'temp'):
    """Histogram/PDF of attenuation per weather class for one band.
    snow_split=True splits snow into dry (T<t_dry) and wet (T>=t_dry)."""
    d, col, classes = _classes_and_col(tidy[tidy['band'] == band], snow_split, t_dry, method)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    edges = np.linspace(0, _CLIP, bins + 1)
    for cls in classes:
        a = d.loc[d[col] == cls, 'attenuation'].clip(upper=_CLIP)
        if len(a) < 5:
            continue
        ax.hist(a, bins=edges, density=True, histtype='step', linewidth=2,
                color=CLASS_COLORS[cls], label=f'{cls} (n={len(a)})')
    ax.set_xlabel('Attenuation A = baseline - RSL [dB]')
    ax.set_ylabel('Probability density')
    ttl = f'Attenuation PDF — {band}-band' + (' (snow split dry/wet)' if snow_split else '')
    ax.set_title(ttl)
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def plot_cdf(tidy: pd.DataFrame, band: str = HIGH_FREQ_BAND,
             snow_split: bool = False, t_dry: float = -2.0, method: str = 'temp'):
    """Empirical CDF of attenuation per weather class for one band.
    snow_split=True splits snow into dry (T<t_dry) and wet (T>=t_dry)."""
    d, col, classes = _classes_and_col(tidy[tidy['band'] == band], snow_split, t_dry, method)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for cls in classes:
        a = np.sort(d.loc[d[col] == cls, 'attenuation'].values)
        if len(a) < 5:
            continue
        y = np.arange(1, len(a) + 1) / len(a)
        ax.plot(a, y, linewidth=2, color=CLASS_COLORS[cls], label=f'{cls} (n={len(a)})')
    ax.set_xlim(0, _CLIP)
    ax.set_xlabel('Attenuation A = baseline - RSL [dB]')
    ax.set_ylabel('CDF')
    ttl = f'Attenuation CDF — {band}-band' + (' (snow split dry/wet)' if snow_split else '')
    ax.set_title(ttl)
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def plot_box(tidy: pd.DataFrame, band: str = HIGH_FREQ_BAND):
    """Box plot of attenuation by weather class for one band."""
    d = tidy[tidy['band'] == band]
    data = [d.loc[d['cls'] == c, 'attenuation'].values for c in WEATHER_CLASSES]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    bp = ax.boxplot(data, labels=WEATHER_CLASSES, showfliers=False, patch_artist=True,
                    medianprops=dict(color='black'))
    for patch, c in zip(bp['boxes'], WEATHER_CLASSES):
        patch.set_facecolor(CLASS_COLORS[c]); patch.set_alpha(0.6)
    ax.set_ylabel('Attenuation A [dB]')
    ax.set_title(f'Attenuation by weather class — {band}-band (fliers hidden)')
    ax.grid(alpha=0.3, axis='y')
    fig.tight_layout()
    return fig


def plot_scatter_temp(tidy: pd.DataFrame, band: str = HIGH_FREQ_BAND):
    """Scatter of attenuation vs temperature, colored by weather class."""
    d = tidy[tidy['band'] == band]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for cls in WEATHER_CLASSES:
        s = d[d['cls'] == cls]
        ax.scatter(s['temp'], s['attenuation'].clip(upper=_CLIP), s=8, alpha=0.35,
                   color=CLASS_COLORS[cls], label=cls)
    ax.axvline(2.0, color='k', ls='--', lw=1, label='2 C')
    ax.set_xlabel('Air temperature [C]')
    ax.set_ylabel('Attenuation A [dB]')
    ax.set_title(f'Attenuation vs temperature — {band}-band')
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def plot_band_response(tidy: pd.DataFrame):
    """Mean attenuation per class grouped by band — which band responds to snow."""
    st = per_class_stats(tidy, by_band=True)
    bands = [b for b in BAND_ORDER if b in st['band'].unique()]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(WEATHER_CLASSES)); w = 0.8 / max(1, len(bands))
    for k, b in enumerate(bands):
        sub = st[st['band'] == b].set_index('cls').reindex(WEATHER_CLASSES)
        ax.bar(x + k * w, sub['mean'].values, w, label=f'{b}')
    ax.set_xticks(x + w * (len(bands) - 1) / 2); ax.set_xticklabels(WEATHER_CLASSES)
    ax.set_ylabel('Mean attenuation [dB]')
    ax.set_title('Mean attenuation by weather class and band')
    ax.legend(title='band'); ax.grid(alpha=0.3, axis='y')
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Snow detection (Step 2)
# ---------------------------------------------------------------------------
def attenuation_threshold(tidy: pd.DataFrame, band: str = HIGH_FREQ_BAND,
                          q: float = 0.95) -> float:
    """Precipitation-attenuation threshold = q-quantile of DRY attenuation
    on the given band (above this = an attenuation event, not clear-sky noise)."""
    dry = tidy[(tidy['band'] == band) & (tidy['cls'] == 'dry')]['attenuation']
    return float(dry.quantile(q)) if len(dry) else 1.0


def detect_snow(tidy: pd.DataFrame, band: str = HIGH_FREQ_BAND,
                a_thr: Optional[float] = None, t_thr: float = 2.0) -> pd.DataFrame:
    """Opportunistic snow detector on per-bin V-band rows.

    Rule (signal + co-located temperature, per the paper's methodology):
        attenuation event : A > a_thr  (precipitation present)
        -> snow            : event AND temp < t_thr
        -> rain            : event AND temp >= t_thr
        -> dry             : no event
    Ground truth folds mix/ice into the precip side; we score the snow-vs-rain
    phase call on bins that actually have precipitation.

    Returns a per-bin frame with columns: truth (dry/rain/snow/other),
    pred (dry/rain/snow), plus the inputs.
    """
    if a_thr is None:
        a_thr = attenuation_threshold(tidy, band=band)
    d = tidy[tidy['band'] == band].copy()
    event = d['attenuation'] > a_thr
    pred = np.where(~event, 'dry', np.where(d['temp'] < t_thr, 'snow', 'rain'))
    d['pred'] = pred
    d['a_thr'] = a_thr
    d['t_thr'] = t_thr
    d['truth'] = d['cls'].where(d['cls'].isin(['dry', 'rain', 'snow']), 'other')
    return d


def detection_metrics(det: pd.DataFrame) -> Dict[str, float]:
    """Binary snow-vs-not metrics + phase confusion on precipitation bins."""
    truth_snow = (det['truth'] == 'snow').values
    pred_snow = (det['pred'] == 'snow').values
    tp = int((pred_snow & truth_snow).sum())
    fp = int((pred_snow & ~truth_snow).sum())
    fn = int((~pred_snow & truth_snow).sum())
    tn = int((~pred_snow & ~truth_snow).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    acc = (tp + tn) / len(det) if len(det) else 0.0
    return dict(n=len(det), tp=tp, fp=fp, fn=fn, tn=tn,
                precision=round(prec, 3), recall=round(rec, 3),
                f1=round(f1, 3), accuracy=round(acc, 3))


def precip_metrics(det: pd.DataFrame) -> Dict[str, float]:
    """Phase-agnostic: does A>thr detect *any* precipitation (rain|snow|mix)?"""
    truth_wet = det['cls'].isin(['rain', 'snow', 'mix']).values
    pred_wet = (det['attenuation'] > det['a_thr'].iloc[0]).values
    tp = int((pred_wet & truth_wet).sum()); fp = int((pred_wet & ~truth_wet).sum())
    fn = int((~pred_wet & truth_wet).sum()); tn = int((~pred_wet & ~truth_wet).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return dict(precision=round(prec, 3), recall=round(rec, 3),
                accuracy=round((tp + tn) / len(det), 3), tp=tp, fp=fp, fn=fn, tn=tn)


def sweep_threshold(tidy: pd.DataFrame, band: str = HIGH_FREQ_BAND,
                    t_thr: float = 2.0, n: int = 40) -> pd.DataFrame:
    """Snow precision/recall/F1 as the attenuation threshold varies."""
    d = tidy[tidy['band'] == band]
    hi = d['attenuation'].quantile(0.97)
    rows = []
    for a in np.linspace(0.2, max(hi, 2.0), n):
        det = detect_snow(tidy, band=band, a_thr=float(a), t_thr=t_thr)
        m = detection_metrics(det)
        rows.append(dict(a_thr=round(float(a), 2), precision=m['precision'],
                         recall=m['recall'], f1=m['f1'], accuracy=m['accuracy']))
    return pd.DataFrame(rows)


def plot_threshold_sweep(tidy: pd.DataFrame, band: str = HIGH_FREQ_BAND,
                         t_thr: float = 2.0):
    sw = sweep_threshold(tidy, band=band, t_thr=t_thr)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for col, c in [('precision', 'tab:blue'), ('recall', 'tab:orange'), ('f1', 'tab:green')]:
        ax.plot(sw['a_thr'], sw[col], label=col, color=c, lw=2)
    best = sw.loc[sw['f1'].idxmax()]
    ax.axvline(best['a_thr'], color='k', ls='--', lw=1, label=f"best F1 @ {best['a_thr']} dB")
    ax.set_xlabel(f'{band}-band attenuation threshold [dB]')
    ax.set_ylabel('score'); ax.set_ylim(0, 1.02)
    ax.set_title(f'Snow detection vs threshold (T<{t_thr} C)')
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def confusion(det: pd.DataFrame) -> pd.DataFrame:
    """Truth x Pred confusion table over dry/rain/snow."""
    order = ['dry', 'rain', 'snow']
    t = det[det['truth'].isin(order)]
    return pd.crosstab(t['truth'], t['pred']).reindex(index=order, columns=order, fill_value=0)


def plot_event_detection(tidy: pd.DataFrame, event_name: str,
                         band: str = HIGH_FREQ_BAND, a_thr: Optional[float] = None,
                         t_thr: float = 2.0):
    """Time series of mean V-band attenuation + temperature for one event,
    shading where the detector fires snow."""
    if a_thr is None:
        a_thr = attenuation_threshold(tidy, band=band)
    d = tidy[(tidy['band'] == band) & (tidy['event'] == event_name)]
    if d.empty:
        return None
    g = d.groupby('time').agg(att=('attenuation', 'mean'), temp=('temp', 'first')).sort_index()
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(g.index, g['att'], color=CLASS_COLORS['snow'], lw=1.8, label='mean V-band A')
    ax.axhline(a_thr, color='k', ls='--', lw=1, label=f'A_thr={a_thr:.1f} dB')
    fire = (g['att'] > a_thr) & (g['temp'] < t_thr)
    ax.fill_between(g.index, 0, g['att'].max() * 1.05, where=fire.values, color='red',
                    alpha=0.12, label='snow detected')
    ax2 = ax.twinx()
    ax2.plot(g.index, g['temp'], color='tab:green', lw=1.2, alpha=0.8)
    ax2.axhline(t_thr, color='tab:green', ls=':', lw=1)
    ax2.set_ylabel('Temp [C]', color='tab:green')
    ax.set_ylabel('Attenuation [dB]'); ax.set_xlabel('Time')
    ax.set_title(f'Snow detection — {event_name}')
    ax.legend(loc='upper left'); ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Careful single-link diagnostics + heatmaps (methodology notebook)
# ---------------------------------------------------------------------------
def link_diagnostics(cml_ds: xr.Dataset, ref: pd.DataFrame, cml_id: str,
                     band: str = HIGH_FREQ_BAND, start: str = '2023-11-01',
                     end: str = '2024-04-30', time_res: str = '10min',
                     t_dry: float = -2.0) -> Tuple[dict, pd.DataFrame]:
    """Full per-bin diagnostics for ONE link: raw RSL, dry-median baseline,
    attenuation (dB) and specific attenuation (dB/km), weather class, temp,
    dewpoint, wet-bulb, rainfall, and dry/wet-snow regimes by BOTH temperature
    and wet-bulb. Use this to verify the attenuation pipeline link by link."""
    links = list_links(cml_ds)
    sel = links[(links['cml_id'] == str(cml_id)) & (links['band'] == band)]
    if sel.empty:
        raise ValueError(f'no {band} sublink for cml {cml_id}')
    r = sel.iloc[0]
    times = pd.to_datetime(cml_ds['time'].values)
    rsl = cml_ds['rsl'].isel(cml_id=int(r['i']), sublink_id=int(r['j'])).values
    s = pd.Series(rsl, index=times).dropna()
    s = s[~s.index.duplicated()].sort_index().loc[start:end]
    b = s.resample(time_res).median().dropna()

    df = pd.DataFrame({'rsl': b})
    df['cls'] = ref['cat'].reindex(df.index)
    df['temp'] = ref['temp'].reindex(df.index)
    if 'dewpoint' in ref.columns:
        df['dewpoint'] = ref['dewpoint'].reindex(df.index)
        df['wetbulb'] = wet_bulb(df['temp'].values, df['dewpoint'].values)
    if 'rain' in ref.columns:
        df['rain_mm'] = ref['rain'].reindex(df.index)
    df = df.dropna(subset=['cls'])
    df = df[df['cls'].isin(WEATHER_CLASSES)]

    length_km = float(r['length_m']) / 1000.0
    baseline = df.loc[df['cls'] == 'dry', 'rsl'].median()
    df['baseline'] = baseline
    df['attenuation'] = (baseline - df['rsl']).clip(lower=0)
    df['attenuation_per_km'] = df['attenuation'] / length_km

    # dry/wet snow regimes by temp and (if available) wet-bulb
    df['regime_temp'] = df['cls']
    snow = df['cls'] == 'snow'
    df.loc[snow & (df['temp'] < t_dry), 'regime_temp'] = 'snow_dry'
    df.loc[snow & (df['temp'] >= t_dry), 'regime_temp'] = 'snow_wet'
    if 'wetbulb' in df.columns:
        df['regime_wetbulb'] = df['cls']
        df.loc[snow & (df['wetbulb'] < 0.0), 'regime_wetbulb'] = 'snow_dry'
        df.loc[snow & (df['wetbulb'] >= 0.0), 'regime_wetbulb'] = 'snow_wet'

    info = dict(cml_id=str(cml_id), sublink=str(r['sublink']), band=band,
                freq_ghz=float(r['freq_ghz']), length_km=round(length_km, 2),
                baseline_dBm=round(float(baseline), 2),
                dry_std=round(float(df.loc[df['cls'] == 'dry', 'rsl'].std()), 2),
                n_bins=int(len(df)))
    return info, df


def regime_table(df: pd.DataFrame, regime_col: str = 'regime_temp') -> pd.DataFrame:
    """Per-regime summary (n, median RSL, A dB, A dB/km, temp, wet-bulb) for a
    single-link diagnostics frame."""
    order = ['dry', 'rain', 'mix', 'snow_dry', 'snow_wet']
    agg = dict(n=('attenuation', 'size'), RSL_med=('rsl', 'median'),
               A_dB=('attenuation', 'mean'), A_dB_p90=('attenuation', lambda x: x.quantile(.9)),
               A_per_km=('attenuation_per_km', 'mean'), temp=('temp', 'mean'))
    if 'wetbulb' in df.columns:
        agg['wetbulb'] = ('wetbulb', 'mean')
    g = df.groupby(regime_col).agg(**agg)
    return g.reindex([c for c in order if c in g.index]).round(2)


def plot_link_timeseries(df: pd.DataFrame, info: dict, start, end):
    """Raw RSL + dry baseline over a window, points coloured by weather class."""
    w = df.loc[start:end]
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(w.index, w['rsl'], color='0.6', lw=0.8, zorder=1)
    for cls in WEATHER_CLASSES:
        m = w['cls'] == cls
        ax.scatter(w.index[m], w['rsl'][m], s=12, color=CLASS_COLORS[cls], label=cls, zorder=2)
    ax.axhline(info['baseline_dBm'], color='k', ls='--', lw=1,
               label=f"baseline {info['baseline_dBm']} dBm")
    ax.set_ylabel('RSL [dBm]'); ax.set_xlabel('time')
    ax.set_title(f"cml {info['cml_id']} {info['band']} {info['freq_ghz']} GHz "
                 f"{info['length_km']} km — RSL  ({start} … {end})")
    ax.legend(ncol=5, fontsize=8); ax.grid(alpha=0.3); fig.autofmt_xdate(); fig.tight_layout()
    return fig


def plot_baseline_diagnostic(df: pd.DataFrame, info: dict):
    """Left: RSL histogram by weather class (baseline marked). Right: monthly
    dry-bin median RSL (baseline-drift check)."""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4))
    for cls in WEATHER_CLASSES:
        v = df.loc[df['cls'] == cls, 'rsl']
        if len(v) > 5:
            a1.hist(v, bins=40, density=True, histtype='step', lw=2,
                    color=CLASS_COLORS[cls], label=f'{cls} (n={len(v)})')
    a1.axvline(info['baseline_dBm'], color='k', ls='--', lw=1, label='baseline')
    a1.set_xlabel('RSL [dBm]'); a1.set_ylabel('density'); a1.legend(fontsize=8)
    a1.set_title(f"RSL by class — baseline={info['baseline_dBm']} dBm, dry std={info['dry_std']} dB")
    a1.grid(alpha=0.3)
    dm = df.loc[df['cls'] == 'dry', 'rsl'].resample('MS').median()
    a2.plot(dm.index, dm.values, 'o-', color='k')
    a2.set_ylabel('dry-bin median RSL [dBm]'); a2.set_title('Baseline drift (monthly dry median)')
    a2.grid(alpha=0.3); fig.autofmt_xdate(); fig.tight_layout()
    return fig


def plot_heatmap_regime_band(tidy: pd.DataFrame, value: str = 'attenuation_per_km',
                             t_dry: float = -2.0, method: str = 'temp'):
    """Heatmap of mean attenuation across (regime x band)."""
    d = add_snow_phase(tidy, t_dry=t_dry, method=method)
    rows = ['dry', 'rain', 'mix', 'snow_dry', 'snow_wet']
    cols = [b for b in BAND_ORDER if b in d['band'].unique()]
    M = np.full((len(rows), len(cols)), np.nan)
    for i, rg in enumerate(rows):
        for j, bd in enumerate(cols):
            v = d[(d['cls2'] == rg) & (d['band'] == bd)][value]
            if len(v):
                M[i, j] = v.mean()
    fig, ax = plt.subplots(figsize=(1.6 * len(cols) + 2, 4.5))
    im = ax.imshow(M, aspect='auto', cmap='viridis')
    ax.set_xticks(range(len(cols))); ax.set_xticklabels(cols)
    ax.set_yticks(range(len(rows))); ax.set_yticklabels(rows)
    for i in range(len(rows)):
        for j in range(len(cols)):
            if np.isfinite(M[i, j]):
                ax.text(j, i, f'{M[i, j]:.2f}', ha='center', va='center',
                        color='w' if M[i, j] < np.nanmax(M) * 0.6 else 'k', fontsize=9)
    lab = 'dB/km' if 'per_km' in value else 'dB'
    fig.colorbar(im, ax=ax, label=f'mean attenuation [{lab}]')
    ax.set_title(f'Mean {value} by regime x band ({method} split)')
    fig.tight_layout()
    return fig


def plot_heatmap_temp_att(tidy: pd.DataFrame, band: str = HIGH_FREQ_BAND,
                          tbins=24, abins=24, amax: float = 20.0):
    """2D density heatmap of attenuation vs temperature (shows snow bimodality)."""
    d = tidy[tidy['band'] == band]
    t = d['temp'].values
    a = np.clip(d['attenuation'].values, 0, amax)
    H, xe, ye = np.histogram2d(t, a, bins=[tbins, abins],
                               range=[[np.nanmin(t), np.nanmax(t)], [0, amax]])
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    im = ax.pcolormesh(xe, ye, np.log1p(H.T), cmap='magma')
    ax.axvline(-2, color='c', ls='--', lw=1, label='-2 C (dry/wet snow)')
    ax.axvline(2, color='w', ls=':', lw=1, label='2 C')
    ax.set_xlabel('temperature [C]'); ax.set_ylabel('attenuation [dB]')
    ax.set_title(f'{band}: attenuation vs temperature (log density)')
    fig.colorbar(im, ax=ax, label='log(1+count)'); ax.legend(fontsize=8); fig.tight_layout()
    return fig


def plot_scatter_att_rain(tidy: pd.DataFrame, band: str = HIGH_FREQ_BAND):
    """Scatter of attenuation vs ASOS rainfall, coloured by temperature."""
    d = tidy[(tidy['band'] == band) & (tidy.get('rain_mm', pd.Series(dtype=float)).notna())]
    if 'rain_mm' not in d.columns or d.empty:
        return None
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    sc = ax.scatter(d['rain_mm'], d['attenuation'].clip(upper=_CLIP), c=d['temp'],
                    cmap='coolwarm_r', s=12, alpha=0.6, vmin=-5, vmax=10)
    ax.set_xlabel('ASOS rainfall in 10-min bin [mm]'); ax.set_ylabel('attenuation [dB]')
    ax.set_title(f'{band}: attenuation vs rainfall (colour = temp)')
    fig.colorbar(sc, ax=ax, label='temp [C]'); ax.grid(alpha=0.3); fig.tight_layout()
    return fig
