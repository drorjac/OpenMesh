"""
Rainfall maps from sensors (IDW) and their comparison with MRMS radar.

Ported and generalised from github.com/drorjac/pcpn_maps (commit e56d297):
`mapping/idw.py` (IDW, accumulation), `evaluation/metrics.py` (map-vs-radar scores),
`pipeline._distance_to_links` and `plotting.py` (map figures). Inputs are the tidy
hourly tables of `analysis.radar_utils.merge_event`, so every map starts from the same
pre-processed sensor data (gauge QC, CML ITU rain, hour-ending mm) as the point scores.

    maps = build_event_maps(merged, event)                    # (time, lat, lon) per source
    per_hour, pooled = compare_maps(maps['CML'], maps['MRMS'], near=maps['near_CML'])
    plot_event_totals(maps, merged)

Grid: the MRMS-aligned 0.01° grid of `fetch_data.mrms.Grid` (cell centres = MRMS
centres), so the radar needs no interpolation. Hourly values in mm, hour-ending UTC.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd
import xarray as xr

from fetch_data.mrms import OPENMESH, Domain, Grid, haversine_m
from fetch_data.mrms.domain import to_local_xy

# map name → networks of the merged table whose sensors feed it
MAP_SOURCES = {
    'CML': ('CML',),
    'PWS': ('WU PWS',),
    'Gauges': ('ASOS', 'Mesonet', 'WU PWS'),
}


# ============================================================================
# 1. Interpolation (IDW)
# ============================================================================

def idw_weights(src_x, src_y, dst_x, dst_y, power: float = 2.0, radius_m: Optional[float] = 10_000.0,
                nnear: Optional[int] = None, eps: float = 0.0) -> np.ndarray:
    """IDW weight matrix (n_dst, n_src), rows NOT normalised: w = 1 / (d**power + eps),
    zero beyond `radius_m` and outside the `nnear` closest sources. A destination on a
    source (d = 0, eps = 0) takes that source's value exactly."""
    d = np.hypot(dst_x[:, None] - src_x[None, :], dst_y[:, None] - src_y[None, :])
    with np.errstate(divide='ignore'):
        w = 1.0 / (d ** power + eps)
    exact = d == 0
    if eps == 0 and exact.any():
        rows = exact.any(1)
        w[rows] = exact[rows].astype(float)
    if radius_m is not None:
        w[d > radius_m] = 0.0
    if nnear is not None and nnear < d.shape[1]:
        far = np.argsort(d, axis=1)[:, nnear:]
        np.put_along_axis(w, far, 0.0, axis=1)
    return w


def idw_map(values: xr.DataArray, grid: Grid, *, power: float = 2.0,
            radius_m: Optional[float] = 10_000.0, nnear: Optional[int] = None,
            nan_policy: str = 'exclude', eps: float = 0.0) -> xr.DataArray:
    """Interpolate `values(sensor, time)` (coords `lat`, `lon` per sensor) to `grid`.

    nan_policy: 'exclude' — a NaN sensor drops out of that hour's average;
    'zero' — NaN counts as 0 mm. Cells with no sensor within `radius_m` are NaN.
    Distances are metres on a local equirectangular projection (< 0.1 % error over NYC).
    Returns (time, lat, lon) in the input units.
    """
    lat0, lon0 = float(np.mean(grid.lat)), float(np.mean(grid.lon))
    sx, sy = to_local_xy(values['lat'].values, values['lon'].values, lat0, lon0)
    glat, glon = grid.mesh()
    dx, dy = to_local_xy(glat.ravel(), glon.ravel(), lat0, lon0)
    W = idw_weights(sx, sy, dx, dy, power, radius_m, nnear, eps)            # (cells, sensors)

    V = values.transpose('sensor', ...).values.reshape(values.sizes['sensor'], -1)
    if nan_policy == 'zero':
        valid, V = np.ones_like(V), np.nan_to_num(V, nan=0.0)
    elif nan_policy == 'exclude':
        valid = np.isfinite(V).astype(float)
        V = np.where(valid > 0, V, 0.0)
    else:
        raise ValueError("nan_policy must be 'exclude' or 'zero'")
    num, den = W @ V, W @ valid
    with np.errstate(invalid='ignore', divide='ignore'):
        out = np.where(den > 0, num / den, np.nan)

    other = [d for d in values.dims if d != 'sensor']
    out = out.reshape(grid.shape + tuple(values.sizes[d] for d in other))
    out = np.moveaxis(out, [0, 1], [-2, -1])
    coords = {d: values[d].values for d in other}
    coords.update(lat=grid.lat, lon=grid.lon)
    return xr.DataArray(out.astype('float32'), dims=other + ['lat', 'lon'], coords=coords,
                        name=values.name or 'rain',
                        attrs=dict(values.attrs, interpolation='IDW', power=power,
                                   radius_m=radius_m if radius_m is not None else 'none',
                                   nnear=nnear if nnear is not None else 'all',
                                   nan_policy=nan_policy, n_sensors=int(values.sizes['sensor'])))


