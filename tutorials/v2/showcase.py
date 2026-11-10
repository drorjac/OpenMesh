"""Helpers of the OpenMesh v2 showcase notebook (tutorials/v2/03_showcase.ipynb).

Reads only the public v2 record (Zenodo 2.0.0, doi:10.5281/zenodo.23283445) through analysis.datasets:
links, ASOS, METAR, GHCN-Daily and the MRMS radar days. The rain gauge next to a path is the
nearest ASOS station.

Sections
--------
- loading      : `load()` returns every file as one namespace
- metadata     : file inventory, variable tables, values per year, paths reporting per day
- maps         : land basemap, links by band, every sensor
- events       : attenuation against a pre-event baseline, ASOS rain near a path, panels and day maps
- rain chain   : wet/dry (rolling std), baseline (pycomlink), wet antenna (pycomlink), k-R (pycomlink),
                 radar along the paths (poligrain)
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.collections import LineCollection

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from analysis import datasets as D  # noqa: E402

CACHE = Path(__file__).resolve().parent / 'cache'          # git-ignored

BANDS = ['V60', 'K24', 'C5']
BAND_COL = {'V60': '#c2185b', 'K24': '#d97706', 'C5': '#8a99a8'}
BAND_NAME = {'V60': '60 GHz band (58–69 GHz)', 'K24': '24 GHz', 'C5': '5 GHz'}
RAIN_COL, GAUGE_COL, RADAR_COL, CML_COL = '#1d6fb8', '#1d6fb8', '#2e8b57', '#c2185b'
ERAS = [('2023-10-29', '2024-07-15', 'every minute (rsl)', '#e8f1fb'),
        ('2024-07-15', '2025-04-21', '00–01 UTC only', '#fbeee8'),
        ('2025-04-21', '2026-11-02', 'rsl_avg / rsl_max: 1 h, then 6 min', '#eaf6ee')]


# ============================================================================ loading

def style():
    warnings.filterwarnings('ignore', category=RuntimeWarning)
    warnings.filterwarnings('ignore', category=FutureWarning)
    plt.rcParams.update({'figure.dpi': 100, 'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.grid': True, 'grid.alpha': .3, 'font.size': 10, 'axes.titlesize': 11,
                         'axes.titleweight': 'bold', 'legend.frameon': False})
    pd.set_option('display.width', 200)
    pd.set_option('display.max_columns', 30)
    pd.set_option('display.max_colwidth', 70)


def load():
    """Every file of the v2 record, downloaded from Zenodo on the first run (~600 MB)."""
    D.use('v2')
    D.ensure('v2')
    rec = D.v2_root()
    data = rec / 'data'
    R = SimpleNamespace(rec=rec, data=data)
    R.links = xr.open_dataset(data / 'links/openmesh_links.nc')
    R.smeta = pd.read_csv(data / 'links/links_metadata.csv', dtype={'cml_id': str})
    R.paths = D.path_table('v2').set_index('cml_id')
    R.asos = xr.open_dataset(data / 'weather/asos/openmesh_asos.nc')
    R.asos_st = pd.read_csv(data / 'weather/asos/asos_stations.csv')
    R.metar = pd.read_csv(data / 'weather/metar/openmesh_metar.csv', parse_dates=['time'], low_memory=False)
    R.ghcn = pd.read_csv(data / 'weather/ghcn/ghcn_daily.csv')
    R.ghcn_st = pd.read_csv(data / 'weather/ghcn/ghcn_stations.csv')
    R.radar_ev = pd.read_csv(data / 'weather/radar/radar_events.csv')
    R.land = regional_land()
    return R


def regional_land(box=(-74.6, 40.3, -73.3, 41.2)):
    """Natural Earth 10 m land around NYC (New Jersey, Long Island, Westchester), clipped to `box`; cartopy downloads
    it once into its cache. Without cartopy the maps have a plain background."""
    try:
        import cartopy.io.shapereader as shp
        import shapely.geometry as sg
    except ImportError:
        return []
    b = sg.box(*box)
    out = []
    for g in shp.Reader(shp.natural_earth(resolution='10m', category='physical', name='land')).geometries():
        if g.intersects(b):
            c = g.intersection(b)
            out += list(c.geoms) if hasattr(c, 'geoms') else [c]
    return out


def span(t):
    t = pd.DatetimeIndex(t)
    return f'{t[0]:%Y-%m-%d} → {t[-1]:%Y-%m-%d}'


# ============================================================================ metadata

def file_inventory(R):
    rows = [[str(p.relative_to(R.rec)), round(p.stat().st_size / 1e6, 1)]
            for p in sorted(R.data.rglob('*')) if p.is_file()]
    return pd.DataFrame(rows, columns=['file', 'MB']).set_index('file')


def variables_table(ds):
    return pd.DataFrame([[n, ', '.join(v.dims), str(v.dtype), v.attrs.get('long_name', ''), v.attrs.get('units', '')]
                         for n, v in {**ds.coords, **ds.data_vars}.items()],
                        columns=['name', 'dims', 'dtype', 'long_name', 'units']).set_index('name')


def sensor_table(R):
    return pd.DataFrame([
        ['links', 'data/links/openmesh_links.nc', f'{len(R.paths)} paths / {len(R.smeta)} sublinks', span(R.links.time),
         '1 min / 1 h / 6 min', 'rsl, rsl_avg, rsl_max (dBm)', 'Zenodo v2'],
        ['ASOS', 'data/weather/asos/openmesh_asos.nc', f"{R.asos.sizes['id']} stations", span(R.asos.time), '1 min',
         'rain, T, RH, wind, precip type', 'Zenodo v2'],
        ['METAR', 'data/weather/metar/openmesh_metar.csv', f'{R.metar.station.nunique()} stations, {len(R.metar):,} reports',
         span(R.metar.time.sort_values()), 'hourly + specials', 'present weather, precip, visibility', 'Zenodo v2'],
        ['GHCN-Daily', 'data/weather/ghcn/ghcn_daily.csv', f'{len(R.ghcn_st)} stations', f'{R.ghcn.date.min()} → {R.ghcn.date.max()}',
         '1 day', 'rain, snowfall, snow depth', 'Zenodo v2'],
        ['radar', 'data/weather/radar/*.nc', f'{len(R.radar_ev)} days (5 rain, 5 snow)',
         f'{R.radar_ev.day.min()} → {R.radar_ev.day.max()}', '1 h / 15 min / 10 min', 'MRMS QPE, precip flag; KOKX', 'Zenodo v2'],
    ], columns=['sensor', 'file', 'size', 'period', 'step', 'variables', 'source']).set_index('sensor')


def _blocks(R, n=50_000):
    t = pd.DatetimeIndex(R.links.time.values)
    for a in range(0, len(t), n):
        b = min(a + n, len(t))
        yield t[a:b], R.links.isel(time=slice(a, b))


def values_per_year(R):
    """Million non-missing values per signal, band and year (reads the whole link file once; cached)."""
    cf = CACHE / 'values_per_year.csv'
    if cf.exists():
        return pd.read_csv(cf, index_col=[0, 1])
    band = R.paths.band.reindex(R.links.cml_id.values.astype(str)).values
    acc = {}
    for t, blk in _blocks(R):
        for v in ['rsl', 'rsl_avg', 'rsl_max']:
            n = blk[v].notnull().sum('sublink_id').values
            for bd in BANDS:
                cnt = n[band == bd].sum(0)
                for y in np.unique(t.year):
                    acc[(v, bd, y)] = acc.get((v, bd, y), 0) + int(cnt[t.year == y].sum())
    out = (pd.Series(acc).rename_axis(['variable', 'band', 'year']).unstack('year') / 1e6).round(2)
    CACHE.mkdir(exist_ok=True)
    out.to_csv(cf)
    return out


def paths_reporting_daily(R):
    """Paths with any value per day, by band (cached)."""
    cf = CACHE / 'daily_reporting.csv'
    if cf.exists():
        return pd.read_csv(cf, index_col=0, parse_dates=True)
    rows = []
    for t, blk in _blocks(R):
        has = (blk.rsl.notnull() | blk.rsl_avg.notnull()).any('sublink_id').values
        rows.append(pd.DataFrame(has.T, index=t.floor('D'), columns=R.links.cml_id.values.astype(str)).groupby(level=0).any())
    has = pd.concat(rows).groupby(level=0).any()
    out = pd.DataFrame({b: has.loc[:, R.paths.index[R.paths.band == b]].sum(axis=1) for b in BANDS})
    CACHE.mkdir(exist_ok=True)
    out.to_csv(cf)
    return out


def shade_eras(ax, label_y=None):
    for a, b, lab, c in ERAS:
        ax.axvspan(pd.Timestamp(a), pd.Timestamp(b), color=c, zorder=0)
        if label_y is not None:
            ax.text(pd.Timestamp(a) + pd.Timedelta('5D'), label_y, lab, fontsize=8, color='#444')


# ============================================================================ maps

LAND, WATER, LAND_EDGE = '#f2f4f6', '#d3e3f0', '#aebac6'


def draw_boro(ax, R, label=False):
    ax.set_facecolor(WATER if getattr(R, 'land', None) else LAND)
    for g in getattr(R, 'land', []):
        x, y = g.exterior.xy
        ax.fill(x, y, color=LAND, ec='none', zorder=0)
    ax.set_aspect(1 / np.cos(np.radians(40.7)))
    ax.grid(False)
    ax.tick_params(labelsize=8)


def draw_links(ax, paths, bands=BANDS, lw=None, label=True):
    for b in ['C5', 'K24', 'V60']:
        if b not in bands:
            continue
        d = paths[paths.band == b]
        segs = [[(r.site_0_lon, r.site_0_lat), (r.site_1_lon, r.site_1_lat)] for r in d.itertuples()]
        ax.add_collection(LineCollection(
            segs, colors=BAND_COL[b], lw=(lw or {'C5': .5, 'K24': 2, 'V60': 2.2}[b]),
            alpha={'C5': .6, 'K24': 1, 'V60': 1}[b], zorder=2,
            label=f'{BAND_NAME[b]} ({len(d)})' if label else None))


def sensor_map(R):
    fig, axs = plt.subplots(1, 2, figsize=(15, 7.5))
    for ax, (xl, yl) in zip(axs, [((-74.27, -73.70), (40.49, 40.92)), ((-74.03, -73.90), (40.64, 40.75))]):
        draw_boro(ax, R)
        draw_links(ax, R.paths)
        ax.scatter(R.asos.lon, R.asos.lat, s=60, marker='s', c='k', label='ASOS (5)', zorder=4)
        ax.scatter(R.ghcn_st.lon, R.ghcn_st.lat, s=50, marker='x', c='#6a3d9a', label=f'GHCN-Daily ({len(R.ghcn_st)})', zorder=4)
        ax.set_xlim(xl)
        ax.set_ylim(yl)
    axs[0].legend(loc='upper left', fontsize=8, frameon=True)
    axs[0].set_title('All sensors')
    axs[1].set_title('Zoom: Lower Manhattan and Brooklyn')
    plt.tight_layout()
    return fig


# ============================================================================ events

def hav(lat0, lon0, lat1, lon1):
    r = np.pi / 180
    a = np.sin((lat1 - lat0) * r / 2) ** 2 + np.cos(lat0 * r) * np.cos(lat1 * r) * np.sin((lon1 - lon0) * r / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def midpoint(R, cid):
    p = R.paths.loc[cid]
    return (p.site_0_lat + p.site_1_lat) / 2, (p.site_0_lon + p.site_1_lon) / 2


def day_slice(day, var):
    """Stamps of one UTC day. rsl_avg covers the window ending at its stamp, so its day is (00:00, 24:00]."""
    t0 = pd.Timestamp(day)
    t1 = t0 + pd.Timedelta('1D')
    return slice(t0 + pd.Timedelta('1s'), t1) if var == 'rsl_avg' else slice(t0, t1 - pd.Timedelta('1s'))


def signal_var(day):
    return 'rsl' if pd.Timestamp(day) < D.V2_ERA_END else 'rsl_avg'


def gauge_near(R, cid, start, end):
    """5-min rain rate (mm/h) of the ASOS gauge nearest the path's midpoint, flag 0 only, labelled by the end of
    each 5 min. Returns (series, station id, distance km)."""
    lat, lon = midpoint(R, cid)
    d = hav(lat, lon, R.asos.lat.values, R.asos.lon.values)
    i = int(np.argmin(d))
    st = str(R.asos.id.values[i])
    r = R.asos.rainfall_amount.where(R.asos.rainfall_flag == 0).sel(id=st, time=slice(start, end)).to_series()
    r = r.resample('5min', closed='right', label='right').sum(min_count=4) * 12
    return r.rename('asos_mm_h'), st, float(d[i])


def gauge_day(R, day, cid):
    t0 = pd.Timestamp(day)
    return gauge_near(R, cid, t0 + pd.Timedelta('1min'), t0 + pd.Timedelta('1D'))


def attenuation_vs_prior(R, day):
    """Quick look: median level of the 3 days before minus the level, every path and sublink of one day."""
    var = signal_var(day)
    t0 = pd.Timestamp(day)
    x = R.links[var].sel(time=day_slice(day, var)).load()
    base = R.links[var].sel(time=slice(t0 - pd.Timedelta('3D'), t0 - pd.Timedelta('1s'))).median('time')
    return base - x


def top_sublinks(R, att, cid, min_valid=.3):
    """The sublinks of the path's highest frequency with data on the day."""
    f = R.links.frequency.sel(cml_id=cid)
    fmax = float(f.max())
    return [s for s in R.links.sublink_id.values
            if float(f.sel(sublink_id=s)) == fmax and float(att.sel(cml_id=cid, sublink_id=s).notnull().mean()) > min_valid]


