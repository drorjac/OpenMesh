"""
Reusable plotting + comparison helpers for multi-network rainfall data.

Designed to work with the dict-of-Dataset shape returned by
`netcdf_utils.load_pws_grouped`. A network is a `{station_id: xr.Dataset}`
dict; a comparison passes several such dicts under labels:

    networks = {'ASOS': asos_dict, 'WU PWS (QC)': pws_clean, 'Mesonet': meso_dict}

Functions:
    network_hourly_rain   — DataFrame of hourly rainfall (rows=hours, cols=stations)
    station_locations     — DataFrame of (station, lat, lon) per network
    station_map_folium    — interactive NYC map of all stations colored by network
    plot_accumulation     — per-network cumulative: thin per-station + bold median
    plot_overlay          — median-cumulative overlay across networks + normalized shape
    plot_event_zoom       — zoom into ±N days around a rain event for all networks
    plot_daily_heatmap    — daily mm per station as a heatmap (one network)
"""

from __future__ import annotations

from typing import Dict, Iterable

import numpy as np
import pandas as pd
import xarray as xr

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Patch


# ---------------------------------------------------------------------------
# Data shaping
# ---------------------------------------------------------------------------

def network_resample(
    net_dict: Dict[str, xr.Dataset],
    var: str = 'rainfall_amount',
    freq: str = '1h',
    agg: str = 'sum',
) -> pd.DataFrame:
    """Resample a per-station variable to a common grid.

    Parameters
    ----------
    net_dict : {sid: xr.Dataset}
    var      : variable name (e.g. 'rainfall_amount', 'temperature', 'snow_depth')
    freq     : pandas offset alias — '5min', '10min', '30min', '1h', '1D', etc.
    agg      : 'sum' (totals, e.g. rainfall) or 'mean' (intensive, e.g. temperature)

    Returns
    -------
    DataFrame with rows = `freq` timestamps, cols = stations, values = resampled values.

    Note on cadence vs native sampling:
        ASOS native ≈ 1 min, Mesonet ≈ 5 min, WU PWS ≈ 1 h. Picking a `freq`
        finer than a network's native cadence will leave that network's
        resampled bins mostly empty / NaN. For cross-network plots, pick
        the slowest network's cadence (1 h) or accept the sparseness.
    """
    cols = {}
    for sid, ds in net_dict.items():
        if var not in ds:
            continue
        s = ds[var].squeeze(drop=True).to_series()
        s.index = pd.to_datetime(s.index)
        rs = s.resample(freq)
        if agg == 'sum':
            cols[sid] = rs.sum(min_count=1)
        elif agg == 'mean':
            cols[sid] = rs.mean()
        elif agg == 'max':
            cols[sid] = rs.max()
        elif agg == 'last':
            cols[sid] = rs.last()
        else:
            raise ValueError(f"agg must be one of sum/mean/max/last, got {agg!r}")
    return pd.concat(cols, axis=1) if cols else pd.DataFrame()


def network_hourly_rain(
    net_dict: Dict[str, xr.Dataset],
    var: str = 'rainfall_amount',
) -> pd.DataFrame:
    """Legacy alias — hourly rainfall (mm). Equivalent to
    `network_resample(net_dict, var, freq='1h', agg='sum')`."""
    return network_resample(net_dict, var=var, freq='1h', agg='sum')


def _xy(ds: xr.Dataset):
    for spot in (ds.coords, ds.data_vars):
        if 'lat' in spot and 'lon' in spot:
            return (float(spot['lat'].values.flat[0]),
                    float(spot['lon'].values.flat[0]))
    return (None, None)


def station_locations(net_dict: Dict[str, xr.Dataset]) -> pd.DataFrame:
    """One row per station with valid coordinates."""
    rows = []
    for sid, ds in net_dict.items():
        lat, lon = _xy(ds)
        if lat is None or np.isnan(lat) or np.isnan(lon):
            continue
        rows.append({'station': sid, 'lat': lat, 'lon': lon})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------