def accumulate(rate: xr.DataArray, freq: str = '1h', min_coverage: float = 0.8) -> xr.DataArray:
    """Rate series (mm/h, regular step) → accumulation per `freq` (mm), interval-ending.
    Mean rate over valid samples × interval length; intervals with fewer than
    `min_coverage` of the expected samples are NaN."""
    t = pd.DatetimeIndex(rate.time.values)
    step = pd.Series(t).diff().median()
    hours = pd.Timedelta(freq) / pd.Timedelta('1h')
    r = rate.resample(time=freq, label='right', closed='right')
    acc = (r.mean() * hours).where(r.count() >= min_coverage * (pd.Timedelta(freq) / step))
    acc.attrs = dict(rate.attrs, units='mm', accumulation=freq, sample_step=str(step),
                     min_coverage=min_coverage, time_label='end of accumulation window (UTC)')
    return acc


def distance_to_points(grid: Grid, lat, lon) -> xr.DataArray:
    """Distance (km) from each grid cell to the nearest sensor location."""
    glat, glon = grid.mesh()
    d = haversine_m(glat[..., None], glon[..., None], np.asarray(lat)[None, None],
                    np.asarray(lon)[None, None]).min(-1)
    return xr.DataArray(d / 1000.0, dims=('lat', 'lon'), coords={'lat': grid.lat, 'lon': grid.lon},
                        name='distance_km')


def distance_to_paths(grid: Grid, links: pd.DataFrame, step_m: float = 100.0) -> xr.DataArray:
    """Distance (km) from each grid cell to the nearest CML path (sampled every `step_m`).
    `links` needs site_0_lat, site_0_lon, site_1_lat, site_1_lon."""
    glat, glon = grid.mesh()
    best = np.full(glat.shape, np.inf)
    for r in links.itertuples():
        n = max(2, int(haversine_m(r.site_0_lat, r.site_0_lon, r.site_1_lat, r.site_1_lon) / step_m) + 1)
        s = np.linspace(0, 1, n)
        lat = r.site_0_lat + s * (r.site_1_lat - r.site_0_lat)
        lon = r.site_0_lon + s * (r.site_1_lon - r.site_0_lon)
        best = np.minimum(best, haversine_m(glat[..., None], glon[..., None], lat, lon).min(-1))
    return xr.DataArray(best / 1000.0, dims=('lat', 'lon'), coords={'lat': grid.lat, 'lon': grid.lon},
                        name='distance_km')


# ============================================================================
# 2. Event maps from the merged sensor table
# ============================================================================

def sensor_values(merged: pd.DataFrame, networks: Sequence[str], event: Optional[str] = None,
                  value: str = 'sensor_mm') -> xr.DataArray:
    """(sensor, time) DataArray of hourly mm from the merged table, with lat/lon coords
    (CML = path midpoint). Sensor labels are `network:id` so networks can be pooled."""
    m = merged[merged.network.isin(networks)]
    if event is not None:
        m = m[m.event == event]
    m = m.assign(sensor=m.network + ':' + m.sensor_id.astype(str))
    tab = m.pivot_table(index='sensor', columns='time', values=value, dropna=False)
    meta = m.groupby('sensor')[['lat', 'lon']].first().reindex(tab.index)
    return xr.DataArray(tab.values.astype(float), dims=('sensor', 'time'),
                        coords={'sensor': np.asarray(tab.index.tolist()),
                                'time': pd.DatetimeIndex(tab.columns),
                                'lat': ('sensor', meta.lat.values), 'lon': ('sensor', meta.lon.values)},
                        name='rain', attrs={'units': 'mm', 'networks': ','.join(networks)})


