"""
config.py — Configuration for PWS rainfall mapping pipeline.

Paths are resolved by searching upward for the 'OpenMesh' repo root
(identified by the presence of requirements.txt), rather than counting
parent directories which breaks across environments.
"""
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    """Walk upward from start until we find the repo root (has requirements.txt)."""
    p = start.resolve()
    for _ in range(10):
        if (p / "requirements.txt").exists() and (p / "src").exists():
            return p
        p = p.parent
    # Fallback: 3 levels up from this file (pws_rainfall_maps -> analysis -> src -> OpenMesh)
    return start.resolve().parents[2]


_HERE      = Path(__file__).resolve().parent   # .../src/analysis/pws_rainfall_maps
_REPO_ROOT = _find_repo_root(_HERE)
DATASET_DIR = _REPO_ROOT / "dataset"

# Default file locations
PWS_NC_PATH   = DATASET_DIR / "raw" / "openmesh" / "pws_opensense_sample_jan.nc"
PWS_META_PATH = DATASET_DIR / "meta" / "pws_metadata.csv"
OUTPUT_DIR    = _REPO_ROOT / "output" / "pws_rainfall_maps"

PWS_RAIN_VAR = "rainfall_amount"

# QC parameters (pypwsqc)
QC_MAX_DIST_KM = 10.0
QC_NINT        = 10
QC_HI_THRES_A  = 10.0
QC_HI_THRES_B  = 20.0
QC_N_STAT      = 1
QC_EVAL_PERIOD = 24
QC_MMATCH      = 0.5
QC_GAMMA       = 0.5

# IDW parameters
IDW_POWER        = 2
IDW_GRID_RES_DEG = 0.005
IDW_GRID_PAD_DEG = 0.05
IDW_MIN_STATIONS = 3

# Kriging parameters
KRIGING_VARIOGRAM_MODEL = "spherical"
KRIGING_MIN_STATIONS    = 5

# Map / event parameters
AGG_MINUTES = 15   # temporal aggregation window (minutes)
EVENT_HOURS = 2    # hours before/after peak defining event window
GIF_FPS     = 2
GIF_DPI     = 120


if __name__ == "__main__":
    print(f"Repo root     : {_REPO_ROOT}")
    print(f"PWS NC path   : {PWS_NC_PATH}  (exists: {PWS_NC_PATH.exists()})")
    print(f"PWS meta path : {PWS_META_PATH}  (exists: {PWS_META_PATH.exists()})")
    print(f"Output dir    : {OUTPUT_DIR}")