# Default per-network colours (matplotlib + folium compatible hex)
DEFAULT_COLORS = {
    'ASOS'        : '#1f77b4',
    'WU PWS'      : '#ff7f0e',
    'WU PWS (QC)' : '#ff7f0e',
    'Mesonet'     : '#2ca02c',
    'WU as_is'    : '#2ca02c',
    'WU diff'     : '#17becf',
    'WU asos'     : '#9467bd',
    'WU dropped'  : '#d62728',
}


def filter_stations_by_bbox(
    net_dict: Dict[str, xr.Dataset],
    lat_range: tuple,
    lon_range: tuple,
) -> Dict[str, xr.Dataset]:
    """Return {sid: ds} for stations whose lat/lon fall inside the box.

    `lat_range` / `lon_range` are (min, max) tuples in degrees WGS84.
    """
    out = {}
    for sid, ds in net_dict.items():
        lat, lon = _xy(ds)
        if lat is None or np.isnan(lat) or np.isnan(lon):
            continue
        if lat_range[0] <= lat <= lat_range[1] and lon_range[0] <= lon <= lon_range[1]:
            out[sid] = ds
    return out


def station_map_folium(
    networks: Dict[str, Dict[str, xr.Dataset]],
    colors: Dict[str, str] | None = None,
    zoom_start: int = 11,
    label_stations: bool = False,
    highlight: Dict[str, set] | None = None,
):
    """Render every station from every network on a real NYC OpenStreetMap basemap.

    Markers are colored per network; popup shows the station ID.
    Requires `folium` (already installed).
    """
    import folium
    colors = {**DEFAULT_COLORS, **(colors or {})}

    # Collect all locations to compute the center
    all_pts = []
    for net_name, net in networks.items():
        loc = station_locations(net)
        loc['network'] = net_name
        all_pts.append(loc)
    df = pd.concat(all_pts, ignore_index=True) if all_pts else pd.DataFrame()
    if df.empty:
        raise ValueError('No stations with coordinates in any network.')

    center = [df['lat'].mean(), df['lon'].mean()]
    m = folium.Map(location=center, zoom_start=zoom_start, tiles='OpenStreetMap')

    highlight = highlight or {}
    for net_name, sub in df.groupby('network'):
        color = colors.get(net_name, '#666666')
        hi_set = highlight.get(net_name, set())
        layer = folium.FeatureGroup(name=f'{net_name} ({len(sub)})')
        for _, row in sub.iterrows():
            is_hi = row['station'] in hi_set
            folium.CircleMarker(
                location=[row['lat'], row['lon']],
                radius=8 if is_hi else 5,
                color='black' if is_hi else color,
                weight=2 if is_hi else 1,
                fill=True,
                fill_color='yellow' if is_hi else color,
                fill_opacity=0.9 if is_hi else 0.8,
                popup=folium.Popup(f"<b>{net_name}</b><br>{row['station']}<br>"
                                   f"lat={row['lat']:.4f}, lon={row['lon']:.4f}",
                                   max_width=220),
                tooltip=row['station'],
            ).add_to(layer)
            if label_stations:
                folium.Marker(
                    location=[row['lat'], row['lon']],
                    icon=folium.DivIcon(
                        icon_size=(120, 12), icon_anchor=(-6, 6),
                        html=f'<div style="font-size:9px;color:{color};'
                             'text-shadow:0 0 2px white;">'
                             f'{row["station"]}</div>'),
                ).add_to(layer)
        layer.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    return m


def station_map_static(
    networks: Dict[str, Dict[str, xr.Dataset]],
    ax: plt.Axes | None = None,
    colors: Dict[str, str] | None = None,
    basemap: bool = True,
    basemap_zoom: int | str = 'auto',
    margin_deg: float = 0.05,
) -> plt.Axes:
    """Matplotlib scatter of station locations on a real OpenStreetMap basemap.

    Uses `contextily` to fetch OSM tiles. Set `basemap=False` to skip the
    basemap (e.g. if you're offline).
    """
    colors = {**DEFAULT_COLORS, **(colors or {})}
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 10))

    all_lats, all_lons = [], []
    for net_name, net in networks.items():
        loc = station_locations(net)
        if loc.empty:
            continue
        ax.scatter(loc['lon'], loc['lat'], s=55, alpha=0.85,
                   color=colors.get(net_name, '#666'),
                   edgecolor='black', linewidth=0.6,
                   zorder=5,
                   label=f'{net_name} ({len(loc)})')
        all_lats.extend(loc['lat']); all_lons.extend(loc['lon'])

    if all_lats:
        ax.set_xlim(min(all_lons) - margin_deg, max(all_lons) + margin_deg)
        ax.set_ylim(min(all_lats) - margin_deg, max(all_lats) + margin_deg)

    if basemap:
        try:
            import contextily as cx
            cx.add_basemap(ax, crs='EPSG:4326',
                           source=cx.providers.OpenStreetMap.Mapnik,
                           zoom=basemap_zoom)
        except Exception as e:
            print(f'  (contextily basemap skipped: {e})')

    ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude'); ax.set_aspect('equal')
    ax.grid(True, alpha=0.3, zorder=1)
    ax.legend(loc='upper left', framealpha=0.9)
    return ax