def build_event_maps(
    merged: pd.DataFrame,
    event,
    *,
    sources: Optional[Dict[str, Sequence[str]]] = None,
    domain: Domain = OPENMESH,
    radar_product: str = 'MultiSensor_QPE_01H_Pass2',
    cml: Optional[xr.Dataset] = None,
    exclude: Sequence[str] = (),
    client=None,
    **idw,
) -> xr.Dataset:
    """Hourly rain maps (mm, hour-ending) for one event, all on one MRMS-aligned grid.

    Variables: one IDW map per entry of `sources` (default `MAP_SOURCES`: CML, PWS,
    Gauges), 'MRMS' (the radar on the same cells), and 'dist_<name>' (km to the nearest
    sensor of that map; CML = nearest path when `cml` is given, else nearest midpoint).
    `domain` defaults to the OpenMesh link area; `exclude` lists sensor ids to leave
    out (e.g. links flagged by `cml_retrieval_qc`); `idw` goes to `idw_map`.
    """
    from fetch_data.mrms import NYC, hourly_rainfall, to_grid
    from analysis.radar_utils import cml_links, _hour_window
    sources = sources or MAP_SOURCES
    grid = Grid.from_domain(domain)
    ev = merged[(merged.event == event.event) & ~merged.sensor_id.astype(str).isin(list(exclude))]
    h0, h1 = _hour_window(event.start, event.end)
    times = pd.date_range(h0, h1, freq='1h')
    # fetch on the cached NYC crop when it covers the domain, then pick the grid cells
    fetch_dom = NYC if (NYC.lat_min <= domain.lat_min and domain.lat_max <= NYC.lat_max and
                        NYC.lon_min <= domain.lon_min and domain.lon_max <= NYC.lon_max) else domain.pad(0.01)
    radar = hourly_rainfall(h0 - pd.Timedelta('1h'), h1, fetch_dom, product=radar_product, client=client)
    out = {'MRMS': to_grid(radar, grid).reindex(time=times)}
    for name, nets in sources.items():
        vals = sensor_values(ev, nets)
        if vals.sizes['sensor'] == 0:
            continue
        out[name] = idw_map(vals, grid, **idw).reindex(time=times)
        if nets == ('CML',) and cml is not None:
            links = cml_links(cml).loc[[s.split(':', 1)[1] for s in vals.sensor.values]]
            out[f'dist_{name}'] = distance_to_paths(grid, links)
        else:
            out[f'dist_{name}'] = distance_to_points(grid, vals.lat.values, vals.lon.values)
    ds = xr.Dataset(out)
    ds.attrs = {'event': event.event, 'cls': event.cls, 'radar_product': radar_product,
                'domain': str(domain), 'units': 'mm per hour (hour-ending UTC)',
                'idw': ', '.join(f'{k}={v}' for k, v in idw.items()) or 'defaults'}
    return ds


def cml_retrieval_qc(merged: pd.DataFrame, event: str, *, radius_km: float = 5.0,
                     wet_alone_mm: float = 2.0, outlier_ratio: float = 5.0,
                     min_coverage: float = 0.8) -> pd.DataFrame:
    """Flag CML links whose event total disagrees with neighbouring links (pcpn_maps
    retrieval QC, stage 3). Uses other links only — no radar, no gauges.

    Per link with ≥ `min_coverage` valid hours: neighbours = other such links within
    `radius_km`. Flags: 'wet while neighbours dry' (total ≥ `wet_alone_mm`, neighbour
    median < 0.2 mm); 'outlier' (total > or < `outlier_ratio` × neighbour median ≥ 1 mm);
    'unchecked' (< 2 neighbours); 'low coverage'. Flags only — in convective rain a
    real outlier is signal, so dropping is left to the caller (`build_event_maps(exclude=)`).
    Unlike the original, links without data are not counted as dry neighbours.
    """
    m = merged[(merged.event == event) & (merged.network == 'CML')]
    g = m.groupby('sensor_id')
    t = pd.DataFrame({'total_mm': g.sensor_mm.sum(min_count=1), 'coverage': g.sensor_mm.apply(lambda x: x.notna().mean()),
                      'lat': g.lat.first(), 'lon': g.lon.first()})
    ok = t[t.coverage >= min_coverage]
    rows = []
    for lk, r in t.iterrows():
        if r.coverage < min_coverage:
            rows.append((lk, 'low coverage', np.nan, 0))
            continue
        d = haversine_m(r.lat, r.lon, ok.lat.values, ok.lon.values)
        nb = ok[(d <= radius_km * 1000) & (ok.index != lk)]
        if len(nb) < 2:
            rows.append((lk, 'unchecked', np.nan, len(nb)))
            continue
        med = float(nb.total_mm.median())
        if med < 0.2 and r.total_mm >= wet_alone_mm:
            flag = 'wet while neighbours dry'
        elif med >= 1.0 and (r.total_mm > outlier_ratio * med or r.total_mm < med / outlier_ratio):
            flag = 'outlier'
        else:
            flag = 'ok'
        rows.append((lk, flag, med, len(nb)))
    q = pd.DataFrame(rows, columns=['link', 'flag', 'neighbour_median_mm', 'n_neighbours']).set_index('link')
    return t[['total_mm', 'coverage']].join(q).round(2)


