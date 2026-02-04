# Data Organization

This folder (`dataset/`) is the **single standard location** for all project data. Paths are defined in `src/fetch_data/config.py` and `src/analysis/pipeline.py` — use those in code instead of hardcoding paths.

---

## Where each dataset lives and where it came from

### `meta/`

**What:** Station and link metadata (CSVs and maps).  
**Source:** Filled by the OpenMesh extract pipeline, or can be placed here manually.

| File / folder | Description | Origin |
|---------------|-------------|--------|
| `ASOS_stations.csv` | NOAA ASOS station list (e.g. JFK, LGA, NYC) | OpenMesh Zenodo extract or manual |
| `pws_metadata.csv` | Weather Underground PWS station list (NYC area) | OpenMesh Zenodo extract or manual |
| `links_metadata.csv` | OpenMesh CML link coordinates and properties | OpenMesh Zenodo extract |
| `maps/` | `directional_map.html`, `frequency_map.html` | OpenMesh Zenodo extract |

---

### `raw/openmesh/`

**What:** OpenMesh NetCDF files (CML and PWS).  
**Source:** Zenodo downloads, extracted by the OpenMesh pipeline.

| File | Description | Origin |
|------|-------------|--------|
| `ds_openmesh.nc` | Microwave link (CML) RSL time series | **Zenodo 15287692** → `OpenMesh.zip` → extract (e.g. `main.py openmesh`) |
| `pws_opensense_sample_jan.nc` | PWS sample (January only) | **Zenodo 15287692** → same `OpenMesh.zip` |
| `pws_wu_os.nc` | PWS full time series (~8 months) | **Zenodo 17508286** → `PWS_NYC_WU.zip` → extract (OpenMesh PWS WU pipeline) |

---

### `raw/fetched/asos/`

**What:** NOAA ASOS station data (CSV).  
**Source:** Fetched via IEM API.

| Pattern | Description | Origin |
|---------|-------------|--------|
| `ASOS_standard_*.csv` | Standardized 1‑min (or resampled) ASOS | **IEM ASOS API** → `main.py asos` or `asos_pipeline.ipynb` |
| `ASOS_5min_*.csv`, `ASOS_1H_*.csv` | Resampled versions | Same fetch, resampled by pipeline |
| `api_response/ASOS_raw_*.csv` | Raw API response (optional) | Same API, saved with `--type raw` |

---

### `raw/fetched/wu/`

**What:** Weather Underground PWS data (CSV).  
**Source:** Fetched via Weather Underground API (hourly historical).

| Pattern | Description | Origin |
|---------|-------------|--------|
| `WU_*.csv` | Hourly PWS data for requested stations/dates | **WU API** → `main.py wu` or `wu_pipeline.ipynb` (requires `WU_API_KEY`) |
| `api_response/` | Raw API responses (optional) | Same API |

---

### `archived/openmesh/`

**What:** Downloaded ZIPs before extraction.  
**Source:** Zenodo.

| File | Description | Origin |
|------|-------------|--------|
| `OpenMesh.zip` | Main OpenMesh archive (CML + PWS sample + metadata) | **Zenodo 15287692** → `main.py openmesh` or notebook |
| `PWS_NYC_WU.zip` | Full PWS dataset | **Zenodo 17508286** → OpenMesh PWS WU pipeline |

---

### `examples/`

**What:** Example notebooks for exploring OpenMesh data.  
**Source:** Extracted from OpenMesh Zenodo archive (e.g. `openmesh_dataset_example.ipynb`, `read_pws_sample.ipynb`).

---

## Directory structure (overview)

```
dataset/
├── meta/                  # Metadata CSVs and maps (see table above)
├── raw/
│   ├── openmesh/          # NetCDF: ds_openmesh.nc, pws_*.nc (Zenodo)
│   └── fetched/
│       ├── asos/          # ASOS CSVs (IEM API)
│       └── wu/            # WU CSVs (WU API)
├── archived/openmesh/     # OpenMesh.zip, PWS_NYC_WU.zip (Zenodo)
└── examples/              # Example notebooks (from OpenMesh extract)
```

---

## Usage in code

**Do not hardcode `dataset/` paths.** Use centralized config:

**From `src/analysis/` (pipeline, notebooks):**
```python
from analysis.pipeline import get_default_paths
paths = get_default_paths()
# paths['openmesh_raw'], paths['asos'], paths['wu'], paths['meta'], etc.
```

**From `src/fetch_data/`:**
```python
from config import OUTPUT_DIRS, DATASET_DIR
# OUTPUT_DIRS['asos'], OUTPUT_DIRS['wu'], OUTPUT_DIRS['openmesh_raw'], etc.
```

---

## How to fetch or load

| Goal | CLI | Notebook / code |
|------|-----|------------------|
| OpenMesh (CML + PWS sample) | `python src/fetch_data/main.py openmesh` | `OpenMesh/download_and_read_openmesh.ipynb` or `openmesh.run_openmesh_pipeline()` |
| PWS full (~8 months) | Same + PWS WU pipeline | `openmesh.run_pws_wu_pipeline()` |
| ASOS | `main.py asos -s JFK LGA --start ... --end ...` | `noaa_asos/asos_pipeline.ipynb` |
| WU (hourly) | `main.py wu -s ... --start ... --end ...` | `weather_underground/wu_pipeline.ipynb` |
| Load/fetch all + analyze | — | `analysis/analysis.ipynb` (set MODE and run) |

All notebooks should use the functions above instead of reimplementing paths or download logic.
