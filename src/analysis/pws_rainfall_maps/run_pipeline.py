"""
run_pipeline.py — End-to-end PWS rainfall mapping pipeline.

Loads PWS data, applies pypwsqc QC, builds IDW and Kriging rainfall maps
for the wettest event in the dataset, and saves all figures + animated GIF.
No popup windows — all output goes to --out-dir.

Usage
-----
    # From the repo root:
    python src/analysis/pws_rainfall_maps/run_pipeline.py

    # Custom paths:
    python src/analysis/pws_rainfall_maps/run_pipeline.py \\
        --pws-nc   dataset/raw/openmesh/pws_opensense_sample_jan.nc \\
        --pws-meta dataset/meta/pws_metadata.csv \\
        --out-dir  output/pws_rainfall_maps \\
        --agg-minutes 15 \\
        --method idw        # or: kriging, both

    # Skip QC or GIF:
    python src/analysis/pws_rainfall_maps/run_pipeline.py --no-qc --no-gif

Requirements
------------
    pip install pykrige pillow   # for Kriging and GIF support
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # must be set before any other matplotlib import

# Ensure this folder is on the path when run directly
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import config as cfg
from idw import make_grid
from kriging import PYKRIGE_AVAILABLE
from pws_loader import load_pws_file, read_pws_groups, stack_pws_to_dataset
from pws_qc import run_pws_qc
from rainfall_maps import (
    find_peak_event,
    plot_accumulated_map,
    plot_event_detection,
    plot_event_panels,
    plot_idw_vs_kriging,
    plot_raw_vs_qc,
    plot_single_map,
    resample_to_windows,
    save_event_gif,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PWS QC + IDW/Kriging rainfall mapping")
    p.add_argument("--pws-nc",   type=Path, default=cfg.PWS_NC_PATH)
    p.add_argument("--pws-meta", type=Path, default=cfg.PWS_META_PATH)
    p.add_argument("--out-dir",  type=Path, default=cfg.OUTPUT_DIR)
    p.add_argument("--agg-minutes", type=int,  default=cfg.AGG_MINUTES,
                   help="Temporal aggregation window in minutes (default: 15)")
    p.add_argument("--event-hours", type=int,  default=cfg.EVENT_HOURS,
                   help="Hours around peak defining event window (default: 2)")
    p.add_argument("--method", choices=["idw", "kriging", "both"], default="both",
                   help="Interpolation method (default: both)")
    p.add_argument("--no-qc",  action="store_true", help="Skip QC, use raw data")
    p.add_argument("--no-gif", action="store_true", help="Skip GIF generation")
    return p.parse_args()


def run(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput directory: {out_dir}\n{'='*60}")

    methods = ["idw", "kriging"] if args.method == "both" else [args.method]
    if "kriging" in methods and not PYKRIGE_AVAILABLE:
        print("WARNING: pykrige not installed — Kriging will be skipped.")
        print("         Install with: pip install pykrige")
        methods = ["idw"]

    #  1. Load 
    print("\n[1/6] Loading PWS data...")
    ds_pws_nc, pws_meta = load_pws_file(args.pws_nc, meta_path=args.pws_meta)
    pws_data             = read_pws_groups(ds_pws_nc)
    ds_pws_stacked       = stack_pws_to_dataset(pws_data, pws_meta, var=cfg.PWS_RAIN_VAR)
    print(f"      Stacked: {dict(ds_pws_stacked.sizes)}")

    #  2. QC 
    if args.no_qc:
        print("\n[2/6] Skipping QC (--no-qc).")
        ds_pws_qc = ds_pws_stacked
    else:
        print("\n[2/6] Applying pypwsqc (FZ + HI + SO)...")
        ds_pws_qc = run_pws_qc(
            ds_pws_stacked, rain_var=cfg.PWS_RAIN_VAR,
            max_dist_km=cfg.QC_MAX_DIST_KM, nint=cfg.QC_NINT,
            hi_thres_a=cfg.QC_HI_THRES_A, hi_thres_b=cfg.QC_HI_THRES_B,
            n_stat=cfg.QC_N_STAT, eval_period=cfg.QC_EVAL_PERIOD,
            mmatch=cfg.QC_MMATCH, gamma=cfg.QC_GAMMA,
        )

    #  3. Grid + resample 
    print("\n[3/6] Building grid and resampling...")
    pws_lons    = ds_pws_qc.lon.values
    pws_lats    = ds_pws_qc.lat.values
    station_ids = ds_pws_qc.id.values
    grid_lon, grid_lat = make_grid(pws_lons, pws_lats,
                                   res=cfg.IDW_GRID_RES_DEG,
                                   pad=cfg.IDW_GRID_PAD_DEG)
    print(f"      Grid shape: {grid_lon.shape}")

    pws_agg = resample_to_windows(ds_pws_qc, rain_var=cfg.PWS_RAIN_VAR,
                                   agg_minutes=args.agg_minutes)

    #  4. Find event 
    print("\n[4/6] Finding peak event...")
    peak_t, event_start, event_end, pws_event = find_peak_event(
        pws_agg, min_stations=cfg.IDW_MIN_STATIONS, event_hours=args.event_hours)
    plot_event_detection(pws_agg, peak_t, event_start, event_end,
                         agg_minutes=args.agg_minutes, out_dir=out_dir)

    #  5. Maps 
    print("\n[5/6] Generating maps...")
    for method in methods:
        print(f"\n  -- {method.upper()} --")
        plot_single_map(pws_agg, peak_t, pws_lons, pws_lats, station_ids,
                        grid_lon, grid_lat, method=method,
                        agg_minutes=args.agg_minutes, idw_power=cfg.IDW_POWER,
                        out_dir=out_dir)
        plot_event_panels(pws_event, peak_t, pws_lons, pws_lats,
                          grid_lon, grid_lat, method=method,
                          agg_minutes=args.agg_minutes, idw_power=cfg.IDW_POWER,
                          out_dir=out_dir)
        plot_accumulated_map(pws_event, event_start, event_end,
                             pws_lons, pws_lats, station_ids,
                             grid_lon, grid_lat, method=method,
                             idw_power=cfg.IDW_POWER, out_dir=out_dir)
        plot_raw_vs_qc(ds_pws_stacked, pws_agg, peak_t, pws_lons, pws_lats,
                       grid_lon, grid_lat, rain_var=cfg.PWS_RAIN_VAR,
                       method=method, agg_minutes=args.agg_minutes,
                       idw_power=cfg.IDW_POWER, out_dir=out_dir)

    # IDW vs Kriging side-by-side comparison
    if len(methods) == 2 or (len(methods) == 1 and "kriging" in methods):
        plot_idw_vs_kriging(pws_agg, peak_t, pws_lons, pws_lats,
                            grid_lon, grid_lat, agg_minutes=args.agg_minutes,
                            idw_power=cfg.IDW_POWER, out_dir=out_dir)

    #  6. GIF 
    if args.no_gif:
        print("\n[6/6] Skipping GIF (--no-gif).")
    else:
        print("\n[6/6] Saving animated GIFs...")
        for method in methods:
            save_event_gif(pws_event, peak_t, pws_lons, pws_lats,
                           grid_lon, grid_lat, method=method,
                           agg_minutes=args.agg_minutes, idw_power=cfg.IDW_POWER,
                           fps=cfg.GIF_FPS, dpi=cfg.GIF_DPI, out_dir=out_dir)

    ds_pws_nc.close()
    print(f"\n{'='*60}\nDone. All outputs saved to: {out_dir}")


if __name__ == "__main__":
    run(parse_args())