# ============================================================================
# 3. Map-vs-radar comparison
# ============================================================================

def compare_maps(est: xr.DataArray, radar: xr.DataArray, *, near: Optional[xr.DataArray] = None,
                 near_km: Optional[float] = None, wet_threshold: float = 0.1,
                 min_n: int = 30) -> tuple:
    """Hourly map vs. radar on the same grid: (per_hour DataFrame, pooled dict).

    With `near` (a distance-km field, e.g. maps['dist_CML']) and `near_km`, only cells
    within `near_km` of a sensor are scored — IDW far from any sensor is extrapolation.
    `pooled` also holds 'event_total_scores' (per-cell event totals, hours where both
    are valid) and 'hours'. Metrics as `analysis.radar_utils.scores`.
    """
    from analysis.radar_utils import _scores_min
    e, r = xr.align(est, radar, join='inner')
    if near is not None and near_km is not None:
        mask = near <= near_km
        e, r = e.where(mask), r.where(mask)
    rows = [{'time': pd.Timestamp(t), **_scores_min(e.sel(time=t), r.sel(time=t), wet_threshold, 1)}
            for t in e.time.values]
    per_hour = pd.DataFrame(rows).set_index('time') if rows else pd.DataFrame()
    pooled = _scores_min(e, r, wet_threshold, min_n)
    joint = e.notnull() & r.notnull()
    pooled['event_total_scores'] = _scores_min(e.where(joint).sum('time', min_count=1),
                                               r.where(joint).sum('time', min_count=1), 1.0, 1)
    pooled['hours'] = int(e.sizes['time'])
    return per_hour, pooled


def map_scores(maps: xr.Dataset, *, near_km: Optional[float] = 2.0, wet_threshold: float = 0.1
               ) -> pd.DataFrame:
    """Pooled hourly scores of every sensor map in `maps` against its 'MRMS' variable,
    within `near_km` of that map's sensors (None = every cell)."""
    rows = []
    for name in [v for v in maps.data_vars if v != 'MRMS' and not v.startswith('dist_')]:
        _, s = compare_maps(maps[name], maps['MRMS'], near=maps.get(f'dist_{name}'),
                            near_km=near_km, wet_threshold=wet_threshold)
        tot = s.pop('event_total_scores')
        rows.append({'map': name, **s, 'total_nrmse': tot.get('nrmse', np.nan),
                     'total_rel_bias': tot.get('rel_bias', np.nan)})
    return pd.DataFrame(rows).set_index('map')


def event_map_scores(
    merged: pd.DataFrame,
    events: pd.DataFrame,
    *,
    near_km: Optional[float] = 2.0,
    qc_exclude: bool = False,
    cml: Optional[xr.Dataset] = None,
    client=None,
    **kw,
) -> pd.DataFrame:
    """`map_scores` for every event: rows (event, cls, map). With `qc_exclude`, CML links
    flagged 'outlier' or 'wet while neighbours dry' by `cml_retrieval_qc` are left out
    of that event's CML map. `kw` goes to `build_event_maps` (e.g. power=, nnear=)."""
    rows = []
    for ev in events.itertuples():
        exclude = ()
        if qc_exclude:
            q = cml_retrieval_qc(merged, ev.event)
            exclude = q.index[q.flag.isin(['outlier', 'wet while neighbours dry'])].tolist()
        maps = build_event_maps(merged, ev, cml=cml, exclude=exclude, client=client, **kw)
        sc = map_scores(maps, near_km=near_km).assign(event=ev.event, cls=ev.cls, n_excluded=len(exclude))
        rows.append(sc.reset_index())
    return pd.concat(rows, ignore_index=True).set_index(['event', 'cls', 'map'])


