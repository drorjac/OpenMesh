"""KOKX (Upton, NY) NEXRAD Level-3 products (AWS unidata-nexrad-level3 bucket).

KOKX (~90 km east of the links) provides dual-pol radar reflectivity and hydrometeor
classification complementary to MRMS. The 0.5° tilt is ~1–1.5 km above ground over the links.

Products: N0B (reflectivity dBZ), N0X (differential reflectivity ZDR dB), N0C (correlation
coefficient), all of the 0.5° tilt; HHC (hybrid hydrometeor classification: per gate, the
lowest tilt usable there, not always 0.5°). 0.25 km gates.

Two ways to use it:

* raw scans: `read_scan(product, time)` downloads the scan nearest `time` and returns
  the polar field (azimuth × range); `scan_lonlat(scan)` gives cell-edge lon/lat for
  plotting it on a map.
* samples: `fetch_window(start, end)` caches, for every scan (one per 10 min), the
  values at 5 points along each CML path of a dataset (v1 or v2, default: the active
  one) and on a 0.01° grid over the city; `load(start, end, product)` reads them back.

Usage::

    from fetch_data.nexrad import kokx
    scan = kokx.read_scan("N0B", "2024-03-23 12:00")      # one raw scan
    kokx.fetch_window("2024-03-23", "2024-03-24")          # samples, cached
    df = kokx.load("2024-03-23", "2024-03-24", "N0B")      # (t, key, pt, value)
"""

from __future__ import annotations

import io
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests

log = logging.getLogger(__name__)

BUCKET = "https://unidata-nexrad-level3.s3.amazonaws.com/"
SITE = "OKX"
PRODUCTS = ("HHC", "N0B", "N0X", "N0C")
STEP = "10min"

# HHC class codes as stored in the product (NOAA Level-3 product 177). 0 is information:
# below the reflectivity threshold (no echo), not missing data. Codes are kept as fetched.
HYDRO_LEGEND = {
    0: "below threshold (no echo)", 10: "biological", 20: "ground clutter", 30: "ice crystals",
    40: "dry snow", 50: "wet snow", 60: "light/moderate rain", 70: "heavy rain", 80: "big drops",
    90: "graupel", 100: "hail (possibly with rain)", 110: "large hail", 120: "giant hail",
    140: "unknown", 150: "range folded"
}



def grid_axes():
    """(lat, lon) of the sampling grid: the cell centres of the MRMS NYC grid
    (`fetch_data.mrms.Grid.from_domain(NYC)`, 0.01°), so KOKX and MRMS share cells."""
    from fetch_data.mrms import NYC, Grid
    g = Grid.from_domain(NYC)
    return np.asarray(g.lat, float), np.asarray(g.lon, float)


def _get_cache_dir() -> Path:
    """NEXRAD cache location: dataset/raw/radar/nexrad/."""
    from fetch_data.config import RAW_DIR
    cache = RAW_DIR / "radar" / "nexrad"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def link_points(dataset: Optional[str] = None) -> pd.DataFrame:
    """Sample points (key, pt, lat, lon): 5 points along each CML path of `dataset`
    ('v1' / 'v2', default: the active one; key = cml_id) and the 0.01° city grid (key = 'grid')."""
    rows = []
    try:
        from analysis import datasets as D
        meta = D.links_metadata(dataset)
    except (ImportError, FileNotFoundError) as e:
        log.warning(f"no link metadata ({e}); sampling the grid only")
        meta = pd.DataFrame(columns=["cml_id"])

    for _, row in meta.drop_duplicates(subset=["cml_id"]).iterrows():
        key = str(row["cml_id"])
        for i, t in enumerate(np.linspace(0, 1, 5)):  # 5 points per link
            lat = row["site_0_lat"] + t * (row["site_1_lat"] - row["site_0_lat"])
            lon = row["site_0_lon"] + t * (row["site_1_lon"] - row["site_0_lon"])
            rows.append((key, i, lat, lon))

    la, lo = grid_axes()
    for i, (a, b) in enumerate((a, b) for a in la for b in lo):
        rows.append(("grid", i, a, b))

    return pd.DataFrame(rows, columns=["key", "pt", "lat", "lon"])