# ---------------------------------------------------------------------------
# Accumulation plots
# ---------------------------------------------------------------------------

def plot_accumulation(
    networks: Dict[str, pd.DataFrame],
    figsize: tuple = (14, 3 + 0),
    colors: Dict[str, str] | None = None,
) -> plt.Figure:
    """One panel per network. Thin lines = per-station cumulative; thick
    black = median across stations. Title includes mean and median end-totals.
    `networks` here are HOURLY DataFrames (output of `network_hourly_rain`).
    """
    colors = {**DEFAULT_COLORS, **(colors or {})}
    n = len(networks)
    fig, axes = plt.subplots(n, 1, figsize=(figsize[0], 3 * n), sharex=True)
    if n == 1:
        axes = [axes]
    for ax, (name, df) in zip(axes, networks.items()):
        if df.empty:
            ax.text(0.5, 0.5, f'{name}: empty', transform=ax.transAxes, ha='center')
            continue
        c = colors.get(name, '#666')
        cum = df.fillna(0).cumsum()
        for sid in cum.columns:
            ax.plot(cum.index, cum[sid], lw=0.7, alpha=0.35, color=c)
        med = cum.median(axis=1)
        mean = cum.mean(axis=1)
        ax.plot(cum.index, med, lw=2.0, color='black',
                label=f'median across {cum.shape[1]} stations (end={med.iloc[-1]:.0f} mm)')
        ax.plot(cum.index, mean, lw=1.5, color='red', ls='--',
                label=f'mean (end={mean.iloc[-1]:.0f} mm)')
        ax.set_ylabel(f'{name}\ncumulative mm')
        ax.set_title(f'{name} — {cum.shape[1]} stations')
        ax.grid(True, alpha=0.3); ax.legend(loc='upper left', fontsize=9)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    axes[-1].xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    for lab in axes[-1].get_xticklabels():
        lab.set_rotation(30)
    plt.tight_layout()
    return fig


def plot_overlay(
    networks: Dict[str, pd.DataFrame],
    colors: Dict[str, str] | None = None,
) -> plt.Figure:
    """Side-by-side: absolute cumulative (median + mean) vs normalized shape."""
    colors = {**DEFAULT_COLORS, **(colors or {})}
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 4.5))
    for name, df in networks.items():
        if df.empty:
            continue
        c = colors.get(name, '#666')
        cum_med = df.median(axis=1).fillna(0).cumsum()
        cum_mean = df.mean(axis=1).fillna(0).cumsum()
        ax1.plot(cum_med.index, cum_med, lw=1.7, color=c,
                 label=f'{name} median (end={cum_med.iloc[-1]:.0f} mm)')
        ax1.plot(cum_mean.index, cum_mean, lw=1.0, color=c, ls=':',
                 label=f'{name} mean   (end={cum_mean.iloc[-1]:.0f} mm)')
        end = cum_med.iloc[-1]
        if end > 0:
            ax2.plot(cum_med.index, 100 * cum_med / end, lw=1.7, color=c, label=name)
    for ax, ttl, ylab in [
        (ax1, 'Cumulative rainfall — median (solid) and mean (dotted) per network',
              'cumulative mm'),
        (ax2, 'Normalized shape — % of end-of-window total (median)',
              '% of end-of-window total'),
    ]:
        ax.set_title(ttl); ax.set_ylabel(ylab)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
        ax.grid(True, alpha=0.3); ax.legend(loc='upper left', fontsize=9)
        for lab in ax.get_xticklabels():
            lab.set_rotation(30)
    plt.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Event zoom