def pool_map_scores(table: pd.DataFrame, by: Sequence[str] = ('cls', 'map')) -> pd.DataFrame:
    """Median over events of the per-event map scores (robust to one bad storm)."""
    cols = ['nrmse', 'rel_bias', 'corr', 'csi', 'total_nrmse', 'total_rel_bias']
    return table.reset_index().groupby(list(by))[cols].median()


# ============================================================================
# 4. Figures
# ============================================================================

RAIN_CMAP, DIFF_CMAP = 'Blues', 'RdBu_r'
MAP_COLORS = {'CML': '#eda100', 'PWS': '#eb6834', 'Gauges': '#e87ba4', 'MRMS': '#52514e'}


def _panel_ratio(maps) -> float:
    """Height / width of a map panel for this grid (true distances)."""
    lat_span = float(maps.lat.max() - maps.lat.min()) or 0.01
    lon_span = float(maps.lon.max() - maps.lon.min()) or 0.01
    return lat_span / (lon_span * np.cos(np.radians(float(maps.lat.mean()))))


def _aspect(ax, lat):
    ax.set_aspect(1.0 / np.cos(np.radians(float(np.mean(lat)))))


def draw_links(ax, links: pd.DataFrame, color: str = '#0b0b0b', lw: float = 0.8, alpha: float = 0.8):
    """CML paths from a frame with site_0/1 lat/lon (e.g. `radar_utils.cml_links`)."""
    for r in links.itertuples():
        ax.plot([r.site_0_lon, r.site_1_lon], [r.site_0_lat, r.site_1_lat], color=color, lw=lw,
                alpha=alpha, solid_capstyle='round')


def plot_field(field: xr.DataArray, ax=None, *, title: str = '', vmax: Optional[float] = None,
               vmin: float = 0.0, cmap: str = RAIN_CMAP, label: str = 'mm', colorbar: bool = True,
               mask: Optional[xr.DataArray] = None):
    """One (lat, lon) field; cells where `mask` is False are left blank."""
    import matplotlib.pyplot as plt
    if ax is None:
        _, ax = plt.subplots(figsize=(4.5, 4.5))
    f = field.where(mask) if mask is not None else field
    vmax = vmax if vmax is not None else float(np.nanmax(f.values)) if np.isfinite(f).any() else 1.0
    m = ax.pcolormesh(f.lon, f.lat, f.values, cmap=cmap, vmin=vmin, vmax=max(vmax, 1e-6), shading='nearest')
    _aspect(ax, f.lat)
    ax.set_title(title, fontsize=9, loc='left')
    ax.tick_params(labelsize=7)
    if colorbar:
        plt.colorbar(m, ax=ax, shrink=0.8, pad=0.02, label=label)
    return m