def mmwave_paths_on(R, att, bands=('V60', 'K24')):
    cids = [c for c in R.paths.index[R.paths.band.isin(bands)] if top_sublinks(R, att, c)]
    return sorted(cids, key=lambda c: -float(att.sel(cml_id=c).quantile(.99)))


def _hours(ax):
    ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 3)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))


def event_panels(R, day, att, cids, ncol=3):
    """One panel per path: attenuation of its top-frequency sublinks and the rain rate of the nearest ASOS gauge."""
    n = len(cids)
    nrow = int(np.ceil(n / ncol))
    fig, axs = plt.subplots(nrow, ncol, figsize=(5.2 * ncol, 2.4 * nrow), sharex=True, squeeze=False)
    for ax, c in zip(axs.flat, cids):
        rr, st, dkm = gauge_day(R, day, c)
        ax2 = ax.twinx()
        ax2.fill_between(rr.index, rr.values, step='pre', color=GAUGE_COL, alpha=.25, lw=0)
        ax2.set_ylim(0, None)
        ax2.grid(False)
        ax2.tick_params(colors=GAUGE_COL, labelsize=7)
        for s, col in zip(top_sublinks(R, att, c), [BAND_COL[R.paths.loc[c, 'band']], '#7b3fa0']):
            a = att.sel(cml_id=c, sublink_id=s)
            ax.plot(a.time, a, lw=.7, color=col)
        p = R.paths.loc[c]
        ax.set_title(f"cml {c} · {p.frequency/1000:.1f} GHz · {p.length/1000:.1f} km · {st} {dkm:.0f} km", fontsize=9)
        ax.tick_params(labelsize=7)
        ax.set_zorder(ax2.get_zorder() + 1)
        ax.patch.set_visible(False)
        _hours(ax)
    for ax in axs.flat[n:]:
        ax.set_visible(False)
    for ax in axs[:, 0]:
        ax.set_ylabel('attenuation (dB)', fontsize=8)
    fig.suptitle(f'{day}: attenuation (lines, left axis) and 5-min rain rate of the nearest ASOS gauge '
                 f'(shaded, mm/h, right axis)', y=1.0)
    plt.tight_layout()
    return fig


