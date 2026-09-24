"""
methods/cml_analysis.py
=======================
Analysis + plotting helpers for Part 2 (cml_phase_analysis.ipynb). All the
heavy lifting lives here so the notebook cells stay thin (knobs + one call).

Loads `cml_attenuation_baselines.nc` (built by cml_baseline.py) into a tidy
long-form frame and provides:
  - load_attenuation_long  : (sublink, hour) rows with att, att/km, phase, ...
  - plot_cdf_by_phase_band : 2.2 CDF of specific attenuation per band x phase
  - plot_temp_effect       : 2.3 attenuation vs temperature, coloured by phase
  - itu_rainrate_table     : 2.4 per-link ITU-R rain-rate skill (bias/RMSE/R2)
  - plot_itu_scatter       : 2.4 CML vs ASOS rain rate, coloured by phase
  - find_multiband_cmls    : 2.5 CMLs carrying sublinks in >1 band
  - plot_multiband_cml     : 2.5 per-band attenuation on the same path

Shared phase palette is imported from nycmesh_utils so colours match
plot_phase_temp_scatter / plot_cml_phase_scatter everywhere.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import xarray as xr

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))
if str(_REPO / "methods") not in sys.path:
    sys.path.insert(0, str(_REPO / "methods"))

from cml_rainrate import itu_k_alpha, rain_rate_from_attenuation  # noqa: E402

OUT_NC = _REPO / "dataset/raw/full/outputs/cml_attenuation_baselines.nc"
BASE10_NC = _REPO / "dataset/raw/full/outputs/cml_attenuation_baselines_10min.nc"
ASOS_NC = _REPO / "dataset/raw/full/outputs/asos_2023-10-01_2026-04-23.nc"
PWS_NC = _REPO / "dataset/raw/full/outputs/pws_wu_merged_2023-06-07_2026-04-24_qc.nc"
ATT_METHODS = ("att_static", "att_rollq", "att_drymed", "att_ewma")
WET = ("rain", "snow", "mixed")
BAND_ORDER = ("sub6", "K", "V-low", "V-high")

# Phase palette (identical to nycmesh_utils plot_phase_temp_scatter).
PH_COLORS = {"rain": "#2166ac", "mixed": "#e377c2", "snow": "#00e5ff"}

# Baseline-method palette for the per-link diagnostic time series.
METHOD_COLORS = {"static": "#1b9e77", "rollq": "#d95f02",
                 "drymed": "#7570b3", "ewma": "#e6ab02"}

# Band palette: low frequency (blue) -> high frequency (red).
# "V" is the merged V-low+V-high tier (separate_vbands=False).
BAND_COLORS = {"sub6": "#4575b4", "K": "#91bfdb", "V-low": "#fc8d59",
               "V-high": "#d73027", "V": "#d73027"}
_VBANDS = ("V-low", "V-high")


def _vmerge_work(work: pd.DataFrame, separate: bool, label: str = "V") -> pd.DataFrame:
    """Collapse V-low+V-high band tiers into one `label` tier when not separate."""
    if separate:
        return work
    w = work.copy()
    w["band_tier"] = w["band_tier"].where(~w["band_tier"].isin(_VBANDS), label)
    return w


def _vmerge_bands(bands, separate: bool, label: str = "V") -> List[str]:
    """Remap a requested band list to the merged-V naming, order-preserving."""
    if separate:
        return list(bands)
    out = []
    for b in bands:
        b2 = label if b in _VBANDS else b
        if b2 not in out:
            out.append(b2)
    return out


def _darken(c, f=0.45):
    import matplotlib.colors as mc
    r, g, b = mc.to_rgb(c)
    return (r * f, g * f, b * f)


def _temp_bin_labels(edges) -> List[str]:
    """Human labels for a list of temperature bin edges (degC), e.g.
    [-inf, 0, inf] -> ['<0°C', '≥0°C']; [-inf, -5, 0, inf] -> ['<-5°C', ...]."""
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        if np.isneginf(lo):
            out.append(f"<{hi:g}°C")
        elif np.isposinf(hi):
            out.append(f"≥{lo:g}°C")
        else:
            out.append(f"{lo:g}–{hi:g}°C")
    return out


def multiband_cml_ids(df: pd.DataFrame, min_df_ghz: float = 1.0) -> List[str]:
    """Parent CMLs in `df` carrying sublinks spanning > min_df_ghz of frequency
    (same physical path seen in >1 band). Pass to a plot's `cmls=` to pool only
    those links, e.g. `cmls=A.multiband_cml_ids(df)`."""
    spread = df.groupby("cml_id")["freq_GHz"].agg(lambda s: s.max() - s.min())
    return spread[spread > min_df_ghz].index.astype(str).tolist()


def _filter_cmls(work: pd.DataFrame, cmls) -> pd.DataFrame:
    """Restrict to a subset of parent links (cml_id). None/empty = keep all."""
    if not cmls:
        return work
    return work[work["cml_id"].astype(str).isin([str(c) for c in cmls])]


# Rain-rate regimes (mm/hr): the standard light / moderate / heavy split.
PRECIP_REGIMES = {"light": (0.1, 2.5), "moderate": (2.5, 7.5), "heavy": (7.5, np.inf)}


def _resolve_regime(pr):
    """(lo, hi) mm/hr for a regime name or an explicit (lo, hi) tuple."""
    if isinstance(pr, str):
        if pr == "all":
            return 0.0, np.inf
        if pr in PRECIP_REGIMES:
            return PRECIP_REGIMES[pr]
        raise ValueError(f"precip_range must be 'all'|{list(PRECIP_REGIMES)} or (lo,hi), got {pr!r}")
    lo, hi = pr
    return (0.0 if lo is None else float(lo), np.inf if hi is None else float(hi))


def _regime_label(pr):
    names = {"light": "Light 0.1–2.5", "moderate": "Moderate 2.5–7.5", "heavy": "Heavy >7.5"}
    if isinstance(pr, str) and pr in names:
        return f"R: {names[pr]} mm/hr"
    lo, hi = _resolve_regime(pr)
    return f"R: {lo:g}–{hi:g} mm/hr"


def _precip_rate(work: pd.DataFrame) -> pd.Series:
    """precip_mm (per time-bin) -> rate in mm/hr, using the inferred cadence, so
    rate windows/bins are correct at any RES."""
    t = pd.Series(pd.unique(work["time"])).sort_values()
    sec = t.diff().dt.total_seconds().median()
    bin_h = sec / 3600.0 if (pd.notna(sec) and sec > 0) else 1.0
    return work["precip_mm"] / bin_h


_REGIME_BY_RANGE = {(0.1, 2.5): "Light", (2.5, 7.5): "Moderate", (7.5, np.inf): "Heavy"}


def _precip_bin_labels(edges) -> List[str]:
    """Labels for rain-rate bin edges (mm/hr), naming the standard regimes,
    e.g. [0.1,2.5,7.5,inf] -> ['Light 0.1–2.5 mm/hr', 'Moderate ...', 'Heavy >7.5 ...']."""
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        nm = _REGIME_BY_RANGE.get((lo, hi), "")
        rng = (f"<{hi:g}" if (np.isneginf(lo) or lo <= 0)
               else f">{lo:g}" if np.isposinf(hi) else f"{lo:g}–{hi:g}")
        out.append((f"{nm} " if nm else "") + f"{rng} mm/hr")
    return out


def _precip_filter(work: pd.DataFrame, precip_range) -> pd.DataFrame:
    """Restrict rows to a rain-rate window (mm/hr). None or 'all' = no filter."""
    if precip_range is None or precip_range == "all":
        return work
    lo, hi = _resolve_regime(precip_range)
    rate = _precip_rate(work)
    return work[(rate >= lo) & (rate < hi)]


def _draw_dist(ax, vals, *, kind="cdf", color="#888", ls="-", label="",
               lw=2.0, bins=40, xclip_pct=99.5):
    """Draw one distribution curve: CDF (sorted values vs cumulative fraction)
    or PDF (histogram-density line). Fewer than 5 points -> skipped. For PDF the
    histogram spans [min(0, vmin), p`xclip_pct`] so the bulk resolves on a heavy
    tail; the label gets the sample count appended."""
    v = np.sort(pd.Series(vals).dropna().values)
    if len(v) < 5:
        return
    lab = f"{label} (n={len(v):,})"
    if kind == "cdf":
        ax.plot(v, np.arange(1, len(v) + 1) / len(v),
                color=color, ls=ls, lw=lw, label=lab)
    elif kind == "pdf":
        hi = np.nanpercentile(v, xclip_pct) if xclip_pct else float(v.max())
        lo = min(float(v.min()), 0.0)
        if hi <= lo:
            hi = lo + 1e-6
        h, e = np.histogram(v, bins=bins, range=(lo, hi), density=True)
        ax.plot(0.5 * (e[:-1] + e[1:]), h, color=color, ls=ls, lw=lw, label=lab)
    else:
        raise ValueError(f"kind must be 'cdf' or 'pdf', got {kind!r}")


# ============================================================================
# Loader
# ============================================================================
def load_attenuation_long(
    nc_path=OUT_NC,
    att_var: str = "att_ewma",
    keep: str = "wet",
    impute_failures: bool = True,
    freq: Optional[str] = None,
) -> pd.DataFrame:
    """Tidy long-form frame: one row per (sublink, time-bin).

    Columns: sublink, cml_id, band_tier, freq_GHz, length_km, polarisation,
    time, rsl, att, att_per_km, failure, phase, precip_mm, temp_c.

    att_var          which baseline's attenuation to load (default ewma).
    keep             'wet' (rain/snow/mixed bins only), 'all', or 'rain'.
    impute_failures  per Part-2 spec: inside an event, set failure-flagged
                     timestamps to that event's max attenuation (worst case) so
                     outage gaps do not read as zero attenuation. The `failure`
                     column is preserved so they can be marked in plots.
    freq             optional pandas offset (e.g. '30min', '1h', '3h') to
                     DOWNSAMPLE the file's native cadence on the fly: att/rsl/temp
                     by mean, precip by sum, phase by per-bin mode, failure by any.
                     Must be >= the file cadence (it can coarsen, not refine).
                     None = the file's stored cadence. Lets one fine base file
                     (e.g. a 10-min build) serve any coarser analysis.
    """
    d = xr.open_dataset(nc_path)
    att = d[att_var].values.astype(float).copy()   # (sub, time)
    rsl = d["rsl"].values.astype(float)
    fail = d["failure"].values.astype(bool)
    phase = d["phase"].values
    precip = d["precip_mm"].values
    temp = d["temp_c"].values
    event = d["event_id"].values
    bt = d["band_tier"].values
    sub = d["sublink"].values
    cml = d["cml_id"].values
    pol = d["polarisation"].values
    L = d["length_m"].values
    f = d["freq_MHz"].values
    time = pd.to_datetime(d["time"].values)

    if impute_failures:
        # event max attenuation per sublink, broadcast onto failure cells
        ev_ids = np.unique(event[event > 0])
        for ev in ev_ids:
            cols = np.where(event == ev)[0]
            block = att[:, cols]
            emax = np.nanmax(np.where(np.isfinite(block), block, -np.inf), axis=1)
            emax = np.where(np.isfinite(emax), emax, np.nan)
            fblock = fail[:, cols]
            for j, c in enumerate(cols):
                rows = fblock[:, j]
                att[rows, c] = emax[rows]

    if freq is not None:                            # downsample to a coarser grid
        def _res2d(arr, how):
            r = getattr(pd.DataFrame(arr.T, index=time).resample(freq), how)()
            return r.values.T, r.index
        att, newt = _res2d(att, "mean")
        rsl, _ = _res2d(rsl, "mean")
        failf, _ = _res2d(fail.astype(float), "max")
        fail = failf > 0
        precip = pd.Series(precip, index=time).resample(freq).sum(min_count=1).values
        temp = pd.Series(temp, index=time).resample(freq).mean().values
        phase = (pd.Series(phase, index=time).resample(freq)
                 .agg(lambda x: x.value_counts().idxmax() if len(x.dropna()) else np.nan)
                 .values)
        time = newt

    wet_mask = np.isin(phase, WET)
    cell = np.isfinite(att)
    if keep == "wet":
        cell &= wet_mask[None, :]
    elif keep == "rain":
        cell &= (phase == "rain")[None, :]
    si, ti = np.where(cell)

    df = pd.DataFrame({
        "sublink": sub[si], "cml_id": cml[si], "band_tier": bt[si],
        "freq_GHz": f[si] / 1000.0, "length_km": L[si] / 1000.0,
        "polarisation": pol[si], "time": time[ti],
        "rsl": rsl[si, ti], "att": att[si, ti],
        "failure": fail[si, ti].astype(int), "phase": phase[ti],
        "precip_mm": precip[ti], "temp_c": temp[ti],
    })
    df["att_per_km"] = df["att"] / df["length_km"]
    return df


def _pooled_rh(net, freq):
    """Network-mean relative humidity (%) for a network dict, hourly.

    ASOS stations: RH from temperature+dewpoint via Magnus (`rh_from_dewpoint`).
    WU PWS stations: the reported `relative_humidity` directly. Per-station RH
    is resampled to `freq` then averaged across the network's stations.
    """
    from analysis.nycmesh_utils import rh_from_dewpoint
    cols = {}
    for sid, ds in net.items():
        if "relative_humidity" in ds:                       # WU PWS: direct RH
            s = ds["relative_humidity"].squeeze(drop=True).to_series().clip(0, 100)
        elif "temperature" in ds and "dewpoint" in ds:      # ASOS: Magnus
            T = ds["temperature"].squeeze(drop=True).to_series()
            Td = ds["dewpoint"].squeeze(drop=True).to_series()
            Td.index = pd.to_datetime(Td.index)
            s = rh_from_dewpoint(T, Td.reindex(pd.to_datetime(T.index)))
        else:
            continue
        s.index = pd.to_datetime(s.index)
        cols[sid] = s.resample(freq).mean()
    if not cols:
        return pd.Series(dtype=float)
    return pd.concat(cols, axis=1).mean(axis=1)


def add_wet_bulb(df: pd.DataFrame, *, asos_nc=ASOS_NC, pws_nc=PWS_NC,
                 freq: Optional[str] = None, col: str = "temp_wb_c",
                 pws_backfill: bool = True) -> pd.DataFrame:
    """Return a copy of `df` with an added wet-bulb temperature column `col`.

    The attenuation .nc stores only air `temp_c`, so wet-bulb is derived here and
    aligned onto df['time']. Wet-bulb = Stull (2011) of (air temp, RH):
      - air temperature : ASOS network hourly mean (matches `temp_c`), with WU
        network temperature filling hours ASOS is missing.
      - relative humidity : ASOS RH (Magnus from dewpoint), and where ASOS RH is
        missing — `pws_backfill` — the surrounding WU PWS `relative_humidity`.
        (ASOS has dewpoint at only ~98% of hours; WU airports + PWS cover the rest.)

    Use once, then pass `temp_col='temp_wb_c'` to the CDF plots:
        df = A.add_wet_bulb(df)
        A.plot_cdf_band_by_phase(df, ..., temp_bins=[...], temp_col='temp_wb_c')
    """
    from analysis.nycmesh_utils import load_weather_networks, wet_bulb_stull
    if freq is None:                               # infer df cadence so T_wb aligns
        t = pd.Series(pd.unique(df["time"])).sort_values()
        sec = t.diff().dt.total_seconds().median()
        freq = f"{int(round(sec / 60))}min" if np.isfinite(sec) and sec > 0 else "1h"
    nets = load_weather_networks(
        asos_nc=str(asos_nc),
        pws_nc=str(pws_nc) if (pws_backfill and pws_nc) else None, verbose=False)
    asos, pws = nets.get("ASOS", {}), nets.get("WU PWS", {})

    # Pool RH only; the air temperature is the stored `temp_c` (ASOS network mean),
    # so Tw is that exact temperature depressed by humidity → Tw <= temp_c always.
    RH = _pooled_rh(asos, freq)
    if pws_backfill and pws:                             # fill RH gaps from WU
        RH = RH.combine_first(_pooled_rh(pws, freq))

    out = df.copy()
    rh_row = out["time"].map(RH).to_numpy()
    out[col] = wet_bulb_stull(out["temp_c"].to_numpy(), rh_row)   # clamped Tw <= temp_c
    n_na = int(out[col].isna().sum())
    print(f"  add_wet_bulb: {col} filled for {len(out) - n_na:,}/{len(out):,} rows"
          + (f"; {n_na:,} still NaN (no temp_c or RH)" if n_na else ""))
    return out


def plot_links_map(nc_path=OUT_NC, *, cmls=None, separate_vbands: bool = True,
                   zoom_start: int = 11, tiles: str = "cartodbpositron"):
    """Interactive Folium map of the CML links — one polyline per parent link
    between its two site endpoints, coloured by band tier (the link's highest
    band). If `cmls` is given (e.g. multiband_cml_ids(df) or ['16','207']),
    those links are drawn highlighted and the rest dimmed grey, so you can see
    exactly which links a selection covers. Returns a folium.Map (renders inline).
    """
    import folium

    d = xr.open_dataset(nc_path)
    meta = pd.DataFrame({
        "cml_id": d["cml_id"].values.astype(str),
        "band_tier": d["band_tier"].values.astype(str),
        "freq_GHz": d["freq_MHz"].values / 1000.0,
        "length_km": d["length_m"].values / 1000.0,
        "s0lat": d["site_0_lat"].values, "s0lon": d["site_0_lon"].values,
        "s1lat": d["site_1_lat"].values, "s1lon": d["site_1_lon"].values,
    }).dropna(subset=["s0lat", "s0lon", "s1lat", "s1lon"])
    d.close()
    if not separate_vbands:
        meta["band_tier"] = meta["band_tier"].where(~meta["band_tier"].isin(_VBANDS), "V")

    sel = {str(c) for c in cmls} if cmls else None
    clat = pd.concat([meta["s0lat"], meta["s1lat"]]).mean()
    clon = pd.concat([meta["s0lon"], meta["s1lon"]]).mean()
    m = folium.Map(location=[clat, clon], zoom_start=zoom_start, tiles=tiles)

    bands_shown = set()
    for cid, g in meta.groupby("cml_id"):
        row = g.loc[g["freq_GHz"].idxmax()]           # representative (highest band)
        bands = "/".join(sorted(g["band_tier"].unique()))
        freqs = "/".join(f"{x:.1f}" for x in sorted(g["freq_GHz"].unique()))
        chosen = (sel is None) or (cid in sel)
        color = BAND_COLORS.get(row["band_tier"], "#888") if chosen else "#b8b8b8"
        if chosen:
            bands_shown.add(row["band_tier"])
        folium.PolyLine(
            [(row["s0lat"], row["s0lon"]), (row["s1lat"], row["s1lon"])],
            color=color, weight=5 if chosen else 1.5,
            opacity=0.9 if chosen else 0.35,
            popup=(f"CML {cid} | {g['cml_id'].size} sublinks | {bands} | "
                   f"{freqs} GHz | {row['length_km']:.2f} km"),
        ).add_to(m)

    title = (f"{len(sel)} selected of {meta['cml_id'].nunique()} links"
             if sel is not None else f"{meta['cml_id'].nunique()} CML links")
    rows = "".join(f"<div><span style='background:{BAND_COLORS[b]};'>&nbsp;&nbsp;</span> {b}</div>"
                   for b in BAND_ORDER + ("V",) if b in bands_shown)
    legend = (f"<div style='position:fixed;bottom:18px;left:18px;z-index:9999;"
              f"background:white;padding:8px;border:1px solid #888;font-size:12px;'>"
              f"<b>{title}</b>{rows}</div>")
    m.get_root().html.add_child(folium.Element(legend))
    return m


# ============================================================================
# 2.2  CDF of specific attenuation per band, conditioned on phase
# ============================================================================
def plot_cdf_by_phase_band(
    df: pd.DataFrame,
    *,
    bands: Sequence[str] = BAND_ORDER,
    phases: Optional[Sequence[str]] = None,   # subset e.g. ['snow']; None = all present
    cmls: Optional[Sequence[str]] = None,     # subset of parent links; None = all
    separate_vbands: bool = True,             # False = merge V-low+V-high into one "V"
    precip_range=None,              # rain-rate window: 'light'|'moderate'|'heavy'|'all'|(lo,hi) mm/hr
    mixed: str = "separate",        # 'separate' | 'drop' | 'fold_rain'
    value: str = "att_per_km",
    min_att: float = 0.0,
    xclip_pct: float = 99.5,        # clip each panel's x-axis to this percentile
    kind: str = "cdf",              # 'cdf' | 'pdf' (probability-density line)
    temp_bins: Optional[Sequence[float]] = None,
    temp_col: str = "temp_c",
    precip_bins: Optional[Sequence[float]] = None,  # rate-regime edges mm/hr, e.g. [0.1,2.5,7.5,np.inf]
    figsize=(18, 5),
    legend_fs: float = 10,
    label_fs: float = 12,
    title_fs: float = 13,
    save_path=None,
):
    """One CDF panel per band; rain vs snow (and optionally mixed) CDFs of
    specific attenuation. `mixed` knob: show separately, drop, or fold into rain.

    bands      subset of band tiers to panel, e.g. ['V-high', 'sub6'].
    phases     subset of phases to draw, e.g. ['snow']. None = all present.
    cmls       subset of parent links to pool, e.g. multiband_cml_ids(df).
               None = all links.
    min_att    lower cutoff on `value`; default 0.0 (positive attenuation only).
               Set to -np.inf to include the near-zero/negative mass (full dist).
    xclip_pct  right x-limit percentile; set to 100 (or None) to show the full
               tail so the CDF visibly reaches 1.0.
    temp_bins  optional temperature edges (degC) to split each phase's CDF by,
               e.g. [-np.inf, 0, np.inf] for below/at-or-above freezing, or
               [-np.inf, -5, 0, np.inf]. Phase is encoded by colour, temperature
               bin by line style. None = phase only (original behaviour).
    """
    import matplotlib.pyplot as plt

    _LS = ["-", "--", ":", "-."]

    work = _filter_cmls(df.copy(), cmls)
    work = _vmerge_work(work, separate_vbands)
    bands = _vmerge_bands(bands, separate_vbands)
    work = _precip_filter(work, precip_range)
    if mixed == "drop":
        work = work[work["phase"] != "mixed"]
    elif mixed == "fold_rain":
        work.loc[work["phase"] == "mixed", "phase"] = "rain"
    avail = [p for p in ("rain", "snow", "mixed") if p in work["phase"].unique()]
    phases = [p for p in phases if p in avail] if phases else avail

    if precip_bins is not None:                     # rain-rate regime -> line style
        work = work.copy()
        rlabels = _precip_bin_labels(precip_bins)
        work["_tbin"] = pd.cut(_precip_rate(work), bins=list(precip_bins),
                               labels=rlabels, right=False)
        tgroups = list(zip(rlabels, _LS))
    elif temp_bins is not None:                     # temp bin -> line style
        work = work[work[temp_col].notna()].copy()
        tlabels = _temp_bin_labels(temp_bins)
        work["_tbin"] = pd.cut(work[temp_col], bins=list(temp_bins),
                               labels=tlabels, right=False)
        tgroups = list(zip(tlabels, _LS))
    else:
        tgroups = [(None, "-")]

    def _draw(ax, vals, color, ls, label):
        _draw_dist(ax, vals, kind=kind, color=color, ls=ls, label=label, xclip_pct=xclip_pct)

    panels = [b for b in bands if b in work["band_tier"].unique()]
    fig, axes = plt.subplots(1, len(panels), figsize=figsize, sharey=True)
    if len(panels) == 1:
        axes = [axes]
    for ax, b in zip(axes, panels):
        sub = work[(work["band_tier"] == b) & (work[value] > min_att)]
        for ph in phases:
            ph_sub = sub[sub["phase"] == ph]
            for tlabel, ls in tgroups:
                vals = (ph_sub[value] if tlabel is None
                        else ph_sub.loc[ph_sub["_tbin"] == tlabel, value])
                _draw(ax, vals, PH_COLORS[ph], ls,
                      ph if tlabel is None else f"{ph}, {tlabel}")
        ax.set_title(b, fontsize=title_fs, fontweight="bold")
        ax.set_xlabel("Specific attenuation (dB/km)", fontsize=label_fs)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=legend_fs, title=(
            "Phase, rate" if precip_bins is not None
            else "Phase, temp" if temp_bins is not None else "Phase"))
        if xclip_pct and len(sub):
            ax.set_xlim(left=0, right=np.nanpercentile(sub[value].values, xclip_pct))
    axes[0].set_ylabel("PDF" if kind == "pdf" else "CDF", fontsize=label_fs)
    if precip_range not in (None, "all"):
        fig.suptitle(_regime_label(precip_range), fontsize=label_fs, y=1.02)
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=140, bbox_inches="tight")
    return {"fig": fig, "axes": axes}


def plot_cdf_band_by_phase(
    df: pd.DataFrame,
    *,
    phases: Sequence[str] = ("rain", "snow", "mixed"),
    facet_by: str = "phase",          # 'phase' = panel per phase | 'precip' = panel per rain regime
    bands: Sequence[str] = BAND_ORDER,
    cmls: Optional[Sequence[str]] = None,     # subset of parent links; None = all
    separate_vbands: bool = True,             # False = merge V-low+V-high into one "V"
    precip_range=None,              # rain-rate window: 'light'|'moderate'|'heavy'|'all'|(lo,hi) mm/hr
    value: str = "att_per_km",
    min_att: float = 0.0,
    xclip_pct: float = 99.5,
    kind: str = "cdf",              # 'cdf' | 'pdf' (probability-density line)
    temp_bins: Optional[Sequence[float]] = None,
    temp_col: str = "temp_c",
    precip_bins: Optional[Sequence[float]] = None,  # rate-regime edges mm/hr, e.g. [0.1,2.5,7.5,np.inf]
    figsize=(18, 5),
    legend_fs: float = 10,
    label_fs: float = 12,
    title_fs: float = 13,
    save_path=None,
):
    """Transpose of plot_cdf_by_phase_band: one CDF panel **per precipitation
    type**, with one CDF **per band** overlaid (colour = band), so the frequency
    dependence of attenuation is compared within a fixed precip type.

    phases     precip types to panel, e.g. ['rain','snow'] or ['snow'].
    bands      band tiers to overlay, e.g. ['V-high','sub6'].
    cmls       subset of parent links to pool, e.g. multiband_cml_ids(df) for the
               same-path multi-band CMLs. None = all links.
    min_att    lower cutoff on `value`; -np.inf includes the ≤0 mass (full dist).
    xclip_pct  right x-limit percentile; 100 (or None) shows the full tail.
    temp_bins  optional temperature edges (degC) to split each band by
               (line style); None = no temperature split.
    """
    import matplotlib.pyplot as plt

    _LS = ["-", "--", ":", "-."]

    work = _filter_cmls(df.copy(), cmls)
    work = _vmerge_work(work, separate_vbands)
    bands = _vmerge_bands(bands, separate_vbands)
    work = _precip_filter(work, precip_range)
    avail_ph = [p for p in ("rain", "snow", "mixed") if p in work["phase"].unique()]
    phases = [p for p in (phases or avail_ph) if p in avail_ph]
    band_list = [b for b in bands if b in work["band_tier"].unique()]
    n_links = work["cml_id"].nunique()

    # Panels: phase (default) or rain-rate regime (facet_by='precip').
    if facet_by == "precip":
        pbins = list(precip_bins) if precip_bins is not None else [0.1, 2.5, 7.5, np.inf]
        flabels = _precip_bin_labels(pbins)
        work = work[work["phase"].isin(phases)].copy()
        work["_fbin"] = pd.cut(_precip_rate(work), bins=pbins, labels=flabels, right=False)
        panel_col, panel_vals = "_fbin", flabels
        if temp_bins is not None:                   # line style = temp (precip is the facet)
            work = work[work[temp_col].notna()].copy()
            tlabels = _temp_bin_labels(temp_bins)
            work["_tbin"] = pd.cut(work[temp_col], bins=list(temp_bins),
                                   labels=tlabels, right=False)
            tgroups, line_split = list(zip(tlabels, _LS)), "temp"
        else:
            tgroups, line_split = [(None, "-")], None
    else:
        panel_col, panel_vals = "phase", phases
        if precip_bins is not None:                 # rain-rate regime -> line style
            work = work.copy()
            rlabels = _precip_bin_labels(precip_bins)
            work["_tbin"] = pd.cut(_precip_rate(work), bins=list(precip_bins),
                                   labels=rlabels, right=False)
            tgroups, line_split = list(zip(rlabels, _LS)), "rate"
        elif temp_bins is not None:                 # temp bin -> line style
            work = work[work[temp_col].notna()].copy()
            tlabels = _temp_bin_labels(temp_bins)
            work["_tbin"] = pd.cut(work[temp_col], bins=list(temp_bins),
                                   labels=tlabels, right=False)
            tgroups, line_split = list(zip(tlabels, _LS)), "temp"
        else:
            tgroups, line_split = [(None, "-")], None

    def _draw(ax, vals, color, ls, label):
        _draw_dist(ax, vals, kind=kind, color=color, ls=ls, label=label, xclip_pct=xclip_pct)

    leg_title = "Band" + (f", {line_split}" if line_split else "")
    fig, axes = plt.subplots(1, len(panel_vals), figsize=figsize, sharey=True)
    if len(panel_vals) == 1:
        axes = [axes]
    for ax, pv in zip(axes, panel_vals):
        p_sub = work[(work[panel_col] == pv) & (work[value] > min_att)]
        for b in band_list:
            b_sub = p_sub[p_sub["band_tier"] == b]
            for tlabel, ls in tgroups:
                vals = (b_sub[value] if tlabel is None
                        else b_sub.loc[b_sub["_tbin"] == tlabel, value])
                _draw(ax, vals, BAND_COLORS.get(b, "#888"), ls,
                      b if tlabel is None else f"{b}, {tlabel}")
        ax.set_title(str(pv), fontsize=title_fs, fontweight="bold")
        ax.set_xlabel("Specific attenuation (dB/km)", fontsize=label_fs)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=legend_fs, title=leg_title)
        if xclip_pct and len(p_sub):
            ax.set_xlim(left=(0 if min_att >= 0 else None),
                        right=np.nanpercentile(p_sub[value].values, xclip_pct))
    axes[0].set_ylabel("PDF" if kind == "pdf" else "CDF", fontsize=label_fs)
    bits = []
    if cmls:
        shown = [str(c) for c in cmls]
        bits.append("links: " + (", ".join(shown) if len(shown) <= 6 else f"{n_links} CMLs"))
    if precip_range not in (None, "all"):
        bits.append(_regime_label(precip_range))
    if bits:
        fig.suptitle("   |   ".join(bits), fontsize=label_fs, y=1.02)
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=140, bbox_inches="tight")
    return {"fig": fig, "axes": axes}


def plot_cdf_overlay(
    df: pd.DataFrame,
    *,
    bands: Sequence[str] = ("V-high", "sub6"),
    phases: Optional[Sequence[str]] = None,
    cmls: Optional[Sequence[str]] = None,
    separate_vbands: bool = True,
    precip_range=None,
    value: str = "att_per_km",
    min_att: float = 0.0,
    xclip_pct: float = 99.5,
    kind: str = "cdf",              # 'cdf' | 'pdf' (probability-density line)
    temp_bins: Optional[Sequence[float]] = None,
    temp_col: str = "temp_c",
    precip_bins: Optional[Sequence[float]] = None,  # rate-regime edges mm/hr, e.g. [0.1,2.5,7.5,np.inf]
    color_by: str = "phase",
    style_by: str = "band",
    figsize=(9, 6),
    legend_fs: float = 9,
    label_fs: float = 12,
    save_path=None,
):
    """All selected CDFs on ONE axes (merged, not faceted) — the single-panel
    version of plot_cdf_by_phase_band / plot_cdf_band_by_phase.

    Encodes two grouping dimensions: `color_by` and `style_by`, each one of
    'phase' | 'band' | 'temp' ('temp' needs `temp_bins`). e.g. the default
    color_by='phase', style_by='band' overlays rain/snow (colour) × V-high/sub6
    (line style) in a single panel. A dimension that varies but is mapped to
    neither is pooled, so restrict `bands`/`phases` to what you want shown.
    """
    import matplotlib.pyplot as plt
    _LS = ["-", "--", ":", "-."]

    work = _filter_cmls(df.copy(), cmls)
    work = _vmerge_work(work, separate_vbands)
    bands = _vmerge_bands(bands, separate_vbands)
    work = _precip_filter(work, precip_range)
    work = work[work["band_tier"].isin(list(bands))]
    avail = [p for p in ("rain", "snow", "mixed") if p in work["phase"].unique()]
    phs = [p for p in (phases or avail) if p in avail]
    work = work[work["phase"].isin(phs)]
    if temp_bins is not None:
        work = work[work[temp_col].notna()].copy()
        tlabels = _temp_bin_labels(temp_bins)
        work["_tbin"] = pd.cut(work[temp_col], bins=list(temp_bins),
                               labels=tlabels, right=False)
    rlabels = None
    if precip_bins is not None:
        rlabels = _precip_bin_labels(precip_bins)
        work = work.copy()
        work["_pbin"] = pd.cut(_precip_rate(work), bins=list(precip_bins),
                               labels=rlabels, right=False)
    work = work[work[value] > min_att]

    COL = {"phase": "phase", "band": "band_tier", "temp": "_tbin", "precip": "_pbin"}

    def _vals(dim):
        if dim == "phase":
            return phs
        if dim == "band":
            return [b for b in bands if b in work["band_tier"].unique()]
        if dim == "temp":
            if temp_bins is None:
                raise ValueError("color_by/style_by='temp' requires temp_bins")
            return tlabels
        if dim == "precip":
            if precip_bins is None:
                raise ValueError("color_by/style_by='precip' requires precip_bins")
            return rlabels
        raise ValueError(f"dim must be phase|band|temp|precip, got {dim!r}")

    cvals, svals = _vals(color_by), _vals(style_by)
    if color_by == "phase":
        cmap = {p: PH_COLORS.get(p, "#888") for p in cvals}
    elif color_by == "band":
        cmap = {b: BAND_COLORS.get(b, "#888") for b in cvals}
    else:
        cmap = dict(zip(cvals, plt.cm.coolwarm(np.linspace(0, 1, len(cvals)))))
    smap = {s: _LS[i % len(_LS)] for i, s in enumerate(svals)}

    fig, ax = plt.subplots(figsize=figsize)
    for cv in cvals:
        for sv in svals:
            seg = work[(work[COL[color_by]] == cv) & (work[COL[style_by]] == sv)]
            _draw_dist(ax, seg[value], kind=kind, color=cmap[cv], ls=smap[sv],
                       label=f"{cv} · {sv}", xclip_pct=xclip_pct)
    ax.set_xlabel("Specific attenuation (dB/km)", fontsize=label_fs)
    ax.set_ylabel("PDF" if kind == "pdf" else "CDF", fontsize=label_fs)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=legend_fs, title=f"{color_by} (colour) · {style_by} (line)")
    if precip_range not in (None, "all"):
        ax.set_title(_regime_label(precip_range), fontsize=label_fs)
    if xclip_pct and len(work):
        ax.set_xlim(left=(0 if min_att >= 0 else None),
                    right=np.nanpercentile(work[value].values, xclip_pct))
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=140, bbox_inches="tight")
    return {"fig": fig, "ax": ax}


def plot_cdf_temp_sweep(
    df: pd.DataFrame,
    *,
    phases: Sequence[str] = ("rain", "snow"),
    band: str = "V-high",
    thresholds: Sequence[float] = (-5, -2, 0, 2),
    side: str = "below",            # 'below' = temp < T | 'above' = temp >= T
    value: str = "att_per_km",
    min_att: float = 0.0,
    xclip_pct: float = 99.5,
    kind: str = "cdf",              # 'cdf' | 'pdf' (probability-density line)
    cmls: Optional[Sequence[str]] = None,
    separate_vbands: bool = True,
    precip_range=None,              # rain-rate window (mm/hr) to filter to: 'light'|'moderate'|'heavy'|'all'
    cmap: str = "viridis",          # colourmap for the temperature curves (kept off the band blue/red)
    colors: Optional[Sequence] = None,   # explicit per-bin colours (cold->warm order); overrides cmap
    temp_col: str = "temp_c",
    figsize=(13, 5),
    legend_fs: float = 10,
    label_fs: float = 12,
    title_fs: float = 13,
    save_path=None,
):
    """Temperature-threshold sensitivity sweep. For a fixed `band`, draw the CDF
    of specific attenuation on one side of each temperature threshold, one panel
    per phase — so you can see how the distribution shifts as the cut moves and
    where, e.g., snow loses its transparency. Colour runs cold -> warm via `cmap`
    (default 'viridis', kept off the band blue/red). `precip_range` restricts to a
    rain-rate window (mm/hr) so you can re-run per regime for separate figures.

    thresholds  temperature cuts (degC). For 'below'/'above' these are the cut
                points; for 'bins' they are bin EDGES (use ±np.inf at the ends),
                so pick few — e.g. [-np.inf, -2, 1, np.inf] → dry / transition / wet.
    side        'below' -> temp < T ; 'above' -> temp >= T (both one-sided and
                NESTED, for threshold sensitivity); 'bins' -> disjoint [lo, hi)
                intervals from consecutive thresholds (for dry vs wet snow).
    band        single band tier (attenuation magnitude is band-dependent, so
                bands are not mixed here).
    cmls        subset of parent links to pool (e.g. multiband_cml_ids(df)).
    """
    import matplotlib.pyplot as plt

    if isinstance(phases, str):
        phases = [phases]
    work = _filter_cmls(df.copy(), cmls)
    work = _vmerge_work(work, separate_vbands)
    work = _precip_filter(work, precip_range)
    work = work[(work["band_tier"] == band) & work[temp_col].notna()]
    # Build (label, lo, hi) interval specs. 'below'/'above' are one-sided
    # (overlapping, nested); 'bins' makes the thresholds disjoint [lo, hi) bins.
    ts = list(thresholds)
    if side == "below":
        specs = [(f"<{T:g}°C", -np.inf, T) for T in ts]
    elif side == "above":
        specs = [(f"≥{T:g}°C", T, np.inf) for T in ts]
    elif side == "bins":
        def _binlab(lo, hi):
            if np.isneginf(lo):
                return f"<{hi:g}°C"
            if np.isposinf(hi):
                return f"≥{lo:g}°C"
            return f"{lo:g}…{hi:g}°C"
        specs = [(_binlab(lo, hi), lo, hi) for lo, hi in zip(ts[:-1], ts[1:])]
    else:
        raise ValueError(f"side must be 'below', 'above' or 'bins', got {side!r}")
    if colors is not None:
        colours = [colors[i % len(colors)] for i in range(len(specs))]
    else:
        colours = plt.get_cmap(cmap)(np.linspace(0.12, 0.92, len(specs)))

    fig, axes = plt.subplots(1, len(phases), figsize=figsize, sharey=True)
    if len(phases) == 1:
        axes = [axes]
    for ax, ph in zip(axes, phases):
        ph_sub = work[(work["phase"] == ph) & (work[value] > min_att)]
        tcol = ph_sub[temp_col]
        for (lab, lo, hi), col in zip(specs, colours):
            _draw_dist(ax, ph_sub.loc[(tcol >= lo) & (tcol < hi), value],
                       kind=kind, color=col, ls="-", label=lab, xclip_pct=xclip_pct)
        ax.set_title(ph, fontsize=title_fs, fontweight="bold")
        ax.set_xlabel("Specific attenuation (dB/km)", fontsize=label_fs)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=legend_fs, title=f"{band}, temp {side}")
        if xclip_pct and len(ph_sub):
            ax.set_xlim(left=(0 if min_att >= 0 else None),
                        right=np.nanpercentile(ph_sub[value].values, xclip_pct))
    axes[0].set_ylabel("PDF" if kind == "pdf" else "CDF", fontsize=label_fs)
    if precip_range not in (None, "all"):
        fig.suptitle(f"{band}  ·  {_regime_label(precip_range)}", fontsize=label_fs, y=1.02)
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=140, bbox_inches="tight")
    return {"fig": fig, "axes": axes}


# ============================================================================
# 2.3  Temperature effect
# ============================================================================
def plot_temp_effect(
    df: pd.DataFrame,
    *,
    band: str = "V-high",
    value: str = "att_per_km",
    figsize=(8, 6),
    point_size: float = 14,
    label_fs: float = 12,
    title_fs: float = 13,
    save_path=None,
):
    """2-D scatter of specific attenuation vs ASOS temperature, coloured by
    phase, for one band. Communicates the warm-rain / cold-snow separation and
    where snow attenuation sits relative to rain at a given temperature.
    """
    import matplotlib.pyplot as plt

    sub = df[df["band_tier"] == band]
    fig, ax = plt.subplots(figsize=figsize)
    ph_alpha = {"rain": 0.3, "mixed": 0.9, "snow": 1.0}
    ph_edge = {"rain": "none", "mixed": _darken(PH_COLORS["mixed"]),
               "snow": _darken(PH_COLORS["snow"])}
    for ph in ("rain", "mixed", "snow"):
        s = sub[sub["phase"] == ph]
        if s.empty:
            continue
        ax.scatter(s["temp_c"], s[value], s=point_size, color=PH_COLORS[ph],
                   alpha=ph_alpha[ph], edgecolors=ph_edge[ph], linewidths=0.5,
                   label=f"{ph} (n={len(s)})")
    ax.axvline(0, color="k", ls="--", lw=0.8, alpha=0.5)
    ax.set_xlabel("ASOS temperature (°C)", fontsize=label_fs)
    ax.set_ylabel("Specific attenuation (dB/km)", fontsize=label_fs)
    ax.set_title(f"{band}: attenuation vs temperature by phase",
                 fontsize=title_fs, fontweight="bold")
    ax.grid(alpha=0.3)
    ax.legend(title="Phase")
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=140, bbox_inches="tight")
    return {"fig": fig, "axes": ax}


# ============================================================================
# 2.4  ITU-R P.838 rain-rate retrieval vs ASOS
# ============================================================================
def itu_rainrate_table(
    df: pd.DataFrame,
    *,
    band: str = "V-high",
    phase: str = "rain",
    min_link_hours: int = 30,
    min_precip_mm: float = 0.1,
) -> pd.DataFrame:
    """Per-link ITU-R rain-rate skill vs ASOS precip during `phase` hours.

    Returns one row per link: n hours, bias, RMSE, R2, Pearson r, median CML R,
    median ASOS rate. Uses the link's own frequency, length and polarisation.
    `min_precip_mm` restricts the comparison to hours with measurable ASOS rain
    (code-labeled 'rain' hours include many trace/zero-precip hours that
    otherwise dilute the rate retrieval).
    """
    sub = df[(df["band_tier"] == band) & (df["phase"] == phase)
             & (df["precip_mm"] >= min_precip_mm)].copy()
    pol_map = {"vertical": "V", "horizontal": "H", "": "V"}
    rows = []
    for sl, g in sub.groupby("sublink"):
        g = g[np.isfinite(g["att"]) & np.isfinite(g["precip_mm"])]
        if len(g) < min_link_hours:
            continue
        pol = pol_map.get(str(g["polarisation"].iloc[0]), "V")
        R = rain_rate_from_attenuation(g["att"].values, g["length_km"].iloc[0],
                                       g["freq_GHz"].iloc[0], pol)
        obs = g["precip_mm"].values
        err = R - obs
        ss_res = np.nansum(err ** 2)
        ss_tot = np.nansum((obs - obs.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
        r = np.corrcoef(R, obs)[0, 1] if len(R) > 2 and np.std(R) > 0 else np.nan
        rows.append(dict(
            sublink=sl, freq_GHz=round(g["freq_GHz"].iloc[0], 1),
            length_km=round(g["length_km"].iloc[0], 2), n_hours=len(g),
            bias_mmh=round(np.nanmean(err), 2), rmse_mmh=round(np.sqrt(np.nanmean(err ** 2)), 2),
            R2=round(r2, 3), pearson_r=round(r, 3),
            med_cml_R=round(np.nanmedian(R), 2), med_asos=round(np.nanmedian(obs), 2),
        ))
    return pd.DataFrame(rows).sort_values("pearson_r", ascending=False).reset_index(drop=True)


def plot_itu_scatter(
    df: pd.DataFrame,
    *,
    band: str = "V-high",
    color_by_phase: bool = True,
    max_rate: float = 60.0,
    min_precip_mm: float = 0.1,
    figsize=(7, 7),
    point_size: float = 12,
    label_fs: float = 12,
    title_fs: float = 13,
    save_path=None,
):
    """CML-estimated rain rate vs ASOS rate, one point per link-hour, coloured
    by phase. Snow/mixed points show where the rain-only retrieval breaks down.
    `min_precip_mm` keeps only hours with measurable ASOS precip for the rain
    points (snow/mixed are always shown, to expose the rain-only failure).
    """
    import matplotlib.pyplot as plt

    sub = df[df["band_tier"] == band].copy()
    sub = sub[(sub["phase"] != "rain") | (sub["precip_mm"] >= min_precip_mm)]
    pol_map = {"vertical": "V", "horizontal": "H", "": "V"}
    sub["pol"] = sub["polarisation"].map(lambda p: pol_map.get(str(p), "V"))
    R = np.empty(len(sub))
    for pol in sub["pol"].unique():
        m = (sub["pol"] == pol).values
        R[m] = rain_rate_from_attenuation(sub["att"].values[m],
                                          sub["length_km"].values[m],
                                          sub["freq_GHz"].values[m], pol)
    sub["cml_R"] = R

    fig, ax = plt.subplots(figsize=figsize)
    ph_alpha = {"rain": 0.3, "mixed": 0.9, "snow": 1.0}
    ph_edge = {"rain": "none", "mixed": _darken(PH_COLORS["mixed"]),
               "snow": _darken(PH_COLORS["snow"])}
    order = ("rain", "mixed", "snow") if color_by_phase else ("rain",)
    for ph in order:
        s = sub[sub["phase"] == ph] if color_by_phase else sub
        if s.empty:
            continue
        ax.scatter(s["precip_mm"], s["cml_R"], s=point_size, color=PH_COLORS[ph],
                   alpha=ph_alpha[ph], edgecolors=ph_edge[ph], linewidths=0.5,
                   label=f"{ph} (n={len(s)})")
    lim = max_rate
    ax.plot([0, lim], [0, lim], "k--", lw=1, alpha=0.6, label="1:1")
    ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.set_xlabel("ASOS precip rate (mm/h)", fontsize=label_fs)
    ax.set_ylabel("CML ITU-R retrieved rain rate (mm/h)", fontsize=label_fs)
    ax.set_title(f"{band}: CML vs ASOS rain rate", fontsize=title_fs, fontweight="bold")
    ax.grid(alpha=0.3); ax.legend(title="Phase")
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=140, bbox_inches="tight")
    return {"fig": fig, "axes": ax, "data": sub}


# ============================================================================
# 2.5  Multi-band same-CML analysis
# ============================================================================
def find_multiband_cmls(nc_path=OUT_NC, min_df_ghz: float = 1.0) -> pd.DataFrame:
    """CMLs whose sublinks span >1 frequency band (max-min freq > min_df_ghz).
    Returns cml_id, n_sublinks, bands, freq spread, length."""
    d = xr.open_dataset(nc_path)
    meta = pd.DataFrame({
        "cml_id": d["cml_id"].values, "sublink": d["sublink"].values,
        "band_tier": d["band_tier"].values, "freq_GHz": d["freq_MHz"].values / 1000.0,
        "length_km": d["length_m"].values / 1000.0,
    })
    rows = []
    for cid, g in meta.groupby("cml_id"):
        if g["freq_GHz"].max() - g["freq_GHz"].min() > min_df_ghz:
            rows.append(dict(
                cml_id=cid, n_sublinks=len(g),
                bands="/".join(sorted(g["band_tier"].unique())),
                freqs_GHz="/".join(f"{x:.1f}" for x in sorted(g["freq_GHz"].unique())),
                df_GHz=round(g["freq_GHz"].max() - g["freq_GHz"].min(), 1),
                length_km=round(g["length_km"].iloc[0], 2),
            ))
    return pd.DataFrame(rows).sort_values("df_GHz", ascending=False).reset_index(drop=True)


def multiband_phase_stats(df: pd.DataFrame, cml_id: str) -> pd.DataFrame:
    """Mean/median specific attenuation per (sublink, phase) for one CML, so the
    same physical path can be compared across its bands."""
    sub = df[df["cml_id"] == cml_id]
    g = (sub.groupby(["sublink", "freq_GHz", "phase"])["att_per_km"]
         .agg(["mean", "median", "count"]).round(3).reset_index())
    return g.sort_values(["freq_GHz", "phase"]).reset_index(drop=True)


def plot_multiband_bars(
    df: pd.DataFrame,
    cml_id: str,
    *,
    stat: str = "median",
    per_sublink: bool = False,
    min_count: int = 20,
    figsize=(9, 5),
    save_path=None,
):
    """Grouped bar of specific attenuation by band x phase for one CML, so the
    same physical path is compared across its carrier frequencies.

    stat         'median' | 'mean' | 'p90' (90th percentile). POOLS all
                 sublink-hours at each (freq, phase) rather than averaging the
                 per-sublink medians (which silently mixes sublinks of differing
                 quality and can flip sign). 'median' sits near the noise floor
                 for weak bands; 'p90' surfaces the real wet tail.
    per_sublink  one bar group per sublink instead of per frequency, exposing
                 within-band disagreement (e.g. a biased sublink reading < 0).
    min_count    drop (group, phase) cells backed by fewer than this many hours.
    """
    import matplotlib.pyplot as plt

    aggs = {"median": lambda s: s.median(),
            "mean": lambda s: s.mean(),
            "p90": lambda s: s.quantile(0.90)}
    if stat not in aggs:
        raise ValueError(f"stat must be one of {list(aggs)}")

    sub = df[df["cml_id"] == cml_id]
    key = "sublink" if per_sublink else "freq_GHz"
    grp = sub.groupby([key, "phase"])["att_per_km"]
    val = grp.agg(aggs[stat]).where(grp.size() >= min_count)
    piv = val.unstack("phase")
    piv = piv[[p for p in ("rain", "mixed", "snow") if p in piv.columns]].dropna(how="all")
    if not per_sublink:                          # tidy float-GHz tick labels
        piv.index = np.round(piv.index.astype(float), 1)

    fig, ax = plt.subplots(figsize=figsize)
    piv.plot(kind="bar", ax=ax, color=[PH_COLORS.get(c, "#888") for c in piv.columns])
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xlabel("Sublink" if per_sublink else "Sublink carrier frequency (GHz)")
    ax.set_ylabel(f"{stat} specific attenuation (dB/km)")
    ax.set_title(f"CML {cml_id}: same path, {stat} attenuation by "
                 f"{'sublink' if per_sublink else 'band'} and phase  (n ≥ {min_count})")
    ax.grid(alpha=0.3, axis="y")
    ax.legend(title="Phase", fontsize=9)
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=140, bbox_inches="tight")
    return {"fig": fig, "ax": ax, "data": piv}


# ============================================================================
# Per-link baseline diagnostic time series (RSL + baselines + ASOS context)
# ============================================================================
def plot_link_baselines(
    sublink: str,
    *,
    methods: Sequence[str] = ("ewma", "rollq"),
    window: Optional[Tuple[str, str]] = None,
    nc_path=OUT_NC,
    show_temp: bool = True,
    figsize=(15, 9),
    save_path=None,
):
    """Diagnostic time series for one sublink, to compare baseline methods.

    Three stacked panels sharing the time axis:
      (top)    hourly RSL (dBm) with the chosen baseline(s) overlaid;
      (middle) the resulting attenuation = baseline - RSL (dB) with a 0-line,
               so negative (unphysical) excursions are visible per method;
      (bottom) ASOS network precip (mm, bars) and temperature (degC, line).
    Wet hours are shaded by phase (rain/mixed/snow) on every panel.

    sublink  "<cml_id>::<sublink_id>" key, or a bare cml_id (first sublink used).
    methods  baseline methods to overlay: any of 'static','rollq','drymed','ewma'.
    window   (start, end) strings; default = padded window around this sublink's
             highest-precip event so a real storm is in view.
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    methods = [m.replace("att_", "") for m in methods]
    d = xr.open_dataset(nc_path)
    sl = d["sublink"].values.astype(str)
    if sublink in sl:
        i = int(np.where(sl == sublink)[0][0])
    else:                                   # treat as cml_id; take first sublink
        cml = d["cml_id"].values.astype(str)
        cand = np.where(cml == str(sublink))[0]
        if len(cand) == 0:
            d.close()
            raise ValueError(f"no sublink or cml_id matching {sublink!r}")
        i = int(cand[0])

    time = pd.to_datetime(d["time"].values)
    rsl = pd.Series(d["rsl"].values[i], index=time)
    att = {m: pd.Series(d[f"att_{m}"].values[i], index=time) for m in methods}
    base = {m: rsl + att[m] for m in methods}          # baseline = RSL + att
    phase = pd.Series(d["phase"].values.astype(str), index=time)
    precip = pd.Series(d["precip_mm"].values, index=time)
    temp = pd.Series(d["temp_c"].values, index=time)
    event = pd.Series(d["event_id"].values, index=time)
    freq = float(d["freq_MHz"].values[i]) / 1000.0
    length_km = float(d["length_m"].values[i]) / 1000.0
    band, key = str(d["band_tier"].values[i]), sl[i]
    d.close()

    if window is None:
        # highest-precip event *among hours this sublink actually reports*, so the
        # window is not an event the link missed (NaN RSL -> contributes 0 precip).
        valid = rsl.notna()
        ev_tot = precip.where(valid, 0.0).groupby(event.values).sum()
        ev_tot = ev_tot[ev_tot.index > 0]
        if len(ev_tot) and ev_tot.max() > 0:
            ev_t = time[event.values == ev_tot.idxmax()]
            t0, t1 = ev_t.min() - pd.Timedelta("2D"), ev_t.max() + pd.Timedelta("2D")
        elif valid.any():                       # no wet overlap: show its data span
            t0, t1 = time[valid].min(), time[valid].max()
        else:
            t0, t1 = time.min(), time.max()
    else:
        t0, t1 = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    sel = slice(t0, t1)

    n_panel = 3 if show_temp else 2
    fig, axes = plt.subplots(
        n_panel, 1, figsize=figsize, sharex=True,
        gridspec_kw={"height_ratios": [3, 2, 1.4][:n_panel]})

    def _shade(ax):
        idx = phase[sel].index
        for ph in WET:
            ax.fill_between(idx, 0, 1, where=(phase[sel] == ph).values,
                            transform=ax.get_xaxis_transform(),
                            color=PH_COLORS[ph], alpha=0.12, lw=0, step="mid")

    ax_rsl, ax_att = axes[0], axes[1]
    _shade(ax_rsl)
    ax_rsl.plot(rsl[sel].index, rsl[sel].values, color="0.45", lw=0.8, label="RSL")
    for m in methods:
        ax_rsl.plot(base[m][sel].index, base[m][sel].values,
                    color=METHOD_COLORS[m], lw=1.6, label=f"baseline {m}")
    ax_rsl.set_ylabel("RSL / baseline (dBm)")
    ax_rsl.set_title(f"{key}   |   {band}  {freq:.1f} GHz   |   L = {length_km:.2f} km")
    ax_rsl.legend(ncol=len(methods) + 1, fontsize=9, loc="lower left")
    ax_rsl.grid(alpha=0.3)

    _shade(ax_att)
    ax_att.axhline(0, color="k", lw=0.9)
    for m in methods:
        ax_att.plot(att[m][sel].index, att[m][sel].values,
                    color=METHOD_COLORS[m], lw=1.4, label=f"att {m}")
    ax_att.set_ylabel("Attenuation (dB)")
    ax_att.legend(ncol=len(methods), fontsize=9, loc="upper left")
    ax_att.grid(alpha=0.3)

    if show_temp:
        ax_w = axes[2]
        ax_w.bar(precip[sel].index, precip[sel].values, width=0.04,
                 color="#2166ac", alpha=0.6)
        ax_w.set_ylabel("precip (mm)", color="#2166ac")
        ax_w.tick_params(axis="y", labelcolor="#2166ac")
        ax_t = ax_w.twinx()
        ax_t.plot(temp[sel].index, temp[sel].values, color="#d62728", lw=1.0)
        ax_t.axhline(0, color="#d62728", lw=0.6, ls=":")
        ax_t.set_ylabel("temp (°C)", color="#d62728")
        ax_t.tick_params(axis="y", labelcolor="#d62728")
        ax_w.grid(alpha=0.3)
    axes[-1].set_xlabel("time")
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    fig.autofmt_xdate()
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=140, bbox_inches="tight")
    return {"fig": fig, "axes": axes, "sublink": key, "window": (t0, t1)}
