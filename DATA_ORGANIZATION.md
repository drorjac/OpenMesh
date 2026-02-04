# Data Organization

## Standard Data Location

**All downloaded and processed data are stored under the project root in:**
```
dataset/
```

This is the **standard location** used by `src/fetch_data/config.py` and `src/analysis/pipeline.py`.

## Directory Structure

```
OpenMesh-fresh/
├── dataset/                         # All data (gitignore large files)
│   ├── meta/                        # Metadata (CSVs, maps)
│   │   ├── ASOS_stations.csv
│   │   ├── pws_metadata.csv
│   │   ├── links_metadata.csv
│   │   └── maps/                    # HTML maps
│   ├── raw/                         # Raw data
│   │   ├── openmesh/                # NetCDF: ds_openmesh.nc, pws_*.nc
│   │   └── fetched/                 # API-fetched
│   │       ├── asos/                 # ASOS_standard_*.csv, etc.
│   │       └── wu/                  # WU_*.csv
│   ├── archived/
│   │   └── openmesh/                # OpenMesh.zip, PWS_NYC_WU.zip
│   └── examples/                    # Example notebooks (from OpenMesh)
│
└── src/
    ├── fetch_data/                  # Download/fetch; writes to dataset/
    │   └── config.py                # PROJECT_ROOT, OUTPUT_DIRS, DATASET_DIR
    └── analysis/                    # Load from dataset/ via get_default_paths()
```

## Usage in Code

**Paths are centralized** — do not hardcode `dataset/` paths in notebooks.

### From `src/analysis/` (pipeline, notebooks):
```python
from analysis.pipeline import get_default_paths
paths = get_default_paths()
# paths['openmesh_raw'], paths['openmesh_meta'], paths['asos'], paths['wu'], paths['meta']
```

### From `src/fetch_data/`:
```python
from config import PROJECT_ROOT, OUTPUT_DIRS, DATASET_DIR
# OUTPUT_DIRS['asos'], OUTPUT_DIRS['wu'], OUTPUT_DIRS['openmesh_raw'], etc.
```

## Key Points

1. **`dataset/`** — Single standard location for all data (meta, raw, archived, examples).
2. **Config** — Use `src/fetch_data/config.py` (OUTPUT_DIRS) or `src/analysis/pipeline.get_default_paths()` so paths stay consistent.
3. **Fetch vs load** — Fetch pipelines write to `dataset/raw/` and `dataset/archived/`; analysis loads from `dataset/` via the same paths.
4. **OpenMesh** — CML: `dataset/raw/openmesh/ds_openmesh.nc`. PWS: `pws_opensense_sample_jan.nc` (sample) or `pws_wu_os.nc` (full). Archives: `dataset/archived/openmesh/`.

## Functions

- **Paths:** `src/fetch_data/config.py` (OUTPUT_DIRS, DATASET_DIR), `src/analysis/pipeline.get_default_paths()`
- **Fetch:** `src/fetch_data/main.py` (CLI), `openmesh.run_openmesh_pipeline()`, `openmesh.run_pws_wu_pipeline()`
- **Load:** `src/analysis/pipeline.load_or_fetch_openmesh()`, `load_openmesh_cml()`, `load_pws_from_netcdf()`

All notebooks should use these functions rather than reimplementing paths or download logic.