def plot_event_totals(maps: xr.Dataset, merged: Optional[pd.DataFrame] = None, *,
                      cml: Optional[xr.Dataset] = None, near_km: Optional[float] = None,
                      scores: Optional[pd.DataFrame] = None):
    """Event totals of MRMS and every sensor map on ONE color scale, sensors overlaid
    (CML paths, gauge dots); optional NRMSE bars from `map_scores`. With `near_km`,
    each sensor map is blanked beyond that distance from its sensors."""
    import matplotlib.pyplot as plt
    from analysis.radar_utils import cml_links
    names = ['MRMS'] + [v for v in maps.data_vars if v != 'MRMS' and not v.startswith('dist_')]
    tot = {n: maps[n].sum('time', min_count=1) for n in names}
    # scale set by the radar, so one extreme sensor cannot wash out the others
    vmax = 1.5 * float(np.nanpercentile(tot['MRMS'].values, 99))
    n_pan = len(names) + (1 if scores is not None else 0)
    h_over_w = _panel_ratio(maps)
    fig, axes = plt.subplots(1, n_pan, figsize=(2.4 * n_pan + 1.0, 2.4 * h_over_w + 0.8),
                             squeeze=False, layout='constrained')
    axes = axes[0]
    m = None
    ev = merged[merged.event == maps.attrs.get('event')] if merged is not None else None
    for ax, n in zip(axes, names):
        mask = maps[f'dist_{n}'] <= near_km if (near_km and f'dist_{n}' in maps) else None
        m = plot_field(tot[n], ax, title='MRMS radar' if n == 'MRMS' else f'{n} (IDW)', vmax=vmax,
                       colorbar=False, mask=mask)
        if n == 'CML' and cml is not None:
            draw_links(ax, cml_links(cml))
        elif ev is not None and n in MAP_SOURCES:
            pts = ev[ev.network.isin(MAP_SOURCES[n])].groupby('sensor_id')[['lat', 'lon']].first()
            ax.scatter(pts.lon, pts.lat, s=6, color='#0b0b0b', marker='^')
        ax.set_xlim(float(maps.lon.min()) - 0.005, float(maps.lon.max()) + 0.005)
        ax.set_ylim(float(maps.lat.min()) - 0.005, float(maps.lat.max()) + 0.005)
    fig.colorbar(m, ax=axes[:len(names)].tolist(), shrink=0.8, extend='max',
                 label='event total (mm); darkest = ≥ 1.5 × radar p99')
    if scores is not None:
        ax = axes[-1]
        sc = scores['nrmse'].reindex([n for n in names if n in scores.index])
        ax.barh(range(len(sc)), sc.values, color=[MAP_COLORS.get(n, '0.5') for n in sc.index], height=0.6)
        ax.set_yticks(range(len(sc)), sc.index, fontsize=8)
        for i, v in enumerate(sc.values):
            ax.text(v, i, f' {v:.2f}', va='center', fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel('hourly NRMSE vs MRMS' + (f' (≤ {near_km:g} km)' if near_km else ''), fontsize=8)
        ax.spines[['top', 'right']].set_visible(False)
    fig.suptitle(f"{maps.attrs.get('event', '')}: event accumulation (mm)", fontsize=10, x=0.01, ha='left')
    return {'fig': fig, 'axes': axes}


def plot_hourly_snapshots(maps: xr.Dataset, *, n_times: int = 6, diff: str = 'CML',
                          near_km: Optional[float] = None):
    """Rows = MRMS and each sensor map, columns = `n_times` hours around the radar
    peak; a last row shows `diff` minus MRMS (diverging scale, 0 = white)."""
    import matplotlib.pyplot as plt
    rows = ['MRMS'] + [v for v in maps.data_vars if v != 'MRMS' and not v.startswith('dist_')]
    times = pd.DatetimeIndex(maps.time.values)
    peak = maps['MRMS'].mean(('lat', 'lon')).idxmax().values
    i0 = max(0, min(times.get_indexer([peak])[0] - n_times // 2, len(times) - n_times))
    sel = times[i0:i0 + n_times]
    vmax = max(1e-3, 1.5 * float(np.nanpercentile(maps['MRMS'].sel(time=sel).values, 99)))
    has_diff = diff in maps
    n_rows = len(rows) + int(has_diff)
    w = 1.25
    fig, axes = plt.subplots(n_rows, len(sel), figsize=(w * len(sel) + 1.6, w * _panel_ratio(maps) * n_rows + 0.6),
                             squeeze=False, layout='constrained')
    m_rain = m_diff = None
    for i, r in enumerate(rows):
        for j, t in enumerate(sel):
            ax = axes[i][j]
            mask = maps[f'dist_{r}'] <= near_km if (near_km and f'dist_{r}' in maps) else None
            m_rain = plot_field(maps[r].sel(time=t), ax, vmax=vmax, colorbar=False, mask=mask)
            ax.set_xticks([]), ax.set_yticks([])
            if i == 0:
                ax.set_title(f'{t:%m-%d %H:%M}', fontsize=7)
            if j == 0:
                ax.set_ylabel(r, fontsize=8)
    if has_diff:
        for j, t in enumerate(sel):
            ax = axes[-1][j]
            d = maps[diff].sel(time=t) - maps['MRMS'].sel(time=t)
            mask = maps[f'dist_{diff}'] <= near_km if (near_km and f'dist_{diff}' in maps) else None
            m_diff = plot_field(d, ax, vmin=-vmax / 2, vmax=vmax / 2, cmap=DIFF_CMAP, colorbar=False, mask=mask)
            ax.set_xticks([]), ax.set_yticks([])
            if j == 0:
                ax.set_ylabel(f'{diff} − MRMS', fontsize=8)
    fig.colorbar(m_rain, ax=axes[:len(rows)].ravel().tolist(), shrink=0.6, extend='max',
                 label='hourly rain (mm)')
    if m_diff is not None:
        fig.colorbar(m_diff, ax=axes[-1].tolist(), shrink=0.9, extend='both', label='difference (mm)')
    fig.suptitle(f"{maps.attrs.get('event', '')}: hourly maps around the radar peak",
                 fontsize=10, x=0.01, ha='left')
    return {'fig': fig, 'axes': axes}