# ---------------------------------------------------------------------------

def plot_event_zoom(
    networks: Dict[str, pd.DataFrame],
    event_day: pd.Timestamp,
    span_days: int = 2,
    colors: Dict[str, str] | None = None,
) -> plt.Figure:
    """Hourly rainfall around `event_day`, for every network: median + 25-75% envelope."""
    colors = {**DEFAULT_COLORS, **(colors or {})}
    win0 = event_day - pd.Timedelta(days=span_days)
    win1 = event_day + pd.Timedelta(days=span_days)
    fig, ax = plt.subplots(figsize=(13, 4))
    for name, df in networks.items():
        if df.empty:
            continue
        c = colors.get(name, '#666')
        sub = df.loc[win0:win1]
        if sub.empty:
            continue
        med = sub.median(axis=1)
        lo, hi = sub.quantile(0.25, axis=1), sub.quantile(0.75, axis=1)
        ax.fill_between(sub.index, lo, hi, color=c, alpha=0.18)
        ax.plot(med.index, med, color=c, lw=1.6,
                label=f'{name} median of {sub.shape[1]}')
    ax.axvspan(event_day, event_day + pd.Timedelta(days=1),
               color='red', alpha=0.06, label='event day')
    ax.set_ylabel('hourly rainfall (mm)')
    ax.set_title(f'Rain event — {event_day.date()}')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %Hh'))
    for lab in ax.get_xticklabels():
        lab.set_rotation(30)
    ax.grid(True, alpha=0.3); ax.legend(loc='upper right', fontsize=9)
    plt.tight_layout()
    return fig


def plot_event_qc_compare(
    asos_h: pd.DataFrame,
    pws_raw_h: pd.DataFrame,
    pws_qc_h: pd.DataFrame,
    meso_h: pd.DataFrame | None,
    event_day: pd.Timestamp,
    span_days: int = 2,
    colors: Dict[str, str] | None = None,
) -> plt.Figure:
    """Two-panel event zoom: WU before/after QC + cross-network with QC'd WU.

    Top panel:    WU PWS RAW median (own y-axis — usually huge) + ASOS for scale.
    Bottom panel: ASOS + WU PWS (QC) + Mesonet on a shared, realistic scale.
    """
    colors = {**DEFAULT_COLORS, **(colors or {})}
    win0 = event_day - pd.Timedelta(days=span_days)
    win1 = event_day + pd.Timedelta(days=span_days)

    fig, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(13, 7), sharex=True)

    # --- Top: WU RAW vs WU QC (twin-axis so RAW doesn't crush QC visually) ---
    raw_sub = pws_raw_h.loc[win0:win1]
    qc_sub  = pws_qc_h.loc[win0:win1]
    if not raw_sub.empty:
        ax_top.plot(raw_sub.index, raw_sub.median(axis=1), color='#888', lw=1.4,
                    label=f'WU RAW median (n={raw_sub.shape[1]}, max={raw_sub.median(axis=1).max():.0f} mm/h)')
    if not qc_sub.empty:
        ax_top_r = ax_top.twinx()
        ax_top_r.plot(qc_sub.index, qc_sub.median(axis=1),
                      color=colors.get('WU PWS (QC)', '#ff7f0e'), lw=1.6,
                      label=f'WU QC median (n={qc_sub.shape[1]})')
        ax_top_r.set_ylabel('WU QC mm/h', color=colors.get('WU PWS (QC)', '#ff7f0e'))
        ax_top_r.tick_params(axis='y', labelcolor=colors.get('WU PWS (QC)', '#ff7f0e'))
        ax_top_r.legend(loc='upper right', fontsize=9)
    ax_top.set_ylabel('WU RAW mm/h')
    ax_top.set_title(f'Before vs after QC — WU PWS, event {event_day.date()}')
    ax_top.axvspan(event_day, event_day + pd.Timedelta(days=1), color='red', alpha=0.06)
    ax_top.grid(True, alpha=0.3)
    ax_top.legend(loc='upper left', fontsize=9)

    # --- Bottom: all three networks on a shared, realistic scale ---
    nets = {'ASOS': asos_h, 'WU PWS (QC)': pws_qc_h}
    if meso_h is not None:
        nets['Mesonet'] = meso_h
    for name, df in nets.items():
        sub = df.loc[win0:win1]
        if sub.empty: continue
        c = colors.get(name, '#666')
        med = sub.median(axis=1)
        lo, hi = sub.quantile(0.25, axis=1), sub.quantile(0.75, axis=1)
        ax_bot.fill_between(sub.index, lo, hi, color=c, alpha=0.18)
        ax_bot.plot(med.index, med, color=c, lw=1.6,
                    label=f'{name} median of {sub.shape[1]}')
    ax_bot.axvspan(event_day, event_day + pd.Timedelta(days=1), color='red', alpha=0.06)
    ax_bot.set_ylabel('mm/h')
    ax_bot.set_title('Cross-network rainfall — after WU QC')
    ax_bot.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %Hh'))
    for lab in ax_bot.get_xticklabels():
        lab.set_rotation(30)
    ax_bot.grid(True, alpha=0.3); ax_bot.legend(loc='upper right', fontsize=9)
    plt.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Daily heatmap (single network)