def event_map(R, day, att, cids, radar=True):
    fig, ax = plt.subplots(figsize=(9.5, 8))
    draw_boro(ax, R)
    f = R.radar_ev.loc[R.radar_ev.day == day, 'file']
    if radar and len(f):
        rd = xr.open_dataset(R.data / 'weather/radar' / f.iloc[0])
        tot = rd.rainfall_amount_1h.sum('time_1h', min_count=1)
        m = ax.pcolormesh(rd.lon, rd.lat, tot, cmap='Greens', vmin=0, alpha=.45, shading='nearest', zorder=1)
        plt.colorbar(m, ax=ax, shrink=.5, label='MRMS day total (mm)')
    draw_links(ax, R.paths, bands=['C5'], lw=.3, label=False)
    norm, cm = mcolors.Normalize(0, 20), plt.cm.magma_r
    for c in cids:
        p = R.paths.loc[c]
        ax.plot([p.site_0_lon, p.site_1_lon], [p.site_0_lat, p.site_1_lat], lw=3.5, zorder=3, solid_capstyle='round',
                color=cm(norm(float(att.sel(cml_id=c).quantile(.99)))))
    t0 = pd.Timestamp(day)
    r = R.asos.rainfall_amount.where(R.asos.rainfall_flag == 0).sel(
        time=slice(t0 + pd.Timedelta('1min'), t0 + pd.Timedelta('1D')))
    tot = r.sum('time').where(r.notnull().mean('time') > .8)
    sc = ax.scatter(R.asos.lon, R.asos.lat, c=tot, cmap='Blues', vmin=0, vmax=100, s=90, marker='s', ec='k', lw=.6,
                    zorder=4)
    for i, st in enumerate(R.asos.id.values):
        ax.annotate(f'{st} {float(tot[i]):.0f} mm', (float(R.asos.lon[i]), float(R.asos.lat[i])), fontsize=8,
                    xytext=(5, 5), textcoords='offset points', zorder=5)
    plt.colorbar(sc, ax=ax, shrink=.5, label='ASOS day total (mm)')
    plt.colorbar(plt.cm.ScalarMappable(norm, cm), ax=ax, shrink=.5, label='path 99th-percentile attenuation (dB)')
    ax.set_xlim(-74.1, -73.82)
    ax.set_ylim(40.6, 40.8)
    ax.set_title(f'{day}: mm-wave paths, ASOS and radar')
    plt.tight_layout()
    return fig


