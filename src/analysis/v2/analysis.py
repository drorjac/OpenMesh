"""Small analysis helpers: one level series per link across the sampling eras, rain-induced attenuation, nearest
gauge, radar along a link, lagged correlation."""
import numpy as np
import pandas as pd

from analysis import cml_baseline as CB, datasets as D
from analysis.itu_rainrate import rain_rate
from fetch_data.mrms import haversine_m


def haversine(lat0, lon0, lat1, lon1):
    """Distance in metres (fetch_data.mrms.haversine_m)."""
    return haversine_m(lat0, lon0, lat1, lon1)


def link_level(ds, cml_id, sublink="sublink_1"):
    """One series per link and direction: rsl where it exists (8 s era, 1 min), else rsl_avg
    (later stamps); datasets.signal_level of the selection."""
    return D.signal_level(ds.sel(cml_id=cml_id, sublink_id=sublink)).to_series().dropna()


def day_of(series, day):
    """The part of a time series inside one UTC day (empty, not an error, when the day has no data)."""
    d = pd.Timestamp(day).normalize()
    return series[(series.index >= d) & (series.index < d + pd.Timedelta("1D"))]


attenuation = CB.attenuation_rollmed          # rolling-median baseline minus level, dB
hourly_attenuation = CB.hourly_attenuation


def nearest(stations, lat, lon, k=1):
    """stations: DataFrame with lat / lon columns. Returns the k nearest with distance_m."""
    d = haversine(lat, lon, stations.lat.values, stations.lon.values)
    o = np.argsort(d)[:k]
    return stations.iloc[o].assign(distance_m=d[o])


def radar_along_link(da, lat0, lon0, lat1, lon1, n=20):
    """Mean of a gridded field (time, lat, lon) over the cells crossed by the straight path, as a time series."""
    lats, lons = np.linspace(lat0, lat1, n), np.linspace(lon0, lon1, n)
    cells = {(float(da.lat.sel(lat=a, method="nearest")), float(da.lon.sel(lon=b, method="nearest")))
             for a, b in zip(lats, lons)}
    tdim = [d for d in da.dims if d.startswith("time")][0]
    vals = [da.sel(lat=a, lon=b).to_series() for a, b in cells]
    return pd.concat(vals, axis=1).mean(axis=1).rename_axis("time") if vals else pd.Series(dtype=float)


def xcorr_lags(a, b, lags):
    """Pearson correlation of a(t) with b(t + lag) for each lag, in steps of the common index."""
    out = []
    for lag in lags:
        bb = b.shift(-lag)
        ok = a.notna() & bb.notna()
        good = ok.sum() > 30 and a[ok].std() > 0 and bb[ok].std() > 0
        with np.errstate(invalid="ignore", divide="ignore"):
            out.append(np.corrcoef(a[ok], bb[ok])[0, 1] if good else np.nan)
    return pd.Series(out, index=lags)


def link_rain(day, cml_ids, wet_window="1h", baseline_window="6h"):
    """Rain rate (mm/h) of sublink_1 of the given paths, minute by minute, from the day before to the day after, by the
    OpenSense chain: wet when a gauge records rain within `wet_window`; baseline = median of the dry minutes over the
    past `baseline_window`, held through wet spells; attenuation = baseline - level; rain from the ITU-R P.838-3 power
    law (analysis.itu_rainrate). Returns (level, wet, rain) as time x cml_id DataArrays. Minute data only (to 2025-04-21)."""
    import xarray as xr
    from . import io
    d = pd.Timestamp(day)
    ds = io.open_links()                       # not closed: xarray shares the handle with the caller's
    x = ds.sel(cml_id=list(cml_ids), sublink_id="sublink_1",
               time=slice(d - pd.Timedelta("1D"), d + pd.Timedelta("2D"))).load()
    level = x.rsl.fillna(x.rsl_avg)
    gauge = io.asos().rainfall_amount.max("id").sel(time=level.time).load()
    n = int(pd.Timedelta(wet_window) / pd.Timedelta("1min"))
    wet = gauge.fillna(0).rolling(time=2 * n + 1, center=True, min_periods=1).max() > 0
    m = int(pd.Timedelta(baseline_window) / pd.Timedelta("1min"))
    base = level.where(~wet).rolling(time=m, min_periods=30).median().where(~wet).ffill("time").bfill("time")
    A = (base - level).clip(min=0)
    R = xr.zeros_like(A) * np.nan
    for c in A.cml_id.values:
        q = x.sel(cml_id=c)
        R.loc[dict(cml_id=c)] = rain_rate(A.sel(cml_id=c).values, float(q.length), float(q.frequency),
                                          str(q.polarization.values))
    return level, wet, R