def _list(product: str, hour: pd.Timestamp) -> Optional[list[str]]:
    """Keys in the bucket for the product hour; None when the listing failed."""
    pre = f"{SITE}_{product}_{hour:%Y_%m_%d_%H}"
    for k in range(3):
        try:
            r = requests.get(BUCKET, params={"list-type": "2", "prefix": pre, "max-keys": "200"}, timeout=30)
            r.raise_for_status()
            return re.findall(r"<Key>([^<]+)</Key>", r.text)
        except Exception as e:
            if k < 2:
                time.sleep(1 + k)
            else:
                log.warning(f"Failed to list {product} {hour}: {e}")
    return None


def _key_time(key: str) -> pd.Timestamp:
    """Extract valid time from key."""
    return pd.to_datetime(key[-19:], format="%Y_%m_%d_%H_%M_%S")


def _read(key: str, tries: int = 3) -> Optional[dict]:
    """Download and decode one NEXRAD Level-3 file."""
    from metpy.io import Level3File

    for k in range(tries):
        try:
            r = requests.get(BUCKET + key, timeout=45)
            r.raise_for_status()
            f = Level3File(io.BytesIO(r.content))
            sb = f.sym_block[0][0]
            raw = np.asarray(sb["data"])

            # HHC stores class codes directly; others need map_data conversion
            if key.split("_")[1] == "HHC":
                val = raw.astype(np.float32)
            else:
                val = np.asarray(f.map_data(raw), dtype=np.float32)

            return {
                "t": _key_time(key),
                "product": key.split("_")[1],
                "data": val,
                "az": np.asarray(sb["start_az"], dtype=float),
                "az_end": np.asarray(sb["end_az"], dtype=float),
                "gate_km": float(f.max_range) / raw.shape[1],
                "rlat": float(f.lat),
                "rlon": float(f.lon)
            }
        except Exception as e:
            if k < tries - 1:
                time.sleep(1 + k)
            else:
                log.debug(f"Failed to read {key}: {e}")
    return None


def read_scan(product: str, when) -> Optional[dict]:
    """The raw scan of `product` nearest to `when` (UTC, within ±30 min), not cached.

    Returns a dict: t (scan time), product, data (azimuth × gate; dBZ for N0B, dB for
    N0X, unitless for N0C, class code for HHC; NaN = below threshold, i.e. no echo),
    az / az_end (start / end azimuth of each radial, °), gate_km, rlat / rlon (radar).
    None when no scan is found."""
    when = pd.Timestamp(when)
    keys = []
    for hour in (when.floor("h") - pd.Timedelta("1h"), when.floor("h"), when.floor("h") + pd.Timedelta("1h")):
        keys += _list(product, hour) or []
    if not keys:
        return None
    s = pd.Series(keys, index=[_key_time(k) for k in keys])
    dt = abs(s.index - when)
    if dt.min() > pd.Timedelta("30min"):
        return None
    return _read(s.iloc[int(np.argmin(dt))])


def scan_lonlat(scan: dict, max_km: Optional[float] = None):
    """Cell-edge (lon, lat) arrays (azimuth+1 × gate+1) of a scan, for `pcolormesh`,
    and the data cropped to `max_km` from the radar: (lon, lat, data)."""
    data = scan["data"]
    n = data.shape[1] if max_km is None else min(data.shape[1], int(np.ceil(max_km / scan["gate_km"])))
    data = data[:, :n]
    order = np.argsort(scan["az"])
    az = scan["az"][order]
    data = data[order]
    az_edges = np.radians(np.append(az, az[0] + 360.0))
    r_edges = np.arange(n + 1) * scan["gate_km"]
    A, R = np.meshgrid(az_edges, r_edges, indexing="ij")
    y, x = R * np.cos(A), R * np.sin(A)
    lat = scan["rlat"] + y / 111.19
    lon = scan["rlon"] + x / (111.19 * np.cos(np.radians(scan["rlat"])))
    return lon, lat, data


def rain_rate(dbz, a: float = 200.0, b: float = 1.6):
    """Rain rate (mm/h) from reflectivity (dBZ) with Z = a·R^b (Marshall–Palmer by
    default). Values below 5 dBZ count as no rain; capped at 53 dBZ (hail)."""
    z = np.asarray(dbz, dtype=float)
    r = (10 ** (np.minimum(z, 53.0) / 10.0) / a) ** (1.0 / b)
    return np.where(np.isfinite(z) & (z >= 5.0), r, np.where(np.isfinite(z), 0.0, np.nan))