# ============================================================================ rain chain

def link_level(R, cid, start, end, sublinks=None):
    """Received level of one path (sublink × time) and the time step in minutes."""
    x = R.links.sel(cml_id=cid, time=slice(start, end))
    if sublinks is not None:
        x = x.sel(sublink_id=list(sublinks))
    var = 'rsl' if x.rsl.notnull().any() else 'rsl_avg'
    lvl = x[var].load()
    step = float(pd.Series(np.diff(lvl.time.values)).median() / pd.Timedelta('1min'))
    return lvl, step, var


def fill_blackouts(lvl, db_above_min=6):
    """Blackout gaps (pycomlink.processing.blackout_gap_detection): a run of missing values that starts and ends
    with a level within `db_above_min` dB of the sublink's lowest level is a signal loss in heavy rain, not an
    outage. Those values are set to the lowest level, a lower bound of the attenuation. Returns (level, mask)."""
    from pycomlink.processing.blackout_gap_detection import (
        created_blackout_gap_mask_from_start_end_markers as gap_mask, get_blackout_start_and_end)
    out, mask = lvl.copy(), xr.zeros_like(lvl, dtype=bool)
    for s in lvl.sublink_id.values:
        x = lvl.sel(sublink_id=s).values.astype(float)
        if np.isnan(x).all():
            continue
        floor = np.nanmin(x)
        start, end = get_blackout_start_and_end(x, floor + db_above_min)
        m = gap_mask(x, start, end)
        x[m] = floor
        out.loc[dict(sublink_id=s)] = x
        mask.loc[dict(sublink_id=s)] = m
    return out, mask


