"""Build openmesh_rain_days.html: an interactive page with a record-overview tab and a map of two rain days
(links, rain gauges, MRMS radar), from public data only.

    python tutorials/v2/rain_days_map/build_map.py      # writes openmesh_rain_days.html next to this file

Inputs, all downloaded on the first run:
  - the OpenMesh v2 record (Zenodo 10.5281/zenodo.23283445): links, ASOS, GHCN-Daily, MRMS radar days;
  - the Weather Underground PWS of the v1 record (Zenodo 10.5281/zenodo.17508286, CC BY-NC 4.0), shown on
    days inside its period (2023-10-29 to 2024-07-01). v2 has no PWS, so later days show ASOS and radar only;
  - Natural Earth 10 m land for the background (cartopy downloads it once).
The page holds its data inline (a few MB), so it opens offline; it needs internet only for d3 from cdnjs.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import shapely.geometry as sg
import xarray as xr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import showcase as S  # noqa: E402  (tutorials/v2/showcase.py; puts src/ on the path)
from analysis import datasets as D  # noqa: E402
from analysis.netcdf_utils import load_pws_grouped  # noqa: E402

DAYS = ['2024-03-23', '2025-10-30']      # rain days of the record with MRMS: one inside the v1 PWS period, one after
PWS_MAX_MM_5MIN = 30.0                   # plausibility cap for a 5-min PWS amount


def ints(x, scale):
    return [None if not np.isfinite(v) else int(round(v * scale)) for v in np.asarray(x, float)]


def v1_pws():
    """The v1 WU PWS as one (id, time) dataset of 5-min rain (mm): downloaded from Zenodo 17508286 when missing."""
    path = D.paths('v1').pws
    if not Path(path).exists():
        from fetch_data.OpenMesh.openmesh import run_pws_wu_pipeline
        run_pws_wu_pipeline()
    groups = load_pws_grouped(path, verbose=False)
    rain, lat, lon = {}, {}, {}
    for sid, ds in groups.items():
        r = ds['rainfall_amount'].squeeze(drop=True).to_series()
        r = r[(r >= 0) & (r <= PWS_MAX_MM_5MIN)]
        rain[sid] = r.resample('5min', closed='right', label='right').sum(min_count=1)
        lat[sid], lon[sid] = float(ds['lat'].squeeze()), float(ds['lon'].squeeze())
    df = pd.DataFrame(rain)
    da = xr.DataArray(df.values.T, dims=('id', 'time'), coords=dict(id=list(df.columns), time=df.index.values))
    return xr.Dataset(dict(rainfall=da), coords=dict(latitude=('id', [lat[i] for i in df.columns]),
                                                     longitude=('id', [lon[i] for i in df.columns])))


def background(R):
    feats = []
    for g in R.land:                                   # Natural Earth land around the city
        g = sg.mapping(sg.polygon.orient(g.simplify(0.002), sign=-1.0))   # d3 wants clockwise exteriors
        coords = json.loads(json.dumps(g['coordinates']), parse_float=lambda v: round(float(v), 4))
        feats.append(dict(type='Feature', properties=dict(name='', land=True), geometry=dict(type=g['type'], coordinates=coords)))
    return feats


def static_links(R):
    out = []
    for c in R.links.cml_id.values.astype(str):
        p = R.paths.loc[c]
        out.append(dict(id=c, f=round(p.frequency / 1000, 1), b={'V60': 'V', 'K24': 'K', 'C5': 'C'}[p.band],
                        len=round(p.length), p=[round(float(p[k]), 5) for k in ['site_0_lat', 'site_0_lon', 'site_1_lat', 'site_1_lon']]))
    return out


def one_day(R, day):
    var = S.signal_var(day)
    att = S.attenuation_vs_prior(R, day)
    times = pd.DatetimeIndex(att.time.values)
    freq = R.links.frequency
    links = []
    for c in att.cml_id.values.astype(str):
        subs = []
        for s in att.sublink_id.values:
            a = att.sel(cml_id=c, sublink_id=s)
            if float(a.notnull().mean()) < .3:
                continue
            subs.append(dict(s=str(s)[-1], f=round(float(freq.sel(cml_id=c, sublink_id=s)) / 1000, 1), a=ints(a.values, 10)))
        if not subs:
            continue
        o = dict(id=c, subs=subs)
        top = S.top_sublinks(R, att, c)
        if R.paths.loc[c, 'band'] != 'C5' and top:
            ch = S.rain_chain(R, c, day, sublinks=top)                    # defaults: rolling-std wet/dry, Schleiss WAA
            r = ch.R.mean('sublink_id').reindex(time=att.time)
            o['r'] = ints(r.values, 10)                                  # mm/h × 10
        links.append(o)
    t0 = pd.Timestamp(day)
    pws = []
    grid = pd.date_range(t0 + pd.Timedelta('5min'), t0 + pd.Timedelta('1D'), freq='5min')
    if t0 < pd.Timestamp(D.V1_PERIOD[1]):
        pr = R.pws.rainfall.reindex(time=grid)
        pws = [dict(id=str(i), lat=round(float(R.pws.latitude.sel(id=i)), 4), lon=round(float(R.pws.longitude.sel(id=i)), 4),
                    r=ints(pr.sel(id=i).values, 100))
               for i in R.pws.id.values if float(pr.sel(id=i).notnull().mean()) >= .8]
        note = (f'PWS: {len(pws)} Weather Underground stations of the v1 record (Zenodo 17508286), '
                '5-min rain, raw amounts (negative or above 30 mm per 5 min dropped).')
    else:
        note = ('No PWS on this day: only the v1 record (2023-10-29 to 2024-07-01) has Weather Underground stations. '
                'References: ASOS gauges and MRMS radar.')
    sl = slice(t0 + pd.Timedelta('1min'), t0 + pd.Timedelta('1D'))
    a = R.asos.rainfall_amount.sel(time=sl).where(R.asos.rainfall_flag.sel(time=sl) == 0)
    a5 = a.resample(time='5min', closed='right', label='right').sum(min_count=1).load()
    asos = [dict(id=str(i), lat=round(float(R.asos.lat.sel(id=i)), 4), lon=round(float(R.asos.lon.sel(id=i)), 4),
                 r=ints(a5.sel(id=i).values, 100)) for i in R.asos.id.values]
    radar = None
    f = R.radar_ev.loc[R.radar_ev.day == day, 'file']
    if len(f):
        rd = xr.open_dataset(R.data / 'weather/radar' / f.iloc[0])
        h = rd.rainfall_amount_1h.load()
        radar = dict(lat=[round(float(v), 4) for v in rd.lat.values], lon=[round(float(v), 4) for v in rd.lon.values],
                     h=[ints(h.isel(time_1h=k).values.ravel(), 10) for k in range(h.sizes['time_1h'])])
    print(day, len(links), 'paths,', sum('r' in o for o in links), 'with rain rate,', len(pws), 'PWS')
    return dict(day=day, var=var, step=1 if var == 'rsl' else 6, t0=str(times[0]), n=len(times),
                links=links, pws=pws, asos=asos, radar=radar, note=note)


def overview(R):
    """Record overview tab: key numbers, sampling periods, coverage per day and the metadata tables."""
    p = R.paths
    daily = S.paths_reporting_daily(R)
    pws_day = R.pws.rainfall.notnull().resample(time='1D').any().sum('id').to_series()
    pws_day = pws_day[pws_day.index < pd.Timestamp(D.V1_PERIOD[1])]
    asos_day = R.asos.rainfall_amount.where(R.asos.rainfall_flag == 0).notnull().resample(time='1D').any().sum('id').to_series()
    gauges = pd.DataFrame({'pws': pws_day, 'asos': asos_day}).reindex(daily.index)
    t = pd.DatetimeIndex(R.links.time.values)
    vol = S.values_per_year(R)
    ok = R.asos.rainfall_amount.where(R.asos.rainfall_flag == 0)
    asos_year = ok.groupby('time.year').sum(min_count=1).to_pandas().T.round(0)
    asos_cov = (ok.notnull().groupby('time.year').mean().to_pandas().T * 100).round(0)
    sens = S.sensor_table(R).reset_index()
    sens = pd.concat([sens, pd.DataFrame([dict(
        sensor='WU PWS', file='pws_wu_os.nc (v1 record)', size=f"{R.pws.sizes['id']} stations",
        period=f'{D.V1_PERIOD[0]} → {D.V1_PERIOD[1]}', step='5 min', variables='rain',
        source='Zenodo v1 (17508286)')])], ignore_index=True)
    var = S.variables_table(R.links).reset_index()
    files = S.file_inventory(R).reset_index()
    radar_mb = round(sum(f.stat().st_size for f in (R.data / 'weather/radar').glob('*.nc')) / 1e6, 1)
    files = pd.concat([files[~files.file.str.contains('radar/openmesh_radar_')], pd.DataFrame(
        [dict(file='data/weather/radar/openmesh_radar_*.nc (20 files: MRMS and KOKX, 10 days)', MB=radar_mb)])],
        ignore_index=True)
    ex = R.smeta[R.smeta.cml_id == '4'][['cml_id', 'sublink_id', 'frequency', 'length', 'direction', 'polarization']]
    rad = R.radar_ev[['day', 'kind', 'asos_median_mm', 'radar_mean_mm', 'radar_max_mm']]
    tab = lambda df: dict(cols=[str(c) for c in df.columns], rows=df.astype(object).where(df.notna(), None).values.tolist())
    dual = p[p.bands.str.contains('[+]')]
    return dict(
        facts=dict(paths=len(p), sublinks=len(R.smeta), stamps=len(t), start=f'{t[0]:%Y-%m-%d}', end=f'{t[-1]:%Y-%m-%d}',
                   bands={b: int((p.band == b).sum()) for b in S.BANDS},
                   subs={b: int((R.smeta.frequency.map(D.band_of) == b).sum()) for b in S.BANDS},
                   dual=len(dual), dual_kinds=dual.bands.value_counts().to_dict(),
                   asos=int(R.asos.sizes['id']), ghcn=len(R.ghcn_st), radar=len(R.radar_ev), metar=len(R.metar),
                   pws=int(R.pws.sizes['id']), pws_end=D.V1_PERIOD[1],
                   median_len={b: round(float(p.loc[p.band == b, 'length'].median())) for b in S.BANDS}),
        eras=[dict(a=a, b=b, label=l) for a, b, l, _ in S.ERAS],
        daily=dict(t0=f'{daily.index[0]:%Y-%m-%d}', V=daily.V60.astype(int).tolist(), K=daily.K24.astype(int).tolist(),
                   C=daily.C5.astype(int).tolist(),
                   pws=[None if not np.isfinite(v) else int(v) for v in gauges.pws.values],
                   asos=[None if not np.isfinite(v) else int(v) for v in gauges.asos.values]),
        sensors=tab(sens), files=tab(files), variables=tab(var),
        volume=tab(vol.reset_index().rename(columns=str)),
        asos_year=tab(asos_year.reset_index().rename(columns=str)), asos_cov=tab(asos_cov.reset_index().rename(columns=str)),
        sublink_example=tab(ex), radar=tab(rad))


def main():
    S.style()
    R = S.load()                       # the v2 record, downloaded on the first run
    R.pws = v1_pws()                   # the v1 WU PWS, downloaded on the first run
    data = dict(links=static_links(R), boro=background(R), days=[one_day(R, d) for d in DAYS], ov=overview(R))
    page = (HERE / 'template.html').read_text().replace(
        '__DATA__', json.dumps(data, separators=(',', ':')).replace('</', '<\\/'))
    out = HERE / 'openmesh_rain_days.html'
    out.write_text(page)
    print(out.relative_to(D.REPO_ROOT), round(out.stat().st_size / 1e6, 1), 'MB')


if __name__ == '__main__':
    main()