# ---------------------------------------------------------------------------

def plot_per_station_before_after(
    raw_pws_dict: Dict[str, xr.Dataset],
    station_ids: Iterable[str],
    event_day: pd.Timestamp | None = None,
    event_pad_days: float | None = None,
    var: str = 'rainfall_amount',
    figsize_per_row: float = 2.2,
) -> plt.Figure:
    """Per-station grid: raw vs differentiated (`diff().clip(lower=0)`).

    Layout: `len(station_ids)` rows × 4 columns:
        col 0: raw daily               col 1: diff daily
        col 2: raw cumulative          col 3: diff cumulative

    Use as a sanity check after running QC: for any chosen station you can
    see, side-by-side, what the differentiation did to its daily totals and
    its cumulative shape.

    If `event_day` is given, that day is shaded on every panel.
    If `event_pad_days` is also given, the x-axis is restricted to a
    ±`event_pad_days` window around `event_day` — i.e. event zoom-in.
    """
    sids = list(station_ids)
    n = len(sids)
    fig, axes = plt.subplots(n, 4, figsize=(17, figsize_per_row * n),
                             sharex='col', sharey=False)
    if n == 1:
        axes = axes.reshape(1, -1)

    for i, sid in enumerate(sids):
        ax_rd, ax_dd, ax_rc, ax_dc = axes[i]
        if sid not in raw_pws_dict:
            for ax in axes[i]:
                ax.text(0.5, 0.5, f'{sid}: missing',
                        transform=ax.transAxes, ha='center')
            continue
        ds = raw_pws_dict[sid]
        if var not in ds:
            for ax in axes[i]:
                ax.text(0.5, 0.5, f'{sid}: no {var}',
                        transform=ax.transAxes, ha='center')
            continue

        raw = ds[var].squeeze(drop=True).to_series()
        raw.index = pd.to_datetime(raw.index)
        diff = raw.diff().clip(lower=0)
        if len(diff):
            diff.iloc[0] = 0.0

        # Optional event window restriction (event zoom-in)
        if event_day is not None and event_pad_days is not None:
            w0 = pd.Timestamp(event_day) - pd.Timedelta(days=event_pad_days)
            w1 = pd.Timestamp(event_day) + pd.Timedelta(days=event_pad_days)
            raw  = raw.loc[w0:w1]
            diff = diff.loc[w0:w1]

        raw_d  = raw.resample('1D').sum(min_count=1)
        diff_d = diff.resample('1D').sum(min_count=1)
        raw_c  = raw.fillna(0).cumsum()
        diff_c = diff.fillna(0).cumsum()

        ax_rd.plot(raw_d.index,  raw_d,  color='#7f7f7f', lw=1.0)
        ax_rd.set_title(f'{sid}  RAW daily  (sum={raw.sum():.0f} mm, max={raw.max():.1f})',
                        fontsize=9)
        ax_rd.set_ylabel('mm/day'); ax_rd.grid(True, alpha=0.3)

        ax_dd.plot(diff_d.index, diff_d, color='#d62728', lw=1.0)
        ax_dd.set_title(f'DIFF daily  (sum={diff.sum():.0f} mm, max={diff.max():.1f})',
                        fontsize=9)
        ax_dd.grid(True, alpha=0.3)

        ax_rc.plot(raw_c.index,  raw_c,  color='#7f7f7f', lw=1.0)
        ax_rc.set_title(f'RAW cumulative  (end={raw_c.iloc[-1]:.0f} mm)' if len(raw_c) else 'RAW cumulative',
                        fontsize=9)
        ax_rc.set_ylabel('cumulative mm'); ax_rc.grid(True, alpha=0.3)

        ax_dc.plot(diff_c.index, diff_c, color='#d62728', lw=1.0)
        ax_dc.set_title(f'DIFF cumulative  (end={diff_c.iloc[-1]:.0f} mm)' if len(diff_c) else 'DIFF cumulative',
                        fontsize=9)
        ax_dc.grid(True, alpha=0.3)

        if event_day is not None:
            for ax in axes[i]:
                ax.axvspan(pd.Timestamp(event_day),
                           pd.Timestamp(event_day) + pd.Timedelta(days=1),
                           color='red', alpha=0.06)

    # X-axis formatting
    if event_day is not None and event_pad_days is not None:
        fmt = mdates.DateFormatter('%m-%d %Hh')
        loc = mdates.HourLocator(interval=12)
    else:
        fmt = mdates.DateFormatter('%b %Y')
        loc = mdates.MonthLocator(interval=3)
    for ax in axes[-1]:
        ax.xaxis.set_major_formatter(fmt)
        ax.xaxis.set_major_locator(loc)
        for lab in ax.get_xticklabels():
            lab.set_rotation(30)

    plt.tight_layout()
    return fig


