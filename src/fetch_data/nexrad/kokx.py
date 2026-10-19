"""KOKX (Upton, NY) NEXRAD Level-3 products (AWS unidata-nexrad-level3 bucket).

KOKX (~100 km from NYC) provides dual-pol radar reflectivity and hydrometeor classification
complementary to MRMS. Beam centre over the links is ~1.5 km above ground.

Products: HHC (hydrometeor class), N0B (reflectivity dBZ, 0.25 km gates), N0X (differential
reflectivity ZDR dB), N0C (correlation coefficient). Gates are 0.25 km (max_range 230 km).

Usage::

    from fetch_data.nexrad import kokx
    kokx.fetch_window("2024-01-09", "2024-01-10")        # fetch and cache for the window
    df = kokx.load("2024-01-09", "2024-01-10", "HHC")    # load cached samples
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

# Hydrometeor class legend (HHC product)
HYDRO_LEGEND = {
    0: "no data", 10: "biological", 20: "clutter", 30: "ice crystals",
    40: "dry snow", 50: "wet snow", 60: "rain", 70: "heavy rain", 80: "big drops",
    90: "graupel", 100: "hail", 140: "unknown", 150: "range folded"
}

# Grid for spatial sampling: city bounding box
GRID_BOX = (40.55, 40.92, -74.10, -73.70)  # (lat0, lat1, lon0, lon1)
GRID_RES = 0.01


def _get_cache_dir() -> Path:
    """NEXRAD cache location (mirrors MRMS cache structure)."""
    from fetch_data.config import RAW_DIR
    cache = RAW_DIR / "radar" / "nexrad"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _get_link_points() -> pd.DataFrame:
    """Link endpoints from OpenMesh metadata."""
    meta_file = Path(__file__).resolve().parents[3] / "dataset" / "meta" / "links_metadata.csv"
    try:
        df = pd.read_csv(meta_file, index_col=0)
    except FileNotFoundError:
        log.warning(f"Links metadata not found at {meta_file}; using empty DataFrame")
        return pd.DataFrame({"key": [], "pt": [], "lat": [], "lon": []})

    # Sample points along each link
    rows = []
    for _, row in df.drop_duplicates(subset=["cml_id"]).iterrows():
        key = str(row["cml_id"])
        for i, t in enumerate(np.linspace(0, 1, 5)):  # 5 points per link
            lat = row["site_0_lat"] + t * (row["site_1_lat"] - row["site_0_lat"])
            lon = row["site_0_lon"] + t * (row["site_1_lon"] - row["site_0_lon"])
            rows.append((key, i, lat, lon))

    # Add grid points
    la = np.arange(GRID_BOX[0], GRID_BOX[1] + 1e-9, GRID_RES)
    lo = np.arange(GRID_BOX[2], GRID_BOX[3] + 1e-9, GRID_RES)
    for i, (a, b) in enumerate((a, b) for a in la for b in lo):
        rows.append(("grid", i, a, b))

    return pd.DataFrame(rows, columns=["key", "pt", "lat", "lon"])


def _list(product: str, hour: pd.Timestamp) -> list[str]:
    """List files in AWS bucket for the given hour."""
    pre = f"{SITE}_{product}_{hour:%Y_%m_%d_%H}"
    keys = []
    for k in range(3):
        try:
            r = requests.get(BUCKET, params={"list-type": "2", "prefix": pre, "max-keys": "200"}, timeout=30)
            return re.findall(r"<Key>([^<]+)</Key>", r.text)
        except Exception as e:
            if k < 2:
                time.sleep(1 + k)
            else:
                log.warning(f"Failed to list {product} {hour}: {e}")
    return []


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
                "data": val,
                "az": np.asarray(sb["start_az"], dtype=float),
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


def _sample(scan: Optional[dict], points: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Sample scan values at link and grid points (range-azimuth to Cartesian)."""
    if scan is None:
        return None

    # Equirectangular projection: metres from radar
    lat, lon = points["lat"].values, points["lon"].values
    y = (lat - scan["rlat"]) * 111.19
    x = (lon - scan["rlon"]) * 111.19 * np.cos(np.radians((lat + scan["rlat"]) / 2))

    # Range and azimuth to each point
    rng = np.hypot(x, y)
    azm = np.degrees(np.arctan2(x, y)) % 360

    # Nearest azimuth bin and range gate
    d, az = scan["data"], scan["az"]
    ai = np.argmin(np.abs(((az[None, :] - azm[:, None] + 180) % 360) - 180), axis=1)
    gi = np.floor(rng / scan["gate_km"]).astype(int)

    # Sample values (NaN where out of range)
    ok = (gi >= 0) & (gi < d.shape[1])
    v = np.full(len(points), np.nan, dtype=np.float32)
    v[ok] = d[ai[ok], gi[ok]]

    return pd.DataFrame({
        "t": scan["t"],
        "key": points["key"].values,
        "pt": points["pt"].values.astype(np.int16),
        "value": v
    })


def _hour(product: str, hour: pd.Timestamp, points: pd.DataFrame, cache: Path, workers: int = 12):
    """Download and cache one product hour (one scan per STEP)."""
    out = cache / product / f"{hour:%Y%m%d_%H}.parquet"
    if out.exists():
        return

    keys = _list(product, hour)
    if keys:
        s = pd.Series(keys, index=[_key_time(k) for k in keys]).sort_index()
        keys = list(s.groupby(s.index.floor(STEP)).first().values)

    frames = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for df in ex.map(lambda k: _sample(_read(k), points), keys):
            if df is not None:
                frames.append(df)

    out.parent.mkdir(parents=True, exist_ok=True)
    if frames:
        d = pd.concat(frames, ignore_index=True)
    else:
        d = pd.DataFrame({"t": pd.Series(dtype="datetime64[ns]"), "key": [], "pt": [], "value": []})
    d.to_parquet(out, index=False)


def fetch_window(start, end, products=PRODUCTS, workers=12):
    """Fetch and cache NEXRAD Level-3 scans for the time window.

    Parameters
    ----------
    start, end : str or pd.Timestamp
        UTC time bounds (inclusive).
    products : sequence of str
        Product codes (default: all four).
    workers : int
        Download parallelism.
    """
    cache = _get_cache_dir()
    points = _get_link_points()

    for hour in pd.date_range(
        pd.Timestamp(start).floor("h"),
        pd.Timestamp(end).floor("h"),
        freq="h"
    ):
        for product in products:
            _hour(product, hour, points, cache, workers)


def load(start, end, product: str) -> Optional[pd.DataFrame]:
    """Load cached samples for the time window.

    Returns (t, key, pt, value) where:
    - t: UTC time of the scan
    - key: CML link ID (string) or 'grid'
    - pt: point index (0..4 along links, or grid position)
    - value: sampled NEXRAD value (HHC code, dBZ, etc.)
    """
    cache = _get_cache_dir()

    hours = pd.date_range(
        pd.Timestamp(start).floor("h"),
        pd.Timestamp(end).floor("h"),
        freq="h"
    )
    files = [cache / product / f"{h:%Y%m%d_%H}.parquet" for h in hours]
    files = [f for f in files if f.exists()]

    if not files:
        return None

    d = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    d["t"] = pd.to_datetime(d["t"])
    return d[(d["t"] >= pd.Timestamp(start)) & (d["t"] <= pd.Timestamp(end))]
