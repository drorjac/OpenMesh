"""
paper_viz_utils.py
==================
Paper-ready *display* helpers for the snow-sensing sub-study
(`dataset/raw/full/paper/`). Companion to `paper_snow_utils` (imported as `P`):
that module does the science (event detection, attenuation extraction, stats);
this module does the **figures** — the NYC sensor/link map, the event table,
multi-band link detection, and the two-panel "weather (top) + CML response
(bottom)" event figures the paper is built around.

Design (matches the repo): notebook cells stay thin (knobs + one call); every
bit of logic lives here. Figures are returned as Matplotlib Figures and only
written to disk when the caller passes an explicit `out_path`.

Data layout
-----------
* CML : `ds_opensense_cml.nc` — dims (cml_id, sublink_id, time); `rsl` [dBm];
        per-sublink `frequency` [MHz]; per-cml endpoint coords
        site_0_lat/lon, site_1_lat/lon; per-cml `length` [m].
* ASOS: grouped netCDF (one group per station) with per-bin `precip_category`,
        `temperature`, `rainfall_amount`.
* PWS : grouped netCDF (one group per station) with `lat`/`lon`.

Attenuation convention follows `paper_snow_utils`: A(t) = baseline - RSL(t),
clipped >= 0, baseline = clear-sky upper envelope of RSL in the window.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import xarray as xr
import netCDF4 as nc
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

# sibling module (band definitions, link listing, attenuation pipeline)
try:
    from . import paper_snow_utils as P
except ImportError:  # running from a notebook with src/ on the path
    import analysis.paper_snow_utils as P


# ---------------------------------------------------------------------------
# Styling and shared colour maps
# ---------------------------------------------------------------------------
BAND_COLORS = {'sub6': '#1f77b4', 'K': '#2ca02c', 'V60': '#ff7f0e', 'V65': '#d62728'}
BAND_LABEL = {'sub6': 'sub-6 GHz (C)', 'K': 'K-band ~24 GHz',
              'V60': 'V-band ~60 GHz', 'V65': 'V-band 65-70 GHz'}
# light, print-safe weather-phase backgrounds
PHASE_BG = {'dry': '#ffffff', 'rain': '#cfe3ff', 'snow': '#e6dcff',
            'mix': '#d8f0d8', 'ice': '#d8f0d8', 'missing': '#f4f4f4'}
PHASE_LABEL = {'dry': 'Dry', 'rain': 'Rain', 'snow': 'Snow', 'mix': 'Mix', 'missing': 'No data'}

# known NYC-area ASOS coordinates (fallback when a group lacks lat/lon vars)
ASOS_COORDS = {
    'EWR': (40.6895, -74.1745), 'JFK': (40.6386, -73.7622),
    'LGA': (40.7769, -73.8740), 'NYC': (40.7790, -73.9690),
    'TEB': (40.8501, -74.0608),
}


def set_pub_style(base: int = 13):
    """Publication-quality Matplotlib defaults (clean grid, readable fonts)."""
    plt.rcParams.update({
        'figure.dpi': 120, 'savefig.dpi': 200, 'savefig.bbox': 'tight',
        'font.size': base, 'axes.titlesize': base + 1, 'axes.labelsize': base,
        'xtick.labelsize': base - 2, 'ytick.labelsize': base - 2,
        'legend.fontsize': base - 3, 'axes.grid': True, 'grid.alpha': 0.3,
        'grid.linestyle': '--', 'axes.axisbelow': True,
        'axes.spines.top': False, 'axes.spines.right': False,
        'figure.facecolor': 'white', 'axes.facecolor': 'white',
    })


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def lonlat_to_web_mercator(lon, lat) -> Tuple[np.ndarray, np.ndarray]:
    """Spherical Web-Mercator (EPSG:3857) projection — no pyproj needed.
    Lets us drop a contextily basemap under plain lat/lon link geometry."""
    R = 6378137.0
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    x = R * np.radians(lon)
    y = R * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
    return x, y


def _band_rank(b: str) -> int:
    return P.BAND_ORDER.index(b) if b in P.BAND_ORDER else -1


def load_link_geometry(cml_ds: xr.Dataset) -> pd.DataFrame:
    """One row per physical CML path (cml_id): endpoints, length, the set of
    frequency bands carried on that path, and a representative (highest) band.

    A single path can host several sublinks at different frequencies — those
    are the multi-band pairs (see `multiband_pairs`)."""
    ll = P.list_links(cml_ds)  # i, cml_id, sublink, freq_mhz, freq_ghz, band, length_m
    s0lat = np.asarray(cml_ds['site_0_lat'].values).ravel()
    s0lon = np.asarray(cml_ds['site_0_lon'].values).ravel()
    s1lat = np.asarray(cml_ds['site_1_lat'].values).ravel()
    s1lon = np.asarray(cml_ds['site_1_lon'].values).ravel()
    rows = []
    for cid, g in ll.groupby('cml_id'):
        i = int(g['i'].iloc[0])
        bands = sorted(set(g['band']) - {'?'}, key=_band_rank)
        if not bands:
            continue
        rep = bands[-1]  # highest-frequency band present
        rows.append(dict(
            cml_id=str(cid), i=i, n_sublinks=len(g),
            bands=bands, rep_band=rep, n_bands=len(bands),
            freqs_ghz=sorted(round(float(f), 1) for f in set(g['freq_ghz'])),
            length_m=float(g['length_m'].iloc[0]),
            lat0=s0lat[i], lon0=s0lon[i], lat1=s1lat[i], lon1=s1lon[i],
            mid_lat=(s0lat[i] + s1lat[i]) / 2, mid_lon=(s0lon[i] + s1lon[i]) / 2,
        ))
    return pd.DataFrame(rows)


def station_coords(asos_nc, pws_nc=None) -> pd.DataFrame:
    """Station id / lat / lon / type for ASOS (airport) and, if given, PWS."""
    rows = []
    a = nc.Dataset(str(asos_nc))
    for g in a.groups:
        grp = a.groups[g]
        if 'lat' in grp.variables and 'lon' in grp.variables:
            lat = float(np.asarray(grp['lat'][:]).ravel()[0])
            lon = float(np.asarray(grp['lon'][:]).ravel()[0])
        elif g in ASOS_COORDS:
            lat, lon = ASOS_COORDS[g]
        else:
            continue
        rows.append(dict(station=g, lat=lat, lon=lon, kind='ASOS'))
    a.close()
    if pws_nc is not None and Path(pws_nc).exists():
        p = nc.Dataset(str(pws_nc))
        for g in p.groups:
            if g in {r['station'] for r in rows}:
                continue  # airport ICAO already counted as ASOS
            grp = p.groups[g]
            if 'lat' not in grp.variables or 'lon' not in grp.variables:
                continue
            lat = float(np.asarray(grp['lat'][:]).ravel()[0])
            lon = float(np.asarray(grp['lon'][:]).ravel()[0])
            if not (np.isfinite(lat) and np.isfinite(lon)):
                continue
            rows.append(dict(station=g, lat=lat, lon=lon, kind='PWS'))
        p.close()
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Weather window helpers
# ---------------------------------------------------------------------------
def temp_envelope(asos_nc, start, end, freq: str = '10min') -> pd.DataFrame:
    """Per-bin temperature for every ASOS station group over [start, end],
    one column per station. Used to shade the across-station spread."""
    a = nc.Dataset(str(asos_nc))
    cols = {}
    for g in a.groups:
        grp = a.groups[g]
        if 'time' not in grp.variables or 'temperature' not in grp.variables:
            continue
        t = pd.to_datetime(np.array(grp['time'][:]), unit='s', utc=True).tz_convert(None)
        s = pd.Series(np.asarray(grp['temperature'][:]).ravel().astype(float), index=t)
        s = s[~s.index.duplicated()].sort_index().resample(freq).mean()
        cols[g] = s
    a.close()
    df = pd.DataFrame(cols).loc[str(start):str(end)]
    return df


# ---------------------------------------------------------------------------
# Event table + multi-band detection
# ---------------------------------------------------------------------------
def count_active_links(cml_ds: xr.Dataset, start, end) -> int:
    """Number of CML sublinks carrying any finite RSL inside [start, end]
    (chunk-aligned time slice — cheap)."""
    times = pd.to_datetime(cml_ds['time'].values)
    m = (times >= pd.Timestamp(start)) & (times <= pd.Timestamp(end))
    idx = np.where(m)[0]
    if idx.size == 0:
        return 0
    block = cml_ds['rsl'].isel(time=slice(int(idx[0]), int(idx[-1]) + 1)).values
    return int(np.isfinite(block).any(axis=2).sum())


def event_table(cml_ds: xr.Dataset, events: pd.DataFrame) -> pd.DataFrame:
    """Enrich detected events with how many CML sublinks were active in each
    window. Returns a clean, paper-ready table sorted by start time."""
    rows = []
    for _, e in events.iterrows():
        rows.append(dict(
            event=e['name'], cls=e['cls'],
            start=e['start'], end=e['end'], dur_min=int(e['dur_min']),
            t_min_C=e['t_min'], t_max_C=e['t_max'], precip_mm=e['rain_mm'],
            active_links=count_active_links(cml_ds, e['start'], e['end']),
        ))
    out = pd.DataFrame(rows).sort_values('start').reset_index(drop=True)
    return out


def band_inventory(geom: pd.DataFrame) -> pd.DataFrame:
    """Per-band link count, mean length, and bounding-box coverage area."""
    ll_long = geom.explode('bands').rename(columns={'bands': 'band'})
    rows = []
    for b in P.BAND_ORDER:
        d = ll_long[ll_long['band'] == b]
        if d.empty:
            continue
        # rough coverage bbox in km (1 deg lat ~111 km; lon scaled by cos lat)
        lat_span = (d['mid_lat'].max() - d['mid_lat'].min()) * 111.0
        lon_span = (d['mid_lon'].max() - d['mid_lon'].min()) * 111.0 * \
            np.cos(np.radians(d['mid_lat'].mean()))
        rows.append(dict(
            band=b, label=BAND_LABEL[b], n_links=d['cml_id'].nunique(),
            mean_len_m=round(d['length_m'].mean(), 0),
            max_len_m=round(d['length_m'].max(), 0),
            coverage_km2=round(abs(lat_span * lon_span), 1),
        ))
    return pd.DataFrame(rows)


def multiband_pairs(geom: pd.DataFrame) -> pd.DataFrame:
    """Physical paths (cml_id) that carry sublinks in more than one band —
    same geometry, different frequency = a built-in cross-band comparison."""
    d = geom[geom['n_bands'] > 1].copy()
    d = d.sort_values('length_m', ascending=False)
    return d[['cml_id', 'bands', 'freqs_ghz', 'length_m',
              'lat0', 'lon0', 'lat1', 'lon1']].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Link selection for the figures (data-driven, guarantees 69 GHz on V65)
# ---------------------------------------------------------------------------
def _ij_lookup(cml_ds: xr.Dataset) -> pd.DataFrame:
    """(band, cml_id) -> i, j, freq, length for slicing rsl directly."""
    return P.list_links(cml_ds)


def pick_showcase_links(cml_ds: xr.Dataset, ref: pd.DataFrame, events: pd.DataFrame,
                        n_per_band: int = 1, v65_freq_min: float = 68.5,
                        min_bins: int = 40) -> pd.DataFrame:
    """Pick representative *long, well-covered* links per band for the figures.

    For the V65 band we deliberately prefer ~69 GHz links (`v65_freq_min`) so
    the highest-frequency response is actually shown. Returns rows with
    i, j, cml_id, sublink, band, freq_ghz, length_m, n_bins."""
    cand = P.pick_long_links_4band(cml_ds, n_per_band=60, per_cml=1)
    tidy = P.extract_attenuation(cml_ds, cand, ref, events, time_res='10min')
    per = (tidy.groupby(['band', 'cml_id'])
           .agg(freq_ghz=('freq_ghz', 'first'), length_m=('length_m', 'first'),
                n_bins=('attenuation', 'size')).reset_index())
    per = per[per['n_bins'] >= min_bins]
    chosen = []
    for b in P.BAND_ORDER:
        sub = per[per['band'] == b].copy()
        if b == P.HIGH_FREQ_BAND:
            hi = sub[sub['freq_ghz'] >= v65_freq_min]
            sub = hi if not hi.empty else sub
        sub = sub.sort_values('length_m', ascending=False).head(n_per_band)
        chosen.append(sub)
    chosen = pd.concat(chosen, ignore_index=True)
    # attach i, j via the link list
    ll = _ij_lookup(cml_ds)
    key = ll.drop_duplicates(['band', 'cml_id'])[['band', 'cml_id', 'i', 'j', 'sublink']]
    out = chosen.merge(key, on=['band', 'cml_id'], how='left')
    out['band'] = pd.Categorical(out['band'], P.BAND_ORDER, ordered=True)
    return out.sort_values('band').reset_index(drop=True)


def links_for_cml(cml_ds: xr.Dataset, cml_id: str) -> pd.DataFrame:
    """All sublinks (one per band) for a single physical path — for the
    same-path multi-band comparison (e.g. cml 16: 5.5 GHz vs 69 GHz)."""
    ll = _ij_lookup(cml_ds)
    d = ll[ll['cml_id'] == str(cml_id)].drop_duplicates('band')
    d['band'] = pd.Categorical(d['band'], P.BAND_ORDER, ordered=True)
    return d.sort_values('band').reset_index(drop=True)


# ---------------------------------------------------------------------------
# RSL / attenuation extraction over a single event window
# ---------------------------------------------------------------------------
def event_link_signals(cml_ds: xr.Dataset, links: pd.DataFrame, start, end,
                       pad_h: float = 6.0, time_res: str = '10min',
                       baseline_q: float = 0.90) -> Tuple[Dict[str, pd.DataFrame], Tuple]:
    """Per-link RSL + attenuation over [start-pad, end+pad].

    Baseline = clear-sky upper envelope (`baseline_q` quantile of in-window
    RSL); A = baseline - RSL, clipped >= 0. Returns {label: frame(rsl, att)}
    keyed by a human label, plus the padded (a, b) window actually read."""
    times = pd.to_datetime(cml_ds['time'].values)
    a = pd.Timestamp(start) - pd.Timedelta(hours=pad_h)
    b = pd.Timestamp(end) + pd.Timedelta(hours=pad_h)
    m = (times >= a) & (times <= b)
    idx = np.where(m)[0]
    out: Dict[str, pd.DataFrame] = {}
    if idx.size == 0:
        return out, (a, b)
    s0, s1 = int(idx[0]), int(idx[-1]) + 1
    block = cml_ds['rsl'].isel(time=slice(s0, s1)).values     # (cml, sublink, n)
    tt = times[s0:s1]
    for r in links.itertuples():
        v = block[int(r.i), int(r.j)]
        s = pd.Series(v, index=tt).dropna()
        if s.empty:
            continue
        s = s[~s.index.duplicated()].resample(time_res).median().dropna()
        if s.empty:
            continue
        baseline = float(s.quantile(baseline_q))
        att = (baseline - s).clip(lower=0)
        label = f"cml {r.cml_id} · {float(r.freq_ghz):.0f} GHz ({r.band})"
        out[label] = pd.DataFrame({'rsl': s, 'att': att,
                                   'baseline': baseline}).assign(
            band=str(r.band), cml_id=str(r.cml_id), freq_ghz=float(r.freq_ghz),
            length_m=float(getattr(r, 'length_m', np.nan)))
    return out, (a, b)


# ---------------------------------------------------------------------------
# Drawing primitives (shared by single-event and grid figures)
# ---------------------------------------------------------------------------
def _phase_runs(cat: pd.Series):
    """Yield (start, end, phase) contiguous runs of a category series."""
    if cat.empty:
        return
    vals = cat.values
    idx = cat.index
    i, n = 0, len(vals)
    while i < n:
        j = i
        while j < n and vals[j] == vals[i]:
            j += 1
        yield idx[i], idx[min(j, n - 1)], vals[i]
        i = j


def draw_weather_panel(ax, ref_w: pd.DataFrame, temp_env_w: Optional[pd.DataFrame],
                       title: Optional[str] = None, show_ylabels: bool = True):
    """TOP panel: phase-coloured background + precip bars (left axis) +
    temperature line with across-station spread (right axis)."""
    # 1) phase background spans
    for a, b, ph in _phase_runs(ref_w['cat']):
        ax.axvspan(a, b, color=PHASE_BG.get(ph, '#f4f4f4'), alpha=0.85, lw=0, zorder=0)
    # 2) precipitation bars (mm per bin)
    if 'rain' in ref_w.columns:
        wbar = (ref_w.index[1] - ref_w.index[0]) / np.timedelta64(1, 'D') if len(ref_w) > 1 else 0.006
        ax.bar(ref_w.index, ref_w['rain'].fillna(0), width=wbar * 0.95,
               color='#1f6fb2', alpha=0.85, zorder=2, label='Precip [mm/bin]')
    ax.set_ylim(bottom=0)
    if show_ylabels:
        ax.set_ylabel('Precip [mm/bin]', color='#1f6fb2')
    ax.tick_params(axis='y', colors='#1f6fb2')
    ax.margins(x=0)
    # 3) temperature on a twin axis (+ across-station spread)
    axt = ax.twinx()
    axt.grid(False)
    if temp_env_w is not None and not temp_env_w.empty:
        lo = temp_env_w.min(axis=1)
        hi = temp_env_w.max(axis=1)
        axt.fill_between(temp_env_w.index, lo, hi, color='#d62728', alpha=0.15, lw=0,
                         zorder=1, label='Temp spread (stations)')
    axt.plot(ref_w.index, ref_w['temp'], color='#d62728', lw=1.8, zorder=3,
             label='Temp [°C]')
    axt.axhline(0, color='#d62728', ls=':', lw=1, alpha=0.7, zorder=1)
    if show_ylabels:
        axt.set_ylabel('Temp [°C]', color='#d62728')
    axt.tick_params(axis='y', colors='#d62728')
    if title:
        ax.set_title(title)
    return axt


def _annotate_signal(ax, df_all: pd.DataFrame, ref_w: pd.DataFrame):
    """Light, data-driven annotations: cold-dry-snow stretch and the
    attenuation peak. Only drawn when the data actually supports them."""
    if df_all.empty:
        return
    mean_att = df_all.groupby(level=0)['att'].mean()
    if mean_att.empty:
        return
    # peak attenuation
    pk = mean_att.idxmax()
    pky = float(mean_att.loc[pk])
    if pky > 1.0:
        ax.annotate(f'peak ≈ {pky:.0f} dB', xy=(pk, pky),
                    xytext=(0, 18), textcoords='offset points', ha='center',
                    fontsize=9, color='black',
                    arrowprops=dict(arrowstyle='->', color='black', lw=1))
    # coldest snow stretch -> "dry snow"
    if 'cat' in ref_w.columns and 'temp' in ref_w.columns:
        cold_snow = ref_w[(ref_w['cat'] == 'snow') & (ref_w['temp'] < -2.0)]
        if len(cold_snow) >= 3:
            c = cold_snow.index[len(cold_snow) // 2]
            ax.annotate('dry snow (T < −2 °C)', xy=(c, mean_att.max() * 0.15),
                        xytext=(0, 0), textcoords='offset points', ha='center',
                        fontsize=9, style='italic', color='#555555')


def draw_rsl_panel(ax, signals: Dict[str, pd.DataFrame], ref_w: pd.DataFrame,
                   metric: str = 'att', show_ylabels: bool = True,
                   annotate: bool = True):
    """BOTTOM panel: per-link attenuation (or RSL), coloured by band, labelled
    by cml id + frequency, with light annotations."""
    # phase background (faint) for visual alignment with the top panel
    for a, b, ph in _phase_runs(ref_w['cat']):
        ax.axvspan(a, b, color=PHASE_BG.get(ph, '#f4f4f4'), alpha=0.5, lw=0, zorder=0)
    rows = []
    for label, df in signals.items():
        band = df['band'].iloc[0]
        ax.plot(df.index, df[metric], lw=1.6, color=BAND_COLORS.get(band, '#333333'),
                label=label, zorder=3, alpha=0.9)
        rows.append(df[[metric]].rename(columns={metric: 'att'}))
    if rows and annotate:
        _annotate_signal(ax, pd.concat(rows), ref_w)
    if show_ylabels:
        ax.set_ylabel('Attenuation A [dB]' if metric == 'att' else 'RSL [dBm]')
    if metric == 'att':
        ax.set_ylim(bottom=0)
    ax.margins(x=0)
    ax.legend(loc='upper left', framealpha=0.9, ncol=1)


def _phase_legend_handles():
    return [Patch(facecolor=PHASE_BG[k], edgecolor='0.6', label=PHASE_LABEL[k])
            for k in ['dry', 'rain', 'snow', 'mix']]


def _format_time_axis(ax):
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    for t in ax.get_xticklabels():
        t.set_rotation(0)
        t.set_ha('center')


# ---------------------------------------------------------------------------
# Top-level event figures
# ---------------------------------------------------------------------------
def plot_event_weather_rsl(cml_ds: xr.Dataset, ref: pd.DataFrame,
                           temp_env: Optional[pd.DataFrame], links: pd.DataFrame,
                           event: pd.Series, pad_h: float = 6.0,
                           metric: str = 'att', out_path: Optional[Path] = None):
    """Single-event, two-panel paper figure: weather (top) + CML response
    (bottom), sharing the time axis. Saves to `out_path` if given."""
    signals, (a, b) = event_link_signals(cml_ds, links, event['start'], event['end'],
                                          pad_h=pad_h)
    ref_w = ref.loc[a:b]
    tenv_w = temp_env.loc[a:b] if temp_env is not None else None

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7.2), sharex=True,
                                   gridspec_kw=dict(height_ratios=[1, 1.1], hspace=0.08))
    ttl = (f"{event['cls'].upper()} event — {pd.Timestamp(event['start']):%Y-%m-%d %H:%M}"
           f"  (T {event['t_min']:.1f}…{event['t_max']:.1f} °C, {event['rain_mm']:.1f} mm)")
    axt = draw_weather_panel(ax1, ref_w, tenv_w, title=ttl)
    # merged weather legend
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = axt.get_legend_handles_labels()
    ax1.legend(h1 + h2 + _phase_legend_handles(), l1 + l2 + [p.get_label() for p in _phase_legend_handles()],
               loc='upper left', ncol=3, framealpha=0.9)

    draw_rsl_panel(ax2, signals, ref_w, metric=metric)
    ax2.set_xlabel('Time (UTC)')
    _format_time_axis(ax2)
    ax2.set_xlim(a, b)
    if out_path is not None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path)
        print(f"  saved -> {out_path}")
    return fig


def plot_events_grid(cml_ds: xr.Dataset, ref: pd.DataFrame,
                     temp_env: Optional[pd.DataFrame], links: pd.DataFrame,
                     events_subset: pd.DataFrame, pad_h: float = 6.0,
                     metric: str = 'att', out_path: Optional[Path] = None):
    """Several events side by side (columns), weather over CML response — the
    multi-panel layout used in the paper figures."""
    n = len(events_subset)
    fig, axes = plt.subplots(2, n, figsize=(6.2 * n, 7.4), sharex='col',
                             gridspec_kw=dict(height_ratios=[1, 1.1], hspace=0.09, wspace=0.28))
    if n == 1:
        axes = axes.reshape(2, 1)
    for k, (_, ev) in enumerate(events_subset.iterrows()):
        signals, (a, b) = event_link_signals(cml_ds, links, ev['start'], ev['end'], pad_h=pad_h)
        ref_w = ref.loc[a:b]
        tenv_w = temp_env.loc[a:b] if temp_env is not None else None
        ttl = f"{ev['cls'].upper()} · {pd.Timestamp(ev['start']):%Y-%m-%d}"
        axt = draw_weather_panel(axes[0, k], ref_w, tenv_w, title=ttl,
                                 show_ylabels=(k == 0))
        if k != 0:
            axt.set_ylabel('')
        draw_rsl_panel(axes[1, k], signals, ref_w, metric=metric,
                       show_ylabels=(k == 0))
        axes[1, k].set_xlabel('Time (UTC)')
        axes[1, k].set_xlim(a, b)
        _format_time_axis(axes[1, k])
    fig.suptitle('Weather (top) vs CML response (bottom) — sampled events', y=0.995,
                 fontsize=15)
    if out_path is not None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path)
        print(f"  saved -> {out_path}")
    return fig


def plot_multiband_comparison(cml_ds: xr.Dataset, ref: pd.DataFrame,
                              temp_env: Optional[pd.DataFrame],
                              band_links: Dict[str, pd.DataFrame], event: pd.Series,
                              pad_h: float = 6.0, same_path_cml: Optional[str] = None,
                              out_path: Optional[Path] = None):
    """One snow event: shared weather panel on top, then one attenuation
    sub-panel per band, so the reader sees how response grows with frequency.
    If `same_path_cml` is given, its band-pair is highlighted as the cleanest
    apples-to-apples (identical geometry, different frequency) comparison."""
    bands = [b for b in P.BAND_ORDER if b in band_links and not band_links[b].empty]
    nrow = 1 + len(bands)
    fig, axes = plt.subplots(nrow, 1, figsize=(11, 2.6 * nrow), sharex=True,
                             gridspec_kw=dict(hspace=0.12))
    a = pd.Timestamp(event['start']) - pd.Timedelta(hours=pad_h)
    b_ = pd.Timestamp(event['end']) + pd.Timedelta(hours=pad_h)
    ref_w = ref.loc[a:b_]
    tenv_w = temp_env.loc[a:b_] if temp_env is not None else None

    ttl = (f"Multi-band response — {event['cls'].upper()} "
           f"{pd.Timestamp(event['start']):%Y-%m-%d %H:%M}")
    axt = draw_weather_panel(axes[0], ref_w, tenv_w, title=ttl)
    h1, l1 = axes[0].get_legend_handles_labels()
    h2, l2 = axt.get_legend_handles_labels()
    axes[0].legend(h1 + h2 + _phase_legend_handles(),
                   l1 + l2 + [p.get_label() for p in _phase_legend_handles()],
                   loc='upper left', ncol=3, framealpha=0.9)

    for ax, band in zip(axes[1:], bands):
        signals, _ = event_link_signals(cml_ds, band_links[band], event['start'],
                                         event['end'], pad_h=pad_h)
        draw_rsl_panel(ax, signals, ref_w, metric='att', annotate=False)
        ax.set_title(f"{BAND_LABEL[band]}", fontsize=11, loc='left', color=BAND_COLORS[band])
    axes[-1].set_xlabel('Time (UTC)')
    axes[-1].set_xlim(a, b_)
    _format_time_axis(axes[-1])
    if out_path is not None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path)
        print(f"  saved -> {out_path}")
    return fig


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
def plot_sensor_link_map(geom: pd.DataFrame, stations: pd.DataFrame,
                         out_path: Optional[Path] = None, basemap: bool = True,
                         title: str = 'NYC Mesh CML links + weather stations'):
    """Paper-ready map: CML paths coloured by (highest) frequency band, ASOS
    airport stations (triangles) and PWS stations (dots), optional OSM/Carto
    basemap. Falls back gracefully to a clean no-basemap map when offline."""
    fig, ax = plt.subplots(figsize=(10, 10))

    # links (in Web-Mercator so a basemap can slot underneath)
    for b in P.BAND_ORDER:
        d = geom[geom['rep_band'] == b]
        first = True
        for _, r in d.iterrows():
            x, y = lonlat_to_web_mercator([r['lon0'], r['lon1']], [r['lat0'], r['lat1']])
            ax.plot(x, y, color=BAND_COLORS[b], lw=1.8, alpha=0.85, solid_capstyle='round',
                    zorder=4, label=BAND_LABEL[b] if first else None)
            first = False
    # highlight multi-band paths
    multi = geom[geom['n_bands'] > 1]
    for _, r in multi.iterrows():
        x, y = lonlat_to_web_mercator([r['lon0'], r['lon1']], [r['lat0'], r['lat1']])
        ax.plot(x, y, color='black', lw=3.2, alpha=0.9, zorder=3)
        mx, my = lonlat_to_web_mercator([r['mid_lon']], [r['mid_lat']])
        ax.annotate(f"cml {r['cml_id']}", (mx[0], my[0]), fontsize=8, zorder=7,
                    ha='center', va='bottom', color='black',
                    bbox=dict(boxstyle='round,pad=0.15', fc='white', ec='none', alpha=0.7))

    # stations
    for kind, marker, color, size in [('PWS', 'o', '#3a7d44', 36),
                                      ('ASOS', '^', '#000000', 130)]:
        s = stations[stations['kind'] == kind]
        if s.empty:
            continue
        sx, sy = lonlat_to_web_mercator(s['lon'].values, s['lat'].values)
        ax.scatter(sx, sy, marker=marker, s=size, c=color, edgecolors='white',
                   linewidths=0.6, zorder=6, label=f'{kind} stations ({len(s)})')
        if kind == 'ASOS':
            for (_, r), xx, yy in zip(s.iterrows(), sx, sy):
                ax.annotate(r['station'], (xx, yy), fontsize=10, fontweight='bold',
                            zorder=8, ha='left', va='bottom')

    used = False
    if basemap:
        try:
            import contextily as cx
            cx.add_basemap(ax, source=cx.providers.CartoDB.Positron, attribution=False)
            used = True
        except Exception as e:
            print(f"  [map] basemap skipped ({type(e).__name__}: {e}) — drawing without it")
    ax.set_axis_off() if used else ax.ticklabel_format(style='plain', useOffset=False)
    ax.set_aspect('equal')

    # legend: bands + station kinds + multi-band marker
    band_handles = [Line2D([0], [0], color=BAND_COLORS[b], lw=2.5, label=BAND_LABEL[b])
                    for b in P.BAND_ORDER if (geom['rep_band'] == b).any()]
    extra = [Line2D([0], [0], color='black', lw=3.2, label='multi-band path'),
             Line2D([0], [0], marker='^', color='w', markerfacecolor='k', markersize=11,
                    label=f"ASOS ({(stations['kind']=='ASOS').sum()})"),
             Line2D([0], [0], marker='o', color='w', markerfacecolor='#3a7d44', markersize=9,
                    label=f"PWS ({(stations['kind']=='PWS').sum()})")]
    ax.legend(handles=band_handles + extra, loc='upper left', framealpha=0.92,
              title='frequency band / sensor')
    ax.set_title(title)
    fig.tight_layout()
    if out_path is not None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path)
        print(f"  saved -> {out_path}")
    return fig