def rain_field(z, **zr):
    """`rain_rate` of an N0B field from `load_grid` (time, lat, lon): NaN inside a scan
    is "below threshold" (no echo), so it counts as 0 mm/h, not as missing. A time step
    with no scan has no row in `load_grid`, so missing scans stay missing."""
    return z.copy(data=rain_rate(np.where(np.isnan(z.values), 0.0, z.values), **zr))


def _sample(scan: Optional[dict], points: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Sample scan values at link and grid points (range-azimuth to Cartesian)."""
    if scan is None:
        return None

    # Equirectangular projection: km from radar
    lat, lon = points["lat"].values, points["lon"].values
    y = (lat - scan["rlat"]) * 111.19
    x = (lon - scan["rlon"]) * 111.19 * np.cos(np.radians((lat + scan["rlat"]) / 2))

    # Range and azimuth to each point
    rng = np.hypot(x, y)
    azm = np.degrees(np.arctan2(x, y)) % 360

    # The radial whose azimuth span contains the point, and the gate that holds it
    d, az = scan["data"], scan["az"]
    width = (scan["az_end"] - az) % 360
    inside = ((azm[:, None] - az[None, :]) % 360) < width[None, :]
    ai = inside.argmax(axis=1)
    gi = np.floor(rng / scan["gate_km"]).astype(int)

    # Sample values (NaN where out of range or in no radial)
    ok = inside.any(axis=1) & (gi >= 0) & (gi < d.shape[1])
    v = np.full(len(points), np.nan, dtype=np.float32)
    v[ok] = d[ai[ok], gi[ok]]

    return pd.DataFrame({
        "t": scan["t"],
        "key": points["key"].values,
        "pt": points["pt"].values.astype(np.int16),
        "value": v
    })


def _hour(product: str, hour: pd.Timestamp, points: pd.DataFrame, folder: Path, workers: int = 12):
    """Download and cache one product hour (one scan per STEP)."""
    out = folder / product / f"{hour:%Y%m%d_%H}.parquet"
    if out.exists():
        return

    keys = _list(product, hour)
    if keys is None:                       # listing failed: try again next time, cache nothing
        return
    if keys:
        s = pd.Series(keys, index=[_key_time(k) for k in keys]).sort_index()
        keys = list(s.groupby(s.index.floor(STEP)).first().values)

    frames = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for df in ex.map(lambda k: _sample(_read(k), points), keys):
            if df is not None:
                frames.append(df)

    if keys and not frames:                # every download failed: do not cache an empty hour
        log.warning(f"no scan of {product} {hour} could be read")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    if frames:
        d = pd.concat(frames, ignore_index=True)
    else:
        d = pd.DataFrame({"t": pd.Series(dtype="datetime64[ns]"), "key": [], "pt": [], "value": []})
    d.to_parquet(out, index=False)


def _folder(dataset: Optional[str]) -> Path:
    """Cache folder of the samples of one dataset's links (the link points differ).
    `samples_v2`: MRMS cell-centre grid and containing-radial rule (older caches are not read)."""
    from analysis import datasets as D
    return _get_cache_dir() / "samples_v2" / D.resolve(dataset)


def fetch_window(start, end, products=PRODUCTS, workers=12, dataset: Optional[str] = None):
    """Fetch and cache NEXRAD Level-3 samples for the time window.

    Parameters
    ----------
    start, end : str or pd.Timestamp
        UTC time bounds (inclusive).
    products : sequence of str
        Product codes (default: all four).
    workers : int
        Download parallelism.
    dataset : 'v1' or 'v2', optional
        Whose CML paths to sample (default: the active dataset).
    """
    folder = _folder(dataset)
    points = link_points(dataset)

    for hour in pd.date_range(
        pd.Timestamp(start).floor("h"),
        pd.Timestamp(end).floor("h"),
        freq="h"
    ):
        for product in products:
            _hour(product, hour, points, folder, workers)


def load(start, end, product: str, dataset: Optional[str] = None) -> Optional[pd.DataFrame]:
    """Load cached samples for the time window.

    Returns (t, key, pt, value) where:
    - t: UTC time of the scan
    - key: CML link ID (string) or 'grid'
    - pt: point index (0..4 along links, or grid position)
    - value: sampled NEXRAD value (HHC code, dBZ, etc.)
    None when nothing is cached for the window (run `fetch_window` first).
    """
    folder = _folder(dataset)

    hours = pd.date_range(
        pd.Timestamp(start).floor("h"),
        pd.Timestamp(end).floor("h"),
        freq="h"
    )
    files = [folder / product / f"{h:%Y%m%d_%H}.parquet" for h in hours]
    files = [f for f in files if f.exists()]

    if not files:
        return None

    d = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    d["t"] = pd.to_datetime(d["t"])
    d["key"] = d["key"].astype(str)
    return d[(d["t"] >= pd.Timestamp(start)) & (d["t"] <= pd.Timestamp(end))]


def load_grid(start, end, product: str = "N0B", dataset: Optional[str] = None):
    """Cached grid samples of the window as a (time, lat, lon) DataArray on the MRMS NYC
    cell centres (`grid_axes`), so the MRMS tools (`sample_points`, `path_average`) work on
    it unchanged. One time step per cached scan; NaN inside a scan = below threshold (no
    echo). None when nothing is cached (run `fetch_window` first)."""
    import xarray as xr
    d = load(start, end, product, dataset)
    if d is None or d.empty:
        return None
    la, lo = grid_axes()
    g = d[d["key"] == "grid"].pivot_table(index="t", columns="pt", values="value", aggfunc="first")
    g = g.reindex(columns=range(la.size * lo.size))
    units = {"N0B": "dBZ", "N0X": "dB", "N0C": "1", "HHC": "class code"}[product]
    return xr.DataArray(g.values.reshape(len(g), la.size, lo.size),
                        coords={"time": g.index.values, "lat": la, "lon": lo},
                        dims=("time", "lat", "lon"), name=product,
                        attrs={"units": units, "source": f"NEXRAD K{SITE} Level-3 {product}"})


def hourly_rain(start, end, dataset: Optional[str] = None, min_scans: int = 4, **zr):
    """Hourly rain (mm, hour-ending, the MRMS QPE convention) on the grid from N0B
    reflectivity: Z–R per scan (`rain_rate`, keywords a / b), mean rate over the hour's
    scans; NaN with fewer than `min_scans` scans (of 6). Needs `fetch_window(...,
    products=('N0B',))` for the window first. A reflectivity estimate at ~1 km height:
    no gauge correction, liquid-rain Z–R (snow and the melting layer are not handled)."""
    z = load_grid(pd.Timestamp(start) - pd.Timedelta("1h"), end, "N0B", dataset)
    if z is None:
        return None
    r = rain_field(z, **zr)
    g = r.resample(time="1h", label="right", closed="right")
    out = g.mean().where(g.count() >= min_scans)
    out = out.sel(time=slice(pd.Timestamp(start), pd.Timestamp(end)))
    out.name, out.attrs = "rainfall_amount", {"units": "mm", "comment": "KOKX N0B, Z = 200 R^1.6, hourly mean rate"}
    return out


# ============================================================================
# KOKX on a grid at given time stamps (the KOKX files of the OpenMesh v2 record)
# ============================================================================

HHC_FILL = 255           # "no HHC scan within `tolerance` of the stamp"; 0 stays "below threshold"
HHC_FLAG_MEANINGS = ("below_threshold biological ground_clutter ice_crystals dry_snow wet_snow "
                     "light_moderate_rain heavy_rain big_drops graupel hail_possibly_with_rain large_hail "
                     "giant_hail unknown range_folded")     # same order as sorted(HYDRO_LEGEND)


def _nearest_scans(product: str, times: pd.DatetimeIndex, tolerance: pd.Timedelta) -> list:
    """Bucket key of the scan nearest each stamp within `tolerance` (None if there is none)."""
    hours = pd.date_range((times[0] - tolerance).floor("h"), (times[-1] + tolerance).floor("h"), freq="h")
    with ThreadPoolExecutor(max_workers=8) as ex:
        listed = list(ex.map(lambda h: _list(product, h), hours))
    if any(x is None for x in listed):
        raise RuntimeError(f"listing {product} failed for some hours; try again")
    keys = [k for ks in listed for k in ks]
    if not keys:
        return [None] * len(times)
    s = pd.Series(keys, index=pd.DatetimeIndex([_key_time(k) for k in keys])).sort_index()
    s = s[~s.index.duplicated()]
    out = []
    for t in times:
        d = np.abs(s.index - t)
        j = int(np.argmin(d))
        out.append(s.iloc[j] if d[j] <= tolerance else None)
    return out


def sample_grid(times, lat=None, lon=None, tolerance: str = "5min", workers: int = 12):
    """KOKX HHC and N0B on a grid at given time stamps, as the KOKX files of the OpenMesh v2
    record (`data/weather/radar/openmesh_radar_kokx_<kind>_<day>.nc`) store them.

    times    : the stamps (e.g. `time_10min` of the record's MRMS file of the same day)
    lat, lon : cell centres (default `grid_axes()`, the MRMS NYC cell centres)
    For each stamp the scan nearest it within `tolerance`; each cell takes the gate holding
    its centre (`_sample`: the radial whose azimuth span contains it). Returns a Dataset:
    hydrometeor_class (uint8, NOAA HHC codes as stored, 0 = below threshold, 255 = no scan),
    reflectivity (float32 dBZ; NaN = below threshold where scan_time_n0b is set, NaN
    everywhere where it is NaT = no scan), scan_time_hhc, scan_time_n0b."""
    import xarray as xr
    times = pd.DatetimeIndex(times)
    if lat is None or lon is None:
        lat, lon = grid_axes()
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    pts = pd.DataFrame({"key": "grid", "pt": np.arange(lat.size * lon.size),
                        "lat": np.repeat(lat, lon.size), "lon": np.tile(lon, lat.size)})
    tol = pd.Timedelta(tolerance)
    data, scan_times = {}, {}
    for prod in ("HHC", "N0B"):
        keys = _nearest_scans(prod, times, tol)
        uniq = sorted({k for k in keys if k})
        with ThreadPoolExecutor(max_workers=workers) as ex:
            grids = dict(zip(uniq, ex.map(
                lambda k: (lambda s: None if s is None else
                           _sample(s, pts)["value"].values.reshape(lat.size, lon.size))(_read(k)), uniq)))
        bad = [k for k, g in grids.items() if g is None]
        if bad:
            raise RuntimeError(f"{len(bad)} {prod} scans could not be read (e.g. {bad[0]}); try again")
        if prod == "HHC":
            arr = np.full((len(times), lat.size, lon.size), HHC_FILL, dtype=np.uint8)
            for i, k in enumerate(keys):
                if k:
                    g = grids[k]
                    arr[i] = np.where(np.isnan(g), HHC_FILL, g).astype(np.uint8)
        else:
            arr = np.full((len(times), lat.size, lon.size), np.nan, dtype=np.float32)
            for i, k in enumerate(keys):
                if k:
                    arr[i] = grids[k]
        data[prod] = arr
        scan_times[prod] = pd.DatetimeIndex([_key_time(k) if k else pd.NaT for k in keys])

    dims = ("time_10min", "lat", "lon")
    return xr.Dataset(
        {"hydrometeor_class": (dims, data["HHC"], {
            "long_name": "KOKX hybrid hydrometeor classification (NEXRAD Level-3 HHC), class code as stored",
            "flag_values": np.array(sorted(c for c in HYDRO_LEGEND), dtype=np.uint8),
            "flag_meanings": HHC_FLAG_MEANINGS,
            "_FillValue": np.uint8(HHC_FILL)}),
         "reflectivity": (dims, data["N0B"], {"long_name": "KOKX base reflectivity, 0.5 deg tilt (N0B)",
                                              "units": "dBZ"}),
         "scan_time_hhc": ("time_10min", scan_times["HHC"]),
         "scan_time_n0b": ("time_10min", scan_times["N0B"])},
        coords={"time_10min": times, "lat": lat, "lon": lon},
        attrs={"source": f"NOAA/NWS NEXRAD K{SITE} Level-3 (AWS unidata-nexrad-level3)",
               "comment": f"scan nearest each stamp within {tolerance}; gate holding each cell centre"})
