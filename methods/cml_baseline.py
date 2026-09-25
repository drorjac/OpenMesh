"""
methods/cml_baseline.py
=======================
Per-link CML signal baseline estimation and rain/snow attenuation for the
NYC Mesh long-link subset, aligned to the per-bin precipitation-phase index
(`_build_code_phase`, wu_airport cascade + temp_guard) built in
`src/analysis/nycmesh_utils.py`.

WHY
---
A commercial microwave link (CML) reports received signal level (RSL, dBm).
During precipitation the path attenuates and RSL drops. To turn RSL into a
weather signal we need a *baseline* = the RSL we would have seen with a dry
path. Attenuation is then

    A(t) = baseline(t) - RSL(t)          [dB]   (positive during precip)

This dataset has **RSL only** (no TSL), so attenuation is defined purely
against an estimated baseline. Four baseline estimators are provided (see
`BASELINE_METHODS`); each is a full per-link hourly series so attenuation is
defined at every timestamp (it is only physically meaningful inside events).

SCOPE / FILTERS
---------------
- Long links only: path ``length > 900 m`` (LONG_LENGTH_M).
- All valid sublinks on those links are kept (290 sublinks over 119 links).
- Band tier per sublink from frequency (MHz):
      sub6   : f < 6 000
      K      : 18 000 <= f <= 27 000
      V-low  : 50 000 <= f < 65 000
      V-high : f >= 65 000          (the >65 GHz priority focus, 88 sublinks)

CADENCE
-------
Everything is computed and stored at **1 h** — it matches the phase bins and
the "per link-hour" rain-rate retrieval in Part 2, and keeps the product file
small. Native RSL cadence (~8 s, irregular) is reduced by hourly mean.

OUTPUT netCDF  (dataset/raw/full/outputs/cml_attenuation_baselines.nc)
----------------------------------------------------------------------
dims    : time (hourly), sublink (one per valid cml_id x sublink_id)

coords  : time        datetime64        hourly grid over the analysis window
          sublink      str               "<cml_id>::<sublink_id>" unique key
          cml_id       str  (sublink)    parent link id
          sublink_id   str  (sublink)    sublink label
          length_m     f4   (sublink)    path length, metres
          freq_MHz     f4   (sublink)    carrier frequency, MHz
          band_tier    str  (sublink)    sub6 / K / V-low / V-high
          polarisation str  (sublink)
          site_0_lat/lon, site_1_lat/lon f4 (sublink)  link endpoints (deg)

data_vars (sublink, time) :
          rsl          f4   dBm          hourly-mean received signal level
          att_static   f4   dB           attenuation, baseline (a) static 6 h dry window
          att_rollq    f4   dB           attenuation, baseline (b) rolling 95th pct
          att_drymed   f4   dB           attenuation, baseline (c) dry-hour daily median
          att_ewma     f4   dB           attenuation, baseline (d) EWMA over dry RSL
          failure      i1   {0,1}        mid-event RSL gap (data before AND after
                                         within the same event window) -> link outage,
                                         distinct from a fully-NaN day
   (baseline_k(t) = rsl(t) + att_k(t); baselines are recoverable, not stored.)

data_vars (time,) — shared weather context (network level) :
          phase        str               snow / mixed / rain / dry / unknown
          precip_mm    f4   mm           ASOS network hourly precip (mean of station sums)
          temp_c       f4   degC         ASOS network hourly mean temperature
          event_id     i4                contiguous-wet event id (0 = not in an event)

Run ``python methods/cml_baseline.py`` to build the file. A fast smoke build
over a single month is available via ``--window 2024-01-01 2024-02-01``.
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import xarray as xr

warnings.filterwarnings("ignore")

# --- make src/analysis importable -------------------------------------------
_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from analysis.nycmesh_utils import _build_code_phase, load_weather_networks  # noqa: E402
from analysis.pws_qc import network_resample  # noqa: E402

# --- paths ------------------------------------------------------------------
CML_NC = _REPO / "dataset/raw/full/paper/ds_opensense_cml.nc"
OUT_DIR = _REPO / "dataset/raw/full/outputs"
ASOS_NC = OUT_DIR / "asos_2023-10-01_2026-04-23.nc"
PWS_NC = OUT_DIR / "pws_wu_merged_2023-06-07_2026-04-24_qc.nc"
OUT_NC = OUT_DIR / "cml_attenuation_baselines.nc"

# --- constants --------------------------------------------------------------
LONG_LENGTH_M = 900.0
WET = ("snow", "mixed", "rain")
BASELINE_METHODS = ("static", "rollq", "drymed", "ewma")

# baseline knobs
STATIC_DRY_HOURS = 6        # (a) length of the dry window used as the static reference
ROLLQ_WINDOW = "24h"        # (b) rolling-quantile window
ROLLQ_Q = 0.95             # (b) high quantile ~ dry/clear RSL level (RSL drops when wet)
EWMA_HALFLIFE = "3D"        # (d) drift-tracking halflife over dry-hour RSL
EVENT_GAP_HOURS = 1         # merge wet runs separated by <= this many dry hours


def band_tier(freq_mhz: float) -> str:
    """Map carrier frequency (MHz) to a coarse band tier."""
    if not np.isfinite(freq_mhz):
        return "unknown"
    if freq_mhz < 6_000:
        return "sub6"
    if 18_000 <= freq_mhz <= 27_000:
        return "K"
    if 50_000 <= freq_mhz < 65_000:
        return "V-low"
    if freq_mhz >= 65_000:
        return "V-high"
    return "other"


# ============================================================================
# Link selection
# ============================================================================
def select_long_sublinks(ds: xr.Dataset, min_length_m: float = LONG_LENGTH_M) -> pd.DataFrame:
    """One row per valid (cml_id, sublink_id) on links longer than min_length_m.

    'Valid' = finite carrier frequency (an actually-configured sublink).
    """
    freq = ds["frequency"].values            # (cml, sub)
    length = ds["length"].values             # (cml,)
    pol = ds["polarisation"].values          # (cml, sub)
    cml_ids = ds["cml_id"].values.astype(str)
    sub_ids = ds["sublink_id"].values.astype(str)
    s0lat, s0lon = ds["site_0_lat"].values, ds["site_0_lon"].values
    s1lat, s1lon = ds["site_1_lat"].values, ds["site_1_lon"].values

    rows = []
    for ci in np.where(length > min_length_m)[0]:
        for si in range(freq.shape[1]):
            f = freq[ci, si]
            if not np.isfinite(f):
                continue
            rows.append(dict(
                ci=int(ci), si=int(si),
                cml_id=cml_ids[ci], sublink_id=sub_ids[si],
                sublink=f"{cml_ids[ci]}::{sub_ids[si]}",
                length_m=float(length[ci]), freq_MHz=float(f),
                band_tier=band_tier(float(f)),
                polarisation=str(pol[ci, si]),
                site_0_lat=float(s0lat[ci]), site_0_lon=float(s0lon[ci]),
                site_1_lat=float(s1lat[ci]), site_1_lon=float(s1lon[ci]),
            ))
    return pd.DataFrame(rows)


# ============================================================================
# Hourly weather context: phase (wu_airport + temp_guard), precip, temperature
# ============================================================================
def build_hourly_context(
    window: Tuple[str, str],
    *,
    freq: str = "1h",
    temp_guard: bool = True,
    snow_ceil_c: float = 6.0,
    mixed_ceil_c: float = 8.0,
    verbose: bool = True,
) -> pd.DataFrame:
    """Hourly DataFrame indexed by time with columns: phase, precip_mm, temp_c.

    phase   : snow/mixed/rain/dry/unknown from `_build_code_phase` (wu_airport
              cascade), with the warm-temp `temp_guard` veto applied against the
              official ASOS temperature (snow>snow_ceil_c, mixed>mixed_ceil_c -> rain).
    precip_mm : ASOS network hourly precip (mean across stations of per-station sums).
    temp_c    : ASOS network hourly mean temperature.
    """
    nets = load_weather_networks(asos_nc=ASOS_NC, pws_nc=PWS_NC, meso_nc=None, verbose=verbose)
    t0, t1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])

    ph = _build_code_phase(nets, classify="wu_airport", window=window, freq=freq,
                           code_rule="mode", verbose=verbose)

    temp = network_resample(nets["ASOS"], "temperature", freq, "mean").loc[t0:t1].mean(axis=1)
    precip = network_resample(nets["ASOS"], "rainfall_amount", freq, "sum").loc[t0:t1].mean(axis=1)

    grid = pd.date_range(t0.floor(freq), t1.ceil(freq), freq=freq)
    out = pd.DataFrame(index=grid)
    out["phase"] = ph.reindex(grid)
    out["temp_c"] = temp.reindex(grid)
    out["precip_mm"] = precip.reindex(grid)

    if temp_guard:
        p, T = out["phase"], out["temp_c"]
        warm_snow = (p == "snow") & (T > snow_ceil_c)
        warm_mixed = (p == "mixed") & (T > mixed_ceil_c)
        out.loc[warm_snow | warm_mixed, "phase"] = "rain"
        if verbose:
            print(f"  temp_guard reclassified {int(warm_snow.sum())} snow + "
                  f"{int(warm_mixed.sum())} mixed -> rain")

    out["phase"] = out["phase"].fillna("unknown")
    return out


def label_events(phase: pd.Series, gap_hours: int = EVENT_GAP_HOURS) -> pd.Series:
    """Integer event id per hour. An event is a run of wet (snow/mixed/rain)
    hours; runs separated by <= gap_hours dry/unknown hours are merged.
    0 = not in any event.
    """
    wet = phase.isin(WET).to_numpy()
    # bridge short gaps between wet runs
    bridged = wet.copy()
    idx = np.where(wet)[0]
    for a, b in zip(idx[:-1], idx[1:]):
        if 1 < (b - a) <= gap_hours + 1:
            bridged[a:b] = True
    ev = np.zeros(len(phase), dtype=int)
    cur, prev = 0, False
    for i, w in enumerate(bridged):
        if w and not prev:
            cur += 1
        ev[i] = cur if w else 0
        prev = w
    return pd.Series(ev, index=phase.index, name="event_id")


# ============================================================================
# RSL resampling
# ============================================================================
def rsl_hourly(ds: xr.Dataset, ci: int, si: int, grid: pd.DatetimeIndex,
               freq: str = "1h") -> pd.Series:
    """Hourly-mean RSL (dBm) for one sublink, reindexed onto `grid`."""
    arr = ds["rsl"].isel(cml_id=ci, sublink_id=si).values  # (time,) lazy hyperslab read
    s = pd.Series(arr, index=pd.to_datetime(ds["time"].values))
    s = s.resample(freq).mean()
    return s.reindex(grid)


# ============================================================================
# Baselines  (each returns a full hourly baseline series in dBm)
# ============================================================================
def baseline_static(rsl: pd.Series, dry_mask: pd.Series,
                    dry_hours: int = STATIC_DRY_HOURS) -> pd.Series:
    """(a) Static dry-window median: rolling median of dry-hour RSL over a
    `dry_hours`-long window, forward-filled. Anchors each event on the median
    RSL of the most recent dry stretch preceding it."""
    dry_rsl = rsl.where(dry_mask)
    base = dry_rsl.rolling(f"{dry_hours}h", min_periods=1).median()
    return base.ffill()


def baseline_rollq(rsl: pd.Series, window: str = ROLLQ_WINDOW,
                   q: float = ROLLQ_Q) -> pd.Series:
    """(b) Rolling high quantile of RSL. RSL drops during precip, so a high
    quantile (default 95th pct over `window`) tracks the dry/clear level."""
    return rsl.rolling(window, min_periods=3).quantile(q)


def baseline_drymed(rsl: pd.Series, dry_mask: pd.Series) -> pd.Series:
    """(c) Per-day median over dry hours only, forward-filled to every hour."""
    dry_rsl = rsl.where(dry_mask)
    daily = dry_rsl.resample("1D").median()
    return daily.reindex(rsl.index, method="ffill")


def baseline_ewma(rsl: pd.Series, dry_mask: pd.Series,
                  halflife: str = EWMA_HALFLIFE) -> pd.Series:
    """(d) EWMA over dry-hour RSL, forward-filled. Tracks slow hardware/gain
    drift without being pulled down by rain, unlike a fixed-window median."""
    dry_rsl = rsl.where(dry_mask)
    ew = dry_rsl.ewm(halflife=pd.Timedelta(halflife), times=rsl.index).mean()
    return ew.ffill()


def detect_failures(rsl: pd.Series, event_id: pd.Series) -> pd.Series:
    """Per-hour failure flag: RSL is NaN inside an event AND the same event has
    valid RSL both before and after this hour. Marks mid-event link outages,
    distinct from a fully-NaN (never-reporting) day.

    Vectorised: for each event the first/last valid-RSL position is found with a
    groupby min/max; a NaN hour strictly between them is a mid-event gap.
    """
    valid = rsl.notna().to_numpy()
    ev = event_id.to_numpy()
    pos = np.arange(len(valid))
    valid_pos = np.where(valid, pos, np.nan)
    g = pd.DataFrame({"ev": ev, "vp": valid_pos}).groupby("ev")["vp"]
    first_valid = g.transform("min").to_numpy()
    last_valid = g.transform("max").to_numpy()
    fail = (ev > 0) & (~valid) & (pos > first_valid) & (pos < last_valid)
    return pd.Series(fail, index=rsl.index)


# ============================================================================
# Builder
# ============================================================================
def _strarr(x) -> np.ndarray:
    """Coerce to a fixed-width unicode (<U) array. pandas StringDtype and
    object arrays are not directly netCDF4-encodable; xarray writes <U arrays
    as char arrays with a string dimension."""
    return np.array([str(v) for v in np.asarray(x)])


def build_dataset(window: Tuple[str, str], *, freq: str = "1h",
                  verbose: bool = True) -> xr.Dataset:
    ds = xr.open_dataset(CML_NC)
    links = select_long_sublinks(ds)
    if verbose:
        print(f"  {len(links)} long-link sublinks  |  band tiers: "
              f"{links['band_tier'].value_counts().to_dict()}")

    ctx = build_hourly_context(window, freq=freq, verbose=verbose)
    grid = ctx.index
    dry_mask = ctx["phase"] == "dry"
    event_id = label_events(ctx["phase"])

    n, T = len(links), len(grid)
    rsl_a = np.full((n, T), np.nan, np.float32)
    att = {m: np.full((n, T), np.nan, np.float32) for m in BASELINE_METHODS}
    fail_a = np.zeros((n, T), np.int8)

    for k, row in enumerate(links.itertuples(index=False)):
        r = rsl_hourly(ds, row.ci, row.si, grid, freq=freq)
        rsl_a[k] = r.to_numpy(dtype=np.float32)
        bases = dict(
            static=baseline_static(r, dry_mask),
            rollq=baseline_rollq(r),
            drymed=baseline_drymed(r, dry_mask),
            ewma=baseline_ewma(r, dry_mask),
        )
        for m, b in bases.items():
            att[m][k] = (b - r).to_numpy(dtype=np.float32)
        fail_a[k] = detect_failures(r, event_id).to_numpy().astype(np.int8)
        if verbose and (k + 1) % 50 == 0:
            print(f"    processed {k + 1}/{n} sublinks")
    ds.close()

    coords = dict(
        time=grid, sublink=_strarr(links["sublink"].values),
        cml_id=("sublink", _strarr(links["cml_id"].values)),
        sublink_id=("sublink", _strarr(links["sublink_id"].values)),
        length_m=("sublink", links["length_m"].values.astype("f4")),
        freq_MHz=("sublink", links["freq_MHz"].values.astype("f4")),
        band_tier=("sublink", _strarr(links["band_tier"].values)),
        polarisation=("sublink", _strarr(links["polarisation"].values)),
        site_0_lat=("sublink", links["site_0_lat"].values.astype("f4")),
        site_0_lon=("sublink", links["site_0_lon"].values.astype("f4")),
        site_1_lat=("sublink", links["site_1_lat"].values.astype("f4")),
        site_1_lon=("sublink", links["site_1_lon"].values.astype("f4")),
    )
    data = {
        "rsl": (("sublink", "time"), rsl_a, {"units": "dBm", "long_name": "hourly-mean received signal level"}),
        "att_static": (("sublink", "time"), att["static"], {"units": "dB", "long_name": "attenuation vs static 6h dry-window median baseline"}),
        "att_rollq": (("sublink", "time"), att["rollq"], {"units": "dB", "long_name": f"attenuation vs rolling {int(ROLLQ_Q*100)}th-pct baseline ({ROLLQ_WINDOW})"}),
        "att_drymed": (("sublink", "time"), att["drymed"], {"units": "dB", "long_name": "attenuation vs dry-hour daily-median baseline"}),
        "att_ewma": (("sublink", "time"), att["ewma"], {"units": "dB", "long_name": f"attenuation vs EWMA dry-RSL baseline (halflife {EWMA_HALFLIFE})"}),
        "failure": (("sublink", "time"), fail_a, {"long_name": "mid-event RSL gap flag (1=outage inside event)"}),
        "phase": (("time",), _strarr(ctx["phase"].values), {"long_name": "precip phase (wu_airport cascade + temp_guard)"}),
        "precip_mm": (("time",), ctx["precip_mm"].values.astype("f4"), {"units": "mm", "long_name": "ASOS network hourly precipitation"}),
        "temp_c": (("time",), ctx["temp_c"].values.astype("f4"), {"units": "degC", "long_name": "ASOS network hourly mean temperature"}),
        "event_id": (("time",), event_id.values.astype("i4"), {"long_name": "contiguous-wet event id (0=none)"}),
    }
    out = xr.Dataset(data, coords=coords)
    out.attrs.update(
        title="NYC Mesh CML attenuation baselines (long links)",
        description=("Hourly RSL and rain/snow attenuation under 4 baseline methods for "
                     "NYC Mesh sublinks on links >900 m, aligned to the wu_airport+temp_guard "
                     "precipitation-phase index. attenuation = baseline - RSL (dB). RSL-only "
                     "(no TSL). See methods/cml_baseline.py docstring for the full schema."),
        source_cml=str(CML_NC.name), source_asos=str(ASOS_NC.name), source_pws=str(PWS_NC.name),
        baseline_methods=", ".join(BASELINE_METHODS),
        long_length_m=LONG_LENGTH_M, cadence=freq,
        window_start=str(grid[0]), window_end=str(grid[-1]),
        generated_by="methods/cml_baseline.py", generated_on=pd.Timestamp.now().isoformat(),
    )
    return out


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Build CML attenuation-baselines netCDF.")
    ap.add_argument("--window", nargs=2, metavar=("START", "END"),
                    default=["2023-10-29", "2026-04-30"],
                    help="analysis window (default = full CML span)")
    ap.add_argument("--out", default=str(OUT_NC))
    ap.add_argument("--freq", default="1h")
    args = ap.parse_args(argv)

    print(f"Building CML attenuation baselines  window={tuple(args.window)} freq={args.freq}")
    out = build_dataset(tuple(args.window), freq=args.freq)
    enc = {v: {"zlib": True, "complevel": 4} for v in out.data_vars
           if np.issubdtype(out[v].dtype, np.number)}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_netcdf(args.out, encoding=enc)
    sz = Path(args.out).stat().st_size / 1e6
    print(f"  wrote {args.out}  ({sz:.1f} MB)  dims={dict(out.sizes)}")
    print(f"  phase counts: {pd.Series(out['phase'].values).value_counts().to_dict()}")


if __name__ == "__main__":
    main()
