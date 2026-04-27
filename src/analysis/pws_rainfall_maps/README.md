# PWS Rainfall Mapping

Quality control and spatial interpolation (IDW + Ordinary Kriging) for
Personal Weather Station (PWS) rainfall data from the OpenMesh dataset.

## What this does

1. **Loads** the PWS NetCDF file (group-per-station format via netCDF4)
2. **Applies QC** using the OpenSense `pypwsqc` package (FZ, HI, SO filters)
3. **Creates rainfall maps** at configurable time resolution (default 15 min) using:
   - **IDW** (Inverse Distance Weighting) - fast, deterministic
   - **Ordinary Kriging** (via `pykrige`) - geostatistical, produces uncertainty field
4. **Outputs** for the wettest detected event:
   - Single-timestamp map at peak window
   - Multi-panel map across full event
   - Animated GIF of the evolving rainfall field
   - Accumulated event total map
   - Raw vs QC comparison map
   - IDW vs Kriging side-by-side comparison (with Kriging uncertainty panel)

All figures save automatically to `--out-dir` - no popup windows.

## File structure

```
pws_rainfall_maps/
├── config.py          # All parameters (paths, QC, IDW, Kriging settings)
├── pws_loader.py      # Load PWS NetCDF groups -> stacked xr.Dataset
├── pws_qc.py          # pypwsqc FZ + HI + SO filters
├── idw.py             # IDW interpolation
├── kriging.py         # Ordinary Kriging via pykrige (mergeplg approach)
├── rainfall_maps.py   # All map/GIF generation functions
├── run_pipeline.py    # End-to-end CLI script
└── README.md
```

## Requirements

```bash
pip install -r requirements.txt   # from repo root
pip install pykrige pillow        # for Kriging and GIF support
```

Key dependencies: `numpy`, `pandas`, `xarray`, `netCDF4`, `scipy`,
`matplotlib`, `pypwsqc`, `pyproj`, `pykrige`, `pillow`

## Data required

The pipeline expects these files (downloaded automatically by the fetch pipeline):

| File | Default location |
|------|-----------------|
| `pws_opensense_sample_jan.nc` | `dataset/raw/openmesh/` |
| `pws_metadata.csv` | `dataset/meta/` |

Download with:
```bash
python src/fetch_data/main.py openmesh
```

## How to run

### From the repo root (recommended)

```bash
python src/analysis/pws_rainfall_maps/run_pipeline.py
```

| Flag | Default | Description |
|------|---------|-------------|
| `--pws-nc` | `dataset/raw/openmesh/pws_opensense_sample_jan.nc` | PWS NetCDF |
| `--pws-meta` | `dataset/meta/pws_metadata.csv` | Station metadata |
| `--out-dir` | `output/pws_rainfall_maps` | Output directory |
| `--agg-minutes` | `15` | Temporal window (minutes) |
| `--event-hours` | `2` | Event window around peak (hours each side) |
| `--method` | `both` | `idw`, `kriging`, or `both` |
| `--no-qc` | off | Skip QC, use raw data |
| `--no-gif` | off | Skip GIF (faster run) |

## Output files

Saved to `output/pws_rainfall_maps/`:

| File | Description |
|------|-------------|
| `fig_pws_event_detection.png` | Network-total time series, peak marked |
| `fig_pws_idw_peak.png` | IDW map at peak 15-min window |
| `fig_pws_kriging_peak.png` | Kriging map at peak window |
| `fig_pws_idw_vs_kriging.png` | Side-by-side comparison + uncertainty |
| `fig_pws_idw_event_panels.png` | Multi-panel IDW map across event |
| `fig_pws_kriging_event_panels.png` | Multi-panel Kriging map |
| `fig_pws_idw_event.gif` | Animated IDW rainfall field |
| `fig_pws_kriging_event.gif` | Animated Kriging rainfall field |
| `fig_pws_idw_accum.png` | IDW accumulated event rainfall |
| `fig_pws_kriging_accum.png` | Kriging accumulated event rainfall |
| `fig_pws_idw_raw_vs_qc.png` | Effect of QC on IDW field |
| `fig_pws_kriging_raw_vs_qc.png` | Effect of QC on Kriging field |

## Interpolation methods

### IDW (Inverse Distance Weighting)
Standard deterministic method. Weights each station by `1/d^p` where `d` is
distance and `p=2` (default). Fast, simple, no assumptions about spatial
structure. Same approach as in the OpenSense IDW implementations.

### Ordinary Kriging
Geostatistical method using `pykrige` - the same library referenced in
[mergeplg](https://github.com/OpenSenseAction/mergeplg), the OpenSense merging
package. Fits a variogram model (default: spherical) to the observed spatial
correlation, then uses it for optimal interpolation. Also produces a
**variance field** showing uncertainty - highest where stations are sparse.

## Changing parameters

Edit `config.py`. Key parameters:

```python
AGG_MINUTES             = 15        # temporal resolution
IDW_POWER               = 2         # IDW exponent
KRIGING_VARIOGRAM_MODEL = "spherical"  # or gaussian, exponential, linear
QC_MAX_DIST_KM          = 10.0      # QC neighbour radius
```

## PWS format note

The PWS file uses **netCDF4 group-per-station** format. `xr.open_dataset()`
returns an empty dataset for this file - `pws_loader.py` handles it correctly.
Station coordinates come from `pws_metadata.csv` (not stored in the NetCDF).

## References

- pypwsqc (OpenSense QC): https://github.com/OpenSenseAction/pypwsqc
- mergeplg (OpenSense merging + Kriging): https://github.com/OpenSenseAction/mergeplg
- pykrige: https://github.com/GeoStat-Framework/PyKrige
- OpenMesh dataset: https://doi.org/10.5281/zenodo.15287692