def rain_chain(R, cid, day, sublinks=None, wet_method='rsd', rsd_window='60min', rsd_threshold=0.8, waa='schleiss',
               n_average_last_dry=5, blackout_db=6, gauge_pad='30min', spinup='1D'):
    """CML rain rate of one path on one day, the OpenSense/pycomlink processing chain:

    0. blackout gaps (signal lost in heavy rain) set to the sublink's lowest level, `fill_blackouts`
       (pycomlink.processing.blackout_gap_detection); `blackout_db=None` skips it
    1. TRSL = −RSL (the record has no transmitted level; a constant TSL drops out with the baseline)
    2. wet/dry, `wet_method`:
       'rsd' rolling standard deviation of TRSL over `rsd_window` > `rsd_threshold` dB (Schleiss & Berne 2010,
             as in the pycomlink examples): from the link alone
       'gauge' wet when the nearest ASOS gauge records rain within ±`gauge_pad` (a reference-based flag)
    3. baseline: pycomlink.processing.baseline.baseline_constant (level held through wet periods)
    4. A_obs = TRSL − baseline, clipped at 0
    5. wet antenna: pycomlink.processing.wet_antenna, `waa` in {'pastorek', 'leijnse', 'schleiss', None}
    6. R = pycomlink.processing.k_R_relation.calc_R_from_A (ITU-R P.838 k-R power law)

    Returns a Dataset (sublink × time) on the day, with the spin-up day before removed."""
    import pycomlink as pycl
    t0 = pd.Timestamp(day)
    lvl, step, var = link_level(R, cid, t0 - pd.Timedelta(spinup), t0 + pd.Timedelta('1D'), sublinks)
    lvl = lvl.isel(sublink_id=np.where(lvl.notnull().mean('time').values > .3)[0])
    blackout = xr.zeros_like(lvl, dtype=bool)
    if blackout_db is not None:
        lvl, blackout = fill_blackouts(lvl, blackout_db)
    trsl = (-lvl).interpolate_na('time', max_gap=pd.Timedelta(minutes=5 * step))
    n = max(3, int(round(pd.Timedelta(rsd_window) / pd.Timedelta(minutes=step))))
    if wet_method == 'gauge':
        rr, _, _ = gauge_near(R, cid, trsl.time.values[0], trsl.time.values[-1] + np.timedelta64(1, 'h'))
        k = int(pd.Timedelta(gauge_pad) / pd.Timedelta('5min'))
        rainy = (rr.fillna(0) > 0).astype(float).rolling(2 * k + 1, center=True, min_periods=1).max()
        wet1 = rainy.reindex(pd.DatetimeIndex(trsl.time.values), method='nearest').fillna(0).values > 0
        wet = xr.DataArray(np.broadcast_to(wet1, trsl.shape).copy(), coords=trsl.coords, dims=trsl.dims)
    else:
        wet = trsl.rolling(time=n, center=True, min_periods=max(2, n // 2)).std() > rsd_threshold
        wet = wet.where(trsl.notnull()).ffill('time').fillna(0).astype(bool)
        # a filled blackout is flat at the floor, so its std is low: it is the wettest part, keep it (± half a window) wet
        wet = wet | (blackout.astype(float).rolling(time=n, center=True, min_periods=1).max() > 0)
    baseline = pycl.processing.baseline.baseline_constant(trsl=trsl, wet=wet, n_average_last_dry=n_average_last_dry)
    A_obs = (trsl - baseline).clip(min=0)
    L_km = float(R.paths.loc[cid, 'length']) / 1000
    f = R.links.frequency.sel(cml_id=cid, sublink_id=lvl.sublink_id)
    pol = str(R.links.polarization.sel(cml_id=cid, sublink_id=lvl.sublink_id.values[0]).values)
    waa_da = xr.zeros_like(A_obs)
    for s in lvl.sublink_id.values:
        a = A_obs.sel(sublink_id=s)
        f_hz = float(f.sel(sublink_id=s)) * 1e6
        if waa == 'pastorek':
            w = pycl.processing.wet_antenna.waa_pastorek_2021_from_A_obs(A_obs=a.values, f_Hz=f_hz, pol=pol[0].upper(), L_km=L_km)
        elif waa == 'leijnse':
            w = pycl.processing.wet_antenna.waa_leijnse_2008_from_A_obs(A_obs=a.values, f_Hz=f_hz, pol=pol[0].upper(), L_km=L_km)
        elif waa == 'schleiss':
            w = pycl.processing.wet_antenna.waa_schleiss_2013(
                rsl=trsl.sel(sublink_id=s).values, baseline=baseline.sel(sublink_id=s).values,
                wet=wet.sel(sublink_id=s).values, waa_max=2.2, delta_t=step, tau=15)
        else:
            w = np.zeros(a.shape)
        waa_da.loc[dict(sublink_id=s)] = np.where(np.isfinite(a.values), np.clip(w, 0, a.values), np.nan)
    A = (A_obs - waa_da).clip(min=0)
    Rr = xr.concat([pycl.processing.k_R_relation.calc_R_from_A(
        A=A.sel(sublink_id=s), L_km=L_km, f_GHz=float(f.sel(sublink_id=s)) / 1000, pol=pol)
        for s in lvl.sublink_id.values], dim='sublink_id')
    out = xr.Dataset(dict(rsl=lvl, blackout=blackout, trsl=trsl, wet=wet, baseline=baseline, A_obs=A_obs,
                          waa=waa_da, A=A, R=Rr))
    out.attrs.update(cml_id=cid, step_min=step, variable=var, waa=str(waa), wet_method=wet_method, length_km=L_km)
    return out.sel(time=day_slice(day, var))


def hourly(series_or_da, step_min, how='mean'):
    """Mean rain rate (mm/h) per hour, labelled by the hour's end, from a rate series."""
    s = series_or_da.to_series() if hasattr(series_or_da, 'to_series') else series_or_da
    g = s.resample('1h', closed='right', label='right')
    return g.mean() if how == 'mean' else g.sum()


def radar_along_paths(day, cids):
    """MRMS hourly rain (mm) averaged along each path (poligrain GridAtLines): time × cml_id."""
    from analysis.v2.analysis import radar_on_paths
    return radar_on_paths(day, list(cids))


def chain_panel(ch, gauge=None, title='', gauge_label='ASOS, 5 min'):
    """Five stacked panels of one path through the chain."""
    s0 = ch.sublink_id.values[0]
    fig, axs = plt.subplots(5, 1, figsize=(14, 10), sharex=True,
                            gridspec_kw={'height_ratios': [1.3, .45, 1.1, 1.1, 1.2]})
    c = [CML_COL, '#7b3fa0', '#5f7385', '#a35a00']
    for i, s in enumerate(ch.sublink_id.values):
        axs[0].plot(ch.time, ch.trsl.sel(sublink_id=s), lw=.7, color=c[i], label=f'TRSL = −RSL, {s}')
        axs[0].plot(ch.time, ch.baseline.sel(sublink_id=s), lw=1.4, color='k', ls='--' if i else '-',
                    label='baseline' if i == 0 else None)
    axs[0].set_ylabel('dB')
    axs[0].legend(fontsize=8, ncol=3, loc='upper left')
    w = ch.wet.sel(sublink_id=s0).astype(float)
    axs[1].fill_between(ch.time, w, step='mid', color=RAIN_COL, alpha=.5, lw=0)
    axs[1].set_yticks([0, 1], ['dry', 'wet'])
    axs[1].set_ylabel('wet/dry')
    for i, s in enumerate(ch.sublink_id.values):
        axs[2].plot(ch.time, ch.A_obs.sel(sublink_id=s), lw=.7, color=c[i], label=f'A_obs {s}')
    axs[2].plot(ch.time, ch.waa.sel(sublink_id=s0), lw=1.2, color='k', label=f'wet antenna ({ch.attrs["waa"]})')
    axs[2].set_ylabel('dB')
    axs[2].legend(fontsize=8, ncol=3, loc='upper left')
    for i, s in enumerate(ch.sublink_id.values):
        axs[3].plot(ch.time, ch.A.sel(sublink_id=s), lw=.7, color=c[i], label=f'A rain {s}')
    axs[3].set_ylabel('dB')
    axs[3].legend(fontsize=8, ncol=3, loc='upper left')
    axs[4].plot(ch.time, ch.R.mean('sublink_id'), lw=.8, color=CML_COL, label='CML (mean of sublinks)')
    if gauge is not None:
        axs[4].fill_between(gauge.index, gauge.values, step='pre', color=GAUGE_COL, alpha=.3, lw=0, label=gauge_label)
    axs[4].set_ylabel('mm/h')
    axs[4].legend(fontsize=8, loc='upper left')
    _hours(axs[4])
    for ax, lab in zip(axs, ['1 · level and baseline', '2 · wet/dry (rolling std)', '3 · observed attenuation and wet antenna',
                             '4 · rain attenuation', '5 · rain rate (k-R)']):
        ax.set_title(lab, loc='left', fontsize=9)
    fig.suptitle(title, y=1.0)
    plt.tight_layout()
    return fig


# ============================================================================ overview plots

def coverage_plot(R, daily):
    asos_day = R.asos.rainfall_amount.where(R.asos.rainfall_flag == 0).notnull().resample(time='1D').any().sum('id').to_series()
    fig, axs = plt.subplots(3, 1, figsize=(15, 8), sharex=True, gridspec_kw={'height_ratios': [1.2, 1, 1]})
    axs[0].plot(daily.index, daily['C5'], color=BAND_COL['C5'], lw=1, label=BAND_NAME['C5'])
    axs[0].set_ylabel('paths')
    axs[0].set_title('5 GHz paths reporting per day', loc='left')
    for b in ['V60', 'K24']:
        axs[1].plot(daily.index, daily[b], color=BAND_COL[b], lw=1.2, label=BAND_NAME[b])
    axs[1].set_ylabel('paths')
    axs[1].legend(fontsize=8, loc='upper left')
    axs[1].set_title('mm-wave paths reporting per day', loc='left')
    ghcn_day = R.ghcn.dropna(subset=['precipitation_mm']).groupby('date').ghcn_id.nunique()
    ghcn_day.index = pd.to_datetime(ghcn_day.index)
    axs[2].plot(ghcn_day.index, ghcn_day, color=GAUGE_COL, lw=.8, label='GHCN-Daily stations with rain')
    axs[2].plot(asos_day.index, asos_day, color='k', label='ASOS stations with rain data')
    axs[2].legend(fontsize=8, loc='upper right')
    axs[2].set_ylabel('stations')
    axs[2].set_title('rain gauges reporting per day', loc='left')
    for i, ax in enumerate(axs):
        shade_eras(ax, label_y=(150 if i == 0 else None))
    plt.tight_layout()
    return fig


def stamps_per_day(R):
    t = pd.DatetimeIndex(R.links.time.values)
    per_day = pd.Series(1, index=t).resample('1D').sum()
    fig, ax = plt.subplots(figsize=(15, 2.6))
    ax.step(per_day.index, per_day.replace(0, np.nan), where='post', color='k')
    ax.set_yscale('log')
    ax.set_yticks([24, 60, 240, 1440], ['24 (hourly)', '60 (1 h of minutes)', '240 (6 min)', '1440 (every minute)'])
    ax.minorticks_off()
    shade_eras(ax)
    ax.set_title('Stamps per day in the link file', loc='left')
    plt.tight_layout()
    return fig


def band_figure(R):
    fig, axs = plt.subplots(1, 3, figsize=(15, 3.8))
    f = R.smeta.frequency / 1000
    axs[0].hist(f[f < 10], bins=40, color=BAND_COL['C5'])
    axs[0].set_title('5 GHz sublinks: carrier', loc='left')
    axs[0].set_xlabel('GHz')
    axs[1].hist(f[f > 20], bins=60, color=BAND_COL['V60'])
    axs[1].set_title('24 and 60 GHz sublinks: carrier', loc='left')
    axs[1].set_xlabel('GHz')
    rng = np.random.default_rng(0)
    for i, b in enumerate(BANDS):
        L = R.paths.loc[R.paths.band == b, 'length'] / 1000
        axs[2].scatter(i + rng.uniform(-.2, .2, len(L)), L, s=8, color=BAND_COL[b], alpha=.7)
        axs[2].plot([i - .3, i + .3], [L.median()] * 2, color='k', lw=1.5)
    axs[2].set_xticks([0, 1, 2], ['60 GHz', '24 GHz', '5 GHz'])
    axs[2].set_ylabel('path length (km)')
    axs[2].set_title('Path length by band (line: median)', loc='left')
    plt.tight_layout()
    return fig


def three_year_levels(R, examples):
    fig, axs = plt.subplots(len(examples), 1, figsize=(15, 2.4 * len(examples)), sharex=True)
    for ax, (b, c) in zip(axs, examples.items()):
        x = R.links.sel(cml_id=c, sublink_id='sublink_1')
        d = x.rsl.fillna(x.rsl_avg).to_series().resample('1D').agg(['median', 'min', 'max'])
        ax.fill_between(d.index, d['min'], d['max'], color=BAND_COL[b], alpha=.2, lw=0, label='daily min–max')
        ax.plot(d.index, d['median'], color=BAND_COL[b], lw=1, label='daily median')
        p = R.paths.loc[c]
        ax.set_title(f'cml {c} · {float(x.frequency)/1000:.1f} GHz · {p.length/1000:.1f} km', loc='left', fontsize=9)
        ax.set_ylabel('dBm')
        shade_eras(ax)
    axs[0].legend(fontsize=8, loc='lower left')
    plt.tight_layout()
    return fig


def nearest_asos(R, cid):
    lat, lon = midpoint(R, cid)
    d = hav(lat, lon, R.asos.lat.values, R.asos.lon.values)
    return str(R.asos.id.values[int(np.argmin(d))])


def rsl_week(R, cid, start, end):
    st = nearest_asos(R, cid)
    w = R.links.sel(cml_id=cid, time=slice(start, end))
    r = R.asos.rainfall_amount.where(R.asos.rainfall_flag == 0).sel(id=st, time=slice(start, end))
    r = r.resample(time='10min', closed='right', label='right').sum(min_count=1) * 6
    fig, axs = plt.subplots(2, 1, figsize=(15, 5), sharex=True, gridspec_kw={'height_ratios': [2, 1]})
    for s, c in [('sublink_1', BAND_COL['V60']), ('sublink_2', '#7b3fa0')]:
        axs[0].plot(w.time, w.rsl.sel(sublink_id=s), lw=.6, color=c,
                    label=f"{s}: {float(w.frequency.sel(sublink_id=s))/1000:.1f} GHz, direction {'AB'[int(s[-1]) - 1]}")
    axs[0].set_ylabel('RSL (dBm)')
    axs[0].legend(fontsize=8, loc='lower left')
    p = R.paths.loc[cid]
    axs[0].set_title(f'cml {cid} ({p.frequency/1000:.1f} GHz, {p.length/1000:.1f} km): 1-min RSL', loc='left')
    axs[1].bar(r.time, r, width=1 / 144, color=RAIN_COL)
    axs[1].set_ylabel(f'{st} rain (mm/h)')
    plt.tight_layout()
    return fig


def avg_max_example(R, cid, start, end):
    w = R.links.sel(cml_id=cid, sublink_id='sublink_1', time=slice(start, end))
    fig, ax = plt.subplots(figsize=(15, 3))
    ax.plot(w.time, w.rsl_max, color='#d97706', lw=.8, label='rsl_max (highest in the window)')
    ax.plot(w.time, w.rsl_avg, color=BAND_COL['V60'], lw=1, label='rsl_avg (average over the window)')
    ax.set_ylabel('dBm')
    ax.legend(fontsize=8, loc='lower left')
    p = R.paths.loc[cid]
    ax.set_title(f'cml {cid} ({p.frequency/1000:.1f} GHz, {p.length/1000:.1f} km): 6-min average and maximum', loc='left')
    plt.tight_layout()
    return fig


def dual_frequency(R, day, att):
    dual = R.paths[R.paths.bands.str.startswith('V60+')].index.tolist()
    show = [c for c in dual if float(att.sel(cml_id=c).notnull().mean()) > .1][:4]
    fig, axs = plt.subplots(1, len(show), figsize=(4.6 * len(show), 3.2), sharey=True, squeeze=False)
    for ax, c in zip(axs[0], show):
        for s in R.links.sublink_id.values:
            f = float(R.links.frequency.sel(cml_id=c, sublink_id=s))
            a = att.sel(cml_id=c, sublink_id=s)
            if np.isnan(f) or float(a.notnull().mean()) < .3:
                continue
            ax.plot(a.time, a, lw=1, color=BAND_COL['V60'] if f > 50000 else '#5f7385', label=f'{s[-1]}: {f/1000:.1f} GHz')
        ax.set_title(f"cml {c} · {R.paths.loc[c, 'length']/1000:.1f} km", fontsize=9, loc='left')
        ax.legend(fontsize=7)
        _hours(ax)
    axs[0, 0].set_ylabel('attenuation (dB)')
    fig.suptitle(f'{day}: the 60 GHz and 5 GHz radios of the same paths')
    plt.tight_layout()
    return fig, dual


# ============================================================================ rain-chain evaluation

def chain_day_totals(R, day, settings):
    """Day total (mm) of every mm-wave path on `day` under each chain setting {name: kwargs}, next to the nearest
    ASOS gauge and, on radar days, MRMS along the path."""
    att = attenuation_vs_prior(R, day)
    cids = mmwave_paths_on(R, att)
    has_radar = (R.radar_ev.day == day).any()
    rad = radar_along_paths(day, cids) if has_radar else None
    rows = []
    for c in cids:
        p, st, dkm = gauge_day(R, day, c)
        row = dict(cml_id=c, band=R.paths.loc[c, 'band'], GHz=round(R.paths.loc[c, 'frequency'] / 1000, 1),
                   km=round(R.paths.loc[c, 'length'] / 1000, 2), gauge=st, gauge_km=round(dkm, 1),
                   ASOS=round(p.sum() / 12, 1))
        if rad is not None:
            row['radar'] = round(float(rad.sel(cml_id=c).sum()), 1)
        for name, kw in settings.items():
            ch = rain_chain(R, c, day, sublinks=top_sublinks(R, att, c), **kw)
            row[name] = round(float(ch.R.mean('sublink_id').sum()) * ch.attrs['step_min'] / 60, 1)
        rows.append(row)
    return pd.DataFrame(rows).set_index('cml_id').sort_values('km')


def ratio_heatmap(tables, settings, ref='ASOS'):
    fig, axs = plt.subplots(1, len(tables), figsize=(7.5 * len(tables), 0.32 * max(len(t) for t in tables.values()) + 2),
                            squeeze=False)
    for ax, (day, t) in zip(axs[0], tables.items()):
        r = t[list(settings)].div(t[ref], axis=0)
        im = ax.imshow(np.log2(r.values.astype(float)), cmap='RdBu_r', vmin=-2, vmax=2, aspect='auto')
        ax.set_xticks(range(len(settings)), list(settings), rotation=30, ha='right', fontsize=8)
        ax.set_yticks(range(len(t)), [f'{c} · {g:g} GHz · {k:.1f} km' for c, g, k in zip(t.index, t.GHz, t.km)], fontsize=7)
        for i in range(r.shape[0]):
            for j in range(r.shape[1]):
                ax.text(j, i, f'{r.values[i, j]:.2f}', ha='center', va='center', fontsize=6.5)
        ax.set_title(f'{day}: link / reference day total', loc='left', fontsize=10)
        ax.grid(False)
    cb = plt.colorbar(im, ax=axs[0].tolist(), shrink=.6, ticks=[-2, -1, 0, 1, 2])
    cb.ax.set_yticklabels(['¼', '½', '1', '2', '4'])
    return fig


def hourly_comparison(R, day, cids, **chain_kw):
    has_radar = (R.radar_ev.day == day).any()
    rad = radar_along_paths(day, cids) if has_radar else None
    fig, axs = plt.subplots(len(cids), 1, figsize=(14, 2.6 * len(cids)), sharex=True, squeeze=False)
    att = attenuation_vs_prior(R, day)
    for ax, c in zip(axs[:, 0], cids):
        ch = rain_chain(R, c, day, sublinks=top_sublinks(R, att, c), **chain_kw)
        cml = hourly(ch.R.mean('sublink_id'), ch.attrs['step_min'])
        p, st, dkm = gauge_day(R, day, c)
        ph = hourly(p, 5)
        w = pd.Timedelta('20min')
        ax.bar(cml.index - w, cml.values, width=w, color=CML_COL, label='link (chain)')
        ax.bar(ph.index, ph.values, width=w, color=GAUGE_COL, label='nearest ASOS')
        if rad is not None:
            rr = rad.sel(cml_id=c).to_series()
            ax.bar(rr.index + w, rr.values, width=w, color=RADAR_COL, label='MRMS along the path')
        pp = R.paths.loc[c]
        ax.set_title(f'cml {c} · {pp.frequency/1000:.1f} GHz · {pp.length/1000:.1f} km · ASOS {st} {dkm:.0f} km away',
                     loc='left', fontsize=9)
        ax.set_ylabel('mm/h')
    axs[0, 0].legend(fontsize=8, ncol=3, loc='upper left')
    _hours(axs[-1, 0])
    fig.suptitle(f'{day}: hourly rain, labelled by the hour\'s end')
    plt.tight_layout()
    return fig


def gamma_vs_rain(R, days, ax=None):
    """Hourly specific attenuation (dB/km, chain's A after wet antenna) against hourly rain at the nearest ASOS
    gauge, 60 GHz paths, with the ITU-R P.838 curves. The gauge is kilometres away: expect scatter."""
    from analysis.itu_rainrate import itu_k_alpha
    rows = []
    for day in days:
        att = attenuation_vs_prior(R, day)
        for c in mmwave_paths_on(R, att, bands=('V60',)):
            p, st, dkm = gauge_day(R, day, c)
            ch = rain_chain(R, c, day, sublinks=top_sublinks(R, att, c))
            a = hourly(ch.A.mean('sublink_id'), ch.attrs['step_min'])
            df = pd.DataFrame({'A': a, 'R': hourly(p, 5)}).dropna()
            df['gamma'] = df.A / ch.attrs['length_km']
            df['day'] = day
            rows.append(df)
    H = pd.concat(rows)
    if ax is None:
        _, ax = plt.subplots(figsize=(8, 5.5))
    for day, m in zip(days, ['o', '^']):
        d = H[H.day == day]
        ax.scatter(d.R, d.gamma, s=14, marker=m, alpha=.5, label=day)
    x = np.linspace(0, H.R.max() * 1.05, 100)
    for f in [60, 68]:
        k, a = itu_k_alpha(f, 'V')
        ax.plot(x, k * x ** a, lw=2, label=f'ITU-R P.838, {f} GHz V')
    ax.set_xlabel('nearest ASOS rain rate (mm/h, hourly)')
    ax.set_ylabel('specific attenuation (dB/km)')
    ax.legend(fontsize=8)
    plt.tight_layout()
    return H


def reference_monthly(R):
    """Daily rain: GHCN-Daily median (CoCoRaHS and COOP gauges, days ending in the morning) against the ASOS mean
    (UTC days). The day boundaries differ, so single days scatter; months agree."""
    g = R.ghcn.dropna(subset=['precipitation_mm']).groupby('date').precipitation_mm.median()
    g.index = pd.to_datetime(g.index)
    ad_ = R.asos.rainfall_amount.where(R.asos.rainfall_flag == 0).resample(time='1D').sum(min_count=1200).mean('id').to_series()
    dd = pd.DataFrame({'GHCN median': g, 'ASOS mean': ad_}).dropna()
    fig, axs = plt.subplots(1, 2, figsize=(15, 4), gridspec_kw={'width_ratios': [3, 1]})
    m = dd.resample('MS').sum()
    axs[0].bar(m.index - pd.Timedelta('6D'), m['GHCN median'], width=12, color=GAUGE_COL, label='GHCN-Daily median')
    axs[0].bar(m.index + pd.Timedelta('6D'), m['ASOS mean'], width=12, color='k', label='ASOS mean')
    axs[0].legend()
    axs[0].set_ylabel('mm / month')
    axs[0].set_title('Monthly rain on days both cover', loc='left')
    axs[1].scatter(dd['ASOS mean'], dd['GHCN median'], s=6, alpha=.5)
    mx = dd.max().max()
    axs[1].plot([0, mx], [0, mx], 'k--', lw=.8)
    axs[1].set_xlabel('ASOS mean (mm/day)')
    axs[1].set_ylabel('GHCN median (mm/day)')
    axs[1].set_title('Daily totals', loc='left')
    plt.tight_layout()
    return fig


def radar_days_grid(R):
    fig, axs = plt.subplots(2, 5, figsize=(17, 6.5))
    for ax, f in zip(axs.flat, R.radar_ev.file):
        rd = xr.open_dataset(R.data / 'weather/radar' / f)
        tot = rd.rainfall_amount_1h.sum('time_1h', min_count=1)
        draw_boro(ax, R)
        ax.pcolormesh(rd.lon, rd.lat, tot, cmap='Blues' if 'rain' in f else 'Purples', shading='nearest', alpha=.8)
        ax.set_title(f[-17:-3].replace('_', ' ') + f'  ({float(tot.mean()):.0f} mm)', fontsize=9)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle('MRMS day totals (liquid equivalent; in brackets the grid mean) on the 10 radar days')
    plt.tight_layout()
    return fig
