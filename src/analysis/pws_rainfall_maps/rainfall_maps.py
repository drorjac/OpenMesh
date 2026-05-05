"""
rainfall_maps.py - Rainfall map generation from QC-applied PWS data.

All figures are saved to out_dir. plt.show() is never called - figures
close automatically so the pipeline runs without any popup windows.

Supports both IDW and Ordinary Kriging interpolation methods.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # non-interactive backend - no popup windows

import matplotlib.animation as animation
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
import matplotlib.cm as cm

from idw import idw_interpolate, make_grid
from kriging import kriging_interpolate, PYKRIGE_AVAILABLE

DEFAULT_AGG_MINUTES = 15
DEFAULT_EVENT_HOURS = 2
DEFAULT_MIN_STATIONS = 3
DEFAULT_GIF_FPS = 2
DEFAULT_GIF_DPI = 120

# Helpers

def _vmax(arr: np.ndarray, percentile: float = 99) -> float:
    flat = np.asarray(arr).flatten()
    finite = flat[np.isfinite(flat)]
    if len(finite) == 0:
        return 0.01
    return max(float(np.percentile(finite, percentile)), 0.01)

def _save(fig: plt.Figure, out_dir: Path | None, fname: str) -> None:
    if out_dir:
        fig.savefig(Path(out_dir) / fname, dpi=150, bbox_inches="tight")
    plt.close(fig)


# Data preparation

def resample_to_windows(
    ds_pws_qc: xr.Dataset,
    rain_var: str = "rainfall_amount",
    agg_minutes: int = DEFAULT_AGG_MINUTES,
) -> xr.DataArray:
    """Resample QC-applied PWS data to fixed-length accumulation windows."""
    return ds_pws_qc[rain_var].resample(time=f"{agg_minutes}min").sum(skipna=True)


def find_peak_event(
    pws_agg: xr.DataArray,
    min_stations: int = DEFAULT_MIN_STATIONS,
    event_hours: int  = DEFAULT_EVENT_HOURS,
) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, xr.DataArray]:
    """Find the wettest aggregation window and define an event window around it."""
    valid_counts = (~np.isnan(pws_agg)).sum(dim="id")
    network_total = pws_agg.sum(dim="id", skipna=True).where(
        valid_counts >= min_stations
    )
    peak_idx = int(network_total.fillna(0).argmax(dim="time").values)
    peak_t = pd.Timestamp(pws_agg.time.values[peak_idx])
    event_start = peak_t - pd.Timedelta(hours=event_hours)
    event_end = peak_t + pd.Timedelta(hours=event_hours)
    pws_event = pws_agg.sel(time=slice(event_start, event_end))

    print(f"Peak window : {peak_t}")
    print(f"Event window : {event_start} -> {event_end}  ({pws_event.sizes['time']} windows)")
    print(f"Stations at peak: {int(valid_counts.isel(time=peak_idx))}")
    return peak_t, event_start, event_end, pws_event


# Map functions

def plot_event_detection(
    pws_agg: xr.DataArray,
    peak_t: pd.Timestamp,
    event_start: pd.Timestamp,
    event_end: pd.Timestamp,
    agg_minutes: int = DEFAULT_AGG_MINUTES,
    min_stations: int = DEFAULT_MIN_STATIONS,
    out_dir: Path | None = None,
) -> None:
    """Network-total rainfall time series with peak event highlighted."""
    valid_counts = (~np.isnan(pws_agg)).sum(dim="id")
    network_total = pws_agg.sum(dim="id", skipna=True).where(
        valid_counts >= min_stations
    )
    fig, ax = plt.subplots(figsize=(12, 3))
    ax.bar(pd.DatetimeIndex(network_total.time.values),
           network_total.fillna(0).values,
           width=pd.Timedelta(minutes=agg_minutes), color="steelblue", alpha=0.8)
    ax.axvline(peak_t, color="red", linestyle="--",
               label=f"Peak: {peak_t.strftime('%b %d %H:%M')}")
    ax.axvspan(event_start, event_end, alpha=0.1, color="red", label="Event window")
    ax.set_ylabel(f"Network total (mm / {agg_minutes} min)")
    ax.set_title("PWS QC Network-Total Rainfall - Event Detection")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.legend(); ax.grid(True, alpha=0.3)
    plt.tight_layout()
    _save(fig, out_dir, "fig_pws_event_detection.png")
    print(f"  Saved: fig_pws_event_detection.png")


def plot_single_map(
    pws_agg: xr.DataArray,
    peak_t: pd.Timestamp,
    pws_lons: np.ndarray,
    pws_lats: np.ndarray,
    station_ids: np.ndarray,
    grid_lon: np.ndarray,
    grid_lat: np.ndarray,
    method: str = "idw",
    agg_minutes: int = DEFAULT_AGG_MINUTES,
    idw_power: int = 2,
    out_dir: Path | None = None,
) -> None:
    """IDW or Kriging map for the peak aggregation window."""
    peak_vals = pws_agg.sel(time=peak_t, method="nearest").values

    if method == "kriging" and PYKRIGE_AVAILABLE:
        grid_rain, grid_var = kriging_interpolate(
            pws_lons, pws_lats, peak_vals, grid_lon, grid_lat)
        method_label = "Ordinary Kriging (pykrige)"
    else:
        grid_rain = idw_interpolate(pws_lons, pws_lats, peak_vals,
                                    grid_lon, grid_lat, power=idw_power)
        method_label = f"IDW (p={idw_power})"

    vmax = _vmax(grid_rain)
    fig, ax = plt.subplots(figsize=(9, 8))
    im = ax.pcolormesh(grid_lon, grid_lat, grid_rain,
                       cmap="Blues", vmin=0, vmax=vmax, shading="auto")
    plt.colorbar(im, ax=ax, label=f"Rainfall (mm / {agg_minutes} min)", shrink=0.8)
    ax.scatter(pws_lons, pws_lats,
               c=np.nan_to_num(peak_vals), cmap="Blues", vmin=0, vmax=vmax,
               s=80, edgecolors="black", linewidths=0.8, zorder=5)
    for i, sid in enumerate(station_ids):
        if not np.isnan(peak_vals[i]):
            ax.annotate(f"{peak_vals[i]:.2f}", (pws_lons[i], pws_lats[i]),
                        textcoords="offset points", xytext=(4, 4),
                        fontsize=6, color="darkblue")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.set_title(f"Rainfall Map - {peak_t.strftime('%Y-%m-%d %H:%M')} UTC\n"
                 f"{agg_minutes}-min accumulation  |  QC-applied  |  {method_label}")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    fname = f"fig_pws_{method}_peak.png"
    _save(fig, out_dir, fname)
    print(f"  Saved: {fname}  ({(~np.isnan(peak_vals)).sum()} stations)")


def plot_idw_vs_kriging(
    pws_agg: xr.DataArray,
    peak_t: pd.Timestamp,
    pws_lons: np.ndarray,
    pws_lats: np.ndarray,
    grid_lon: np.ndarray,
    grid_lat: np.ndarray,
    agg_minutes: int = DEFAULT_AGG_MINUTES,
    idw_power: int = 2,
    out_dir: Path | None = None,
) -> None:
    """Side-by-side comparison of IDW and Ordinary Kriging at peak timestamp."""
    if not PYKRIGE_AVAILABLE:
        print("  Skipping IDW vs Kriging comparison - pykrige not installed.")
        return

    peak_vals = pws_agg.sel(time=peak_t, method="nearest").values
    grid_idw  = idw_interpolate(pws_lons, pws_lats, peak_vals, grid_lon, grid_lat,
                                 power=idw_power)
    grid_krig, grid_var = kriging_interpolate(pws_lons, pws_lats, peak_vals,
                                               grid_lon, grid_lat)

    vmax = max(_vmax(grid_idw), _vmax(grid_krig))

    fig, axes = plt.subplots(1, 3, figsize=(20, 7))

    for ax, grid, label in [
        (axes[0], grid_idw,  f"IDW (p={idw_power})"),
        (axes[1], grid_krig, "Ordinary Kriging"),
    ]:
        im = ax.pcolormesh(grid_lon, grid_lat, grid,
                           cmap="Blues", vmin=0, vmax=vmax, shading="auto")
        plt.colorbar(im, ax=ax, label=f"mm / {agg_minutes} min", shrink=0.8)
        ax.scatter(pws_lons, pws_lats,
                   c=np.nan_to_num(peak_vals), cmap="Blues", vmin=0, vmax=vmax,
                   s=50, edgecolors="black", linewidths=0.6, zorder=5)
        for i in range(len(pws_lons)):
            if not np.isnan(peak_vals[i]) and peak_vals[i] > 0:
                ax.annotate(f"{peak_vals[i]:.2f}",
                            (pws_lons[i], pws_lats[i]),
                            textcoords="offset points", xytext=(4, 4),
                            fontsize=6, color="darkblue")
        ax.set_title(label); ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
        ax.grid(True, alpha=0.3)

    # Kriging variance (uncertainty) panel
    ax = axes[2]
    cmap_var = cm.get_cmap("YlOrRd").copy()
    cmap_var.set_bad(color="white")
    im2 = ax.pcolormesh(grid_lon, grid_lat, grid_var,
                     cmap=cmap_var, shading="auto")
    plt.colorbar(im2, ax=ax, label="Kriging Variance", shrink=0.8)
    ax.scatter(pws_lons, pws_lats, c="red", s=30, zorder=5)
    for i in range(len(pws_lons)):
            if not np.isnan(peak_vals[i]) and peak_vals[i] > 0:
                ax.annotate(f"{peak_vals[i]:.2f}",
                            (pws_lons[i], pws_lats[i]),
                            textcoords="offset points", xytext=(4, 4),
                            fontsize=6, color="darkblue")
    ax.set_title("Kriging Uncertainty (Variance)")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.grid(True, alpha=0.3)

    fig.suptitle(f"IDW vs Ordinary Kriging - {peak_t.strftime('%Y-%m-%d %H:%M')} UTC  "
                 f"|  {agg_minutes}-min  |  QC-applied",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    _save(fig, out_dir, "fig_pws_idw_vs_kriging.png")
    print("  Saved: fig_pws_idw_vs_kriging.png")


def plot_event_panels(
    pws_event: xr.DataArray,
    peak_t: pd.Timestamp,
    pws_lons: np.ndarray,
    pws_lats: np.ndarray,
    grid_lon: np.ndarray,
    grid_lat: np.ndarray,
    method: str = "idw",
    agg_minutes: int = DEFAULT_AGG_MINUTES,
    idw_power: int = 2,
    ncols: int = 4,
    out_dir: Path | None = None,
) -> None:
    """Multi-panel figure: one panel per aggregation window across the event."""
    times_event = pd.DatetimeIndex(pws_event.time.values)
    n_panels = len(times_event)
    nrows = int(np.ceil(n_panels / ncols))
    vmax_event  = _vmax(pws_event.values)

    fig, axes = plt.subplots(nrows, ncols,
                              figsize=(ncols * 4, nrows * 4),
                              constrained_layout=True)
    axes_flat = np.array(axes).flatten()

    for k, t in enumerate(times_event):
        ax   = axes_flat[k]
        vals = pws_event.sel(time=t).values

        if method == "kriging" and PYKRIGE_AVAILABLE:
            grid, _ = kriging_interpolate(pws_lons, pws_lats, vals, grid_lon, grid_lat)
        else:
            grid = idw_interpolate(pws_lons, pws_lats, vals, grid_lon, grid_lat,
                                   power=idw_power)

        im = ax.pcolormesh(grid_lon, grid_lat, grid,
                           cmap="Blues", vmin=0, vmax=vmax_event, shading="auto")
        ax.scatter(pws_lons, pws_lats,
                   c=np.nan_to_num(vals), cmap="Blues", vmin=0, vmax=vmax_event,
                   s=20, edgecolors="black", linewidths=0.4, zorder=5)
        label = " << PEAK" if pd.Timestamp(t) == peak_t else ""
        ax.set_title(f"{pd.Timestamp(t).strftime('%H:%M')}{label}", fontsize=9)
        ax.set_xticks([]); ax.set_yticks([])

    for k in range(n_panels, len(axes_flat)):
        axes_flat[k].set_visible(False)

    fig.colorbar(im, ax=axes_flat[:n_panels], location="right",
                 label=f"mm / {agg_minutes} min", shrink=0.6)
    method_label = "Ordinary Kriging" if method == "kriging" else f"IDW p={idw_power}"
    fig.suptitle(
        f"PWS Rainfall Maps - {times_event[0].strftime('%Y-%m-%d')}\n"
        f"{agg_minutes}-min  |  QC-applied  |  {method_label}",
        fontsize=12, fontweight="bold",
    )
    fname = f"fig_pws_{method}_event_panels.png"
    _save(fig, out_dir, fname)
    print(f"  Saved: {fname}  ({n_panels} panels)")


def save_event_gif(
    pws_event: xr.DataArray,
    peak_t: pd.Timestamp,
    pws_lons: np.ndarray,
    pws_lats: np.ndarray,
    grid_lon: np.ndarray,
    grid_lat: np.ndarray,
    method: str = "idw",
    agg_minutes: int = DEFAULT_AGG_MINUTES,
    idw_power: int = 2,
    fps: int = DEFAULT_GIF_FPS,
    dpi: int = DEFAULT_GIF_DPI,
    out_dir: Path | None = None,
) -> Path:
    """Animated GIF of the IDW or Kriging rainfall field evolving over the event."""
    times_event = pd.DatetimeIndex(pws_event.time.values)
    method_label = "Ordinary Kriging" if method == "kriging" else f"IDW p={idw_power}"

    # Pre-compute all grids
    all_grids = []
    for t in times_event:
        vals = pws_event.sel(time=t).values
        if method == "kriging" and PYKRIGE_AVAILABLE:
            grid, _ = kriging_interpolate(pws_lons, pws_lats, vals, grid_lon, grid_lat)
        else:
            grid = idw_interpolate(pws_lons, pws_lats, vals, grid_lon, grid_lat,
                                   power=idw_power)
        all_grids.append(grid)

    vmax_gif = _vmax(pws_event.values)

    fig_gif, ax_gif = plt.subplots(figsize=(7, 6))
    plt.subplots_adjust(left=0.1, right=0.88, top=0.88, bottom=0.08)

    mesh = ax_gif.pcolormesh(grid_lon, grid_lat, all_grids[0],
                              cmap="Blues", vmin=0, vmax=vmax_gif, shading="auto")
    scat = ax_gif.scatter(pws_lons, pws_lats,
                           c=np.nan_to_num(pws_event.isel(time=0).values),
                           cmap="Blues", vmin=0, vmax=vmax_gif,
                           s=40, edgecolors="black", linewidths=0.5, zorder=5)
    plt.colorbar(mesh, ax=ax_gif, label=f"mm / {agg_minutes} min", shrink=0.85)
    ax_gif.set_xlabel("Longitude"); ax_gif.set_ylabel("Latitude")
    ax_gif.grid(True, alpha=0.3)
    title = ax_gif.set_title("")

    def _update(k: int):
        t    = times_event[k]
        vals = pws_event.isel(time=k).values
        mesh.set_array(all_grids[k].ravel())
        scat.set_array(np.nan_to_num(vals))
        peak_label = "  << PEAK" if t == peak_t else ""
        title.set_text(
            f"PWS Rainfall - {t.strftime('%Y-%m-%d %H:%M')} UTC{peak_label}\n"
            f"{agg_minutes}-min  |  QC-applied  |  {method_label}"
        )
        return mesh, scat, title

    ani = animation.FuncAnimation(
        fig_gif, _update, frames=len(times_event),
        interval=1000 // fps, blit=False, repeat=True,
    )
    gif_path = Path(out_dir or ".") / f"fig_pws_{method}_event.gif"
    ani.save(str(gif_path), writer="pillow", fps=fps, dpi=dpi)
    plt.close(fig_gif)
    print(f"  Saved: {gif_path.name}  ({len(times_event)} frames)")
    return gif_path


def plot_accumulated_map(
    pws_event: xr.DataArray,
    event_start: pd.Timestamp,
    event_end: pd.Timestamp,
    pws_lons: np.ndarray,
    pws_lats: np.ndarray,
    station_ids: np.ndarray,
    grid_lon: np.ndarray,
    grid_lat: np.ndarray,
    method: str = "idw",
    idw_power: int = 2,
    out_dir: Path | None = None,
) -> None:
    """Map of total rainfall accumulated over the full event window."""
    event_total  = pws_event.sum(dim="time", skipna=True).values
    no_data_mask = np.isnan(pws_event).all(dim="time").values
    event_total  = np.where(no_data_mask, np.nan, event_total)

    if method == "kriging" and PYKRIGE_AVAILABLE:
        grid_accum, _ = kriging_interpolate(pws_lons, pws_lats, event_total,
                                             grid_lon, grid_lat)
        method_label = "Ordinary Kriging"
    else:
        grid_accum = idw_interpolate(pws_lons, pws_lats, event_total,
                                      grid_lon, grid_lat, power=idw_power)
        method_label = f"IDW p={idw_power}"

    vmax_acc = _vmax(grid_accum)
    fig, ax = plt.subplots(figsize=(9, 8))
    im = ax.pcolormesh(grid_lon, grid_lat, grid_accum,
                       cmap="YlGnBu", vmin=0, vmax=vmax_acc, shading="auto")
    plt.colorbar(im, ax=ax, label="Total Accumulation (mm)", shrink=0.8)
    ax.scatter(pws_lons, pws_lats,
               c=np.nan_to_num(event_total), cmap="YlGnBu", vmin=0, vmax=vmax_acc,
               s=80, edgecolors="black", linewidths=0.8, zorder=5)
    for i, sid in enumerate(station_ids):
        if not np.isnan(event_total[i]):
            ax.annotate(f"{event_total[i]:.2f}", (pws_lons[i], pws_lats[i]),
                        textcoords="offset points", xytext=(4, 4),
                        fontsize=6, color="darkgreen")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.set_title(f"PWS Accumulated Rainfall - Event Total\n"
                 f"{event_start.strftime('%Y-%m-%d %H:%M')} – {event_end.strftime('%H:%M')} UTC  "
                 f"|  QC-applied  |  {method_label}")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    fname = f"fig_pws_{method}_accum.png"
    _save(fig, out_dir, fname)
    print(f"  Saved: {fname}")

    print("Station accumulations (mm):")
    for i, sid in enumerate(station_ids):
        if not np.isnan(event_total[i]):
            print(f"  {sid}: {event_total[i]:.3f}")


def plot_raw_vs_qc(
    ds_pws_stacked: xr.Dataset,
    pws_agg: xr.DataArray,
    peak_t: pd.Timestamp,
    pws_lons: np.ndarray,
    pws_lats: np.ndarray,
    grid_lon: np.ndarray,
    grid_lat: np.ndarray,
    rain_var: str = "rainfall_amount",
    method: str = "idw",
    agg_minutes: int = DEFAULT_AGG_MINUTES,
    idw_power: int = 2,
    out_dir: Path | None = None,
) -> None:
    """Side-by-side maps of raw and QC-applied data at peak timestamp."""
    raw_peak_vals = (
        ds_pws_stacked[rain_var]
        .resample(time=f"{agg_minutes}min").sum(skipna=True)
        .sel(time=peak_t, method="nearest").values
    )
    qc_peak_vals = pws_agg.sel(time=peak_t, method="nearest").values

    def _interp(vals):
        if method == "kriging" and PYKRIGE_AVAILABLE:
            g, _ = kriging_interpolate(pws_lons, pws_lats, vals, grid_lon, grid_lat)
            return g
        return idw_interpolate(pws_lons, pws_lats, vals, grid_lon, grid_lat,
                               power=idw_power)

    grid_raw = _interp(raw_peak_vals)
    grid_qc = _interp(qc_peak_vals)
    vmax_cmp = max(_vmax(grid_raw), _vmax(grid_qc))
    method_label = "Ordinary Kriging" if method == "kriging" else f"IDW p={idw_power}"

    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    for ax, grid, vals, label in [
        (axes[0], grid_raw, raw_peak_vals, "Raw (No QC)"),
        (axes[1], grid_qc,  qc_peak_vals,  "QC-Applied (pypwsqc)"),
    ]:
        im = ax.pcolormesh(grid_lon, grid_lat, grid,
                           cmap="Blues", vmin=0, vmax=vmax_cmp, shading="auto")
        plt.colorbar(im, ax=ax, label=f"mm / {agg_minutes} min", shrink=0.8)
        ax.scatter(pws_lons, pws_lats,
                   c=np.nan_to_num(vals), cmap="Blues", vmin=0, vmax=vmax_cmp,
                   s=60, edgecolors="black", linewidths=0.6, zorder=5)
        ax.set_title(f"{label}\n{peak_t.strftime('%Y-%m-%d %H:%M')} UTC")
        ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
        ax.grid(True, alpha=0.3)

    fig.suptitle(f"Effect of QC on {method_label} Rainfall Field  |  {agg_minutes}-min",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    fname = f"fig_pws_{method}_raw_vs_qc.png"
    _save(fig, out_dir, fname)
    flagged = np.sum(~np.isnan(raw_peak_vals) & np.isnan(qc_peak_vals))
    print(f"  Saved: {fname}  (stations flagged by QC: {flagged})")