def plot_daily_heatmap(
    net_dict: Dict[str, xr.Dataset],
    title: str = '',
    n_worst: int = 25,
    var: str = 'rainfall_amount',
) -> plt.Figure:
    """Heatmap of daily rainfall for the `n_worst` stations (by daily max)."""
    cols = {}
    for sid, ds in net_dict.items():
        if var not in ds:
            continue
        s = ds[var].squeeze(drop=True).to_series()
        s.index = pd.to_datetime(s.index)
        cols[sid] = s.resample('1D').sum(min_count=1)
    dm = pd.concat(cols, axis=1)
    worst = dm.max(axis=0).sort_values(ascending=False).head(n_worst).index
    sub = dm[worst].T

    fig, ax = plt.subplots(figsize=(15, max(4, 0.3 * len(sub))))
    im = ax.imshow(np.log10(sub.values + 0.1), aspect='auto',
                   cmap='viridis', interpolation='nearest')
    ax.set_yticks(range(len(sub.index)))
    ax.set_yticklabels(sub.index, fontsize=8)
    xt = np.linspace(0, len(sub.columns) - 1, 9).astype(int)
    ax.set_xticks(xt)
    ax.set_xticklabels([sub.columns[i].strftime('%Y-%m') for i in xt], rotation=30)
    ax.set_xlabel('Date')
    ax.set_title(title or f'Daily rainfall (log10 mm + 0.1) — top {n_worst} stations by daily max')
    plt.colorbar(im, ax=ax, label='log10(daily mm + 0.1)')
    plt.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Pairwise stats
# ---------------------------------------------------------------------------

def pairwise_correlation(
    networks: Dict[str, pd.DataFrame],
    rainy_threshold: float = 0.1,
) -> pd.DataFrame:
    """Pearson r between network-median hourly series. Both `rainy hours only`
    (max across networks > threshold) and all hours."""
    medians = pd.DataFrame({n: df.median(axis=1) for n, df in networks.items()
                            if not df.empty}).dropna(how='all')
    if medians.empty:
        return pd.DataFrame()
    rainy = medians.fillna(0).max(axis=1) > rainy_threshold
    return pd.concat({
        'rainy_only': medians[rainy].corr().round(3),
        'all_hours' : medians.corr().round(3),
    }, names=['scope'])