def radar_on_paths(day, cml_ids, kind="rain"):
    """MRMS hourly rain of one radar day averaged along each path (poligrain GridAtLines): time x cml_id, mm per hour."""
    import poligrain as plg
    from . import io
    r = io.radar(kind, day).rainfall_amount_1h.rename(lat="y", lon="x", time_1h="time")
    lon2, lat2 = np.meshgrid(r.x.values, r.y.values)
    r = r.assign_coords(lon=(("y", "x"), lon2), lat=(("y", "x"), lat2))
    lines = io.open_links().sel(cml_id=list(cml_ids), sublink_id="sublink_1")[["rsl"]].isel(time=0, drop=True)
    return plg.spatial.GridAtLines(r, lines, use_lon_lat=True)(r)


def rain_accumulation(days, pick=None, min_length=800, max_dry_std=1.5):
    """Day totals of rain on radar days from the links, the radar along the same paths, the ASOS gauges and GHCN.
    Paths: `pick` (a list of cml_id), or the 60 GHz paths of at least `min_length` m with 90 % of the day's minutes
    and at most `max_dry_std` dB of noise when dry. Returns (table, per-day results for plots.accumulation)."""
    from . import io
    ds = io.open_links()
    f1 = ds.frequency.sel(sublink_id="sublink_1")
    cand = ds.cml_id.values[((f1 > 50_000) & (ds.length >= min_length)).values]
    gauges = io.asos().rainfall_amount.load()
    g = pd.read_csv(io.data_dir() / "data" / "weather" / "ghcn" / "ghcn_daily.csv", parse_dates=["day_start_utc", "day_end_utc"])
    res, rows = {}, {}
    for day in days:
        d = pd.Timestamp(day); w = slice(d, d + pd.Timedelta("1439min"))
        level, wet, R = link_rain(day, list(pick) if pick else cand)
        Rd = R.sel(time=w)
        ok = Rd.notnull().mean("time") >= 0.9
        if not pick:
            ok = ok & ~(level.where(~wet).std("time") > max_dry_std)
        ids = list(Rd.cml_id.values[ok.values])
        link_mm = Rd.sel(cml_id=ids).sum("time") / 60
        rad = radar_on_paths(day, ids)
        q = g[(g.day_end_utc > d) & (g.day_start_utc < d + pd.Timedelta("1D"))].copy()
        q["overlap"] = q.day_end_utc.clip(upper=d + pd.Timedelta("1D")) - q.day_start_utc.clip(lower=d)
        ghcn = q.sort_values("overlap").groupby("ghcn_id").tail(1).precipitation_mm
        ga = gauges.sel(time=w)
        ga = ga.sel(id=[i for i in ga.id.values if int(ga.sel(id=i).notnull().sum()) >= 1200])   # gauges with the day
        res[day] = dict(R=Rd.sel(cml_id=ids), link_mm=link_mm, rad=rad, rad_mm=rad.sum("time"), asos=ga, ghcn=ghcn)
        rows[day] = {"paths": ", ".join(ids), "links, median (mm)": round(float(link_mm.median()), 1),
                     "radar along the paths (mm)": round(float(rad.sum("time").median()), 1),
                     f"ASOS, median (mm)": round(float(ga.sum("time").median()), 1),
                     "GHCN, median (mm)": round(float(ghcn.median()), 1)}
    return pd.DataFrame(rows), res


def outages(days, heavy=10):
    """Share of minutes without a value (sublink_1 of the paths alive that day), per band and rain class at the
    gauges (highest 10-min rate): dry, light (< `heavy` mm/h), heavy (>= `heavy`). Minute data only."""
    from . import io
    ds = io.open_links()
    f1 = ds.frequency.sel(sublink_id="sublink_1")
    g = io.asos().rainfall_amount.max("id")
    rows = []
    for day in days:
        d = pd.Timestamp(day); w = slice(d, d + pd.Timedelta("1439min"))
        rr = g.sel(time=w).to_series().rolling(10, min_periods=5).sum() * 6     # 10-min rate: a gauge tip is 0.254 mm
        for b, (lo, hi) in {"V60": (50_000, 100_000), "K24": (20_000, 30_000), "C5": (0, 10_000)}.items():
            x = ds.isel(cml_id=((f1 >= lo) & (f1 < hi)).values).sel(sublink_id="sublink_1", time=w)
            lvl = x.rsl.fillna(x.rsl_avg).load()
            lvl = lvl.sel(cml_id=lvl.notnull().mean("time") > 0.5)
            if not lvl.sizes["cml_id"]:
                continue
            r = rr.reindex(lvl.time.values).fillna(0).values
            miss = lvl.isnull().values
            share = lambda m: f"{miss[:, m].mean():.1%}" if m.any() else ""
            rows.append({"day": day, "band": b, "paths": lvl.sizes["cml_id"], "dry": share(r == 0),
                         f"light (< {heavy} mm/h)": share((r > 0) & (r < heavy)), f"heavy (≥ {heavy} mm/h)": share(r >= heavy),
                         "heavy-rain minutes": int((r >= heavy).sum())})
    return pd.DataFrame(rows).set_index(["day", "band"])
