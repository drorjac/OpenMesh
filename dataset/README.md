# Dataset Directory

This directory is the **single standard location** for all project data. Paths are defined in `src/fetch_data/config.py` and `src/analysis/pipeline.py` — use those in code instead of hardcoding paths.

**Note:** `raw/` and `archived/` are gitignored. Metadata (`meta/`) and example notebooks (`examples/`) are tracked.

## Choosing the dataset: v1 (default) or v2

The code reads one of two public OpenMesh datasets, picked in one place,
`src/analysis/datasets.py`. Run the snippets from `src/`, or set `PYTHONPATH=src`.

| | **v1** (default): the ESSD record | **v2**: OpenMesh 2.0.0 |
|---|---|---|
| Zenodo | [15287692](https://doi.org/10.5281/zenodo.15287692) (CML, CC BY 4.0) + [17508286](https://doi.org/10.5281/zenodo.17508286) (WU PWS, CC BY-NC 4.0) | [23283445](https://doi.org/10.5281/zenodo.23283445), CC BY 4.0 |
| links | `raw/openmesh/ds_openmesh.nc`: 75 CMLs / 103 sublinks, 1 min, 2023-10-29 → 2024-07-01 | `data/links/openmesh_links.nc`: 359 CMLs / 732 sublinks, 2023-10-29 → 2026-05-31 (1 min to 2025-04-21, then hourly / 6 min polls in `rsl_avg`, `rsl_max`) |
| weather | WU PWS `raw/openmesh/pws_wu_os.nc` (37 stations, used if present); ASOS 1-min data of one window, fetched from the IEM API with `D.fetch_v1_asos(start, end)` (5 stations, written to `raw/openmesh/derived/`); no Mesonet, no GHCN daily | ASOS (5 stations, quality flag), GHCN daily (7 stations), 10 MRMS days; no PWS, no Mesonet |
| get it | `python src/fetch_data/main.py openmesh`, `openmesh.run_pws_wu_pipeline()`, or automatically in `tutorials/radar.ipynb` | download `openmesh-2.0.0.zip` from the record, then `D.install_v2(path)` once |
| folder | `dataset/raw/openmesh/` (or `OPENMESH_V1_DIR`) | `dataset/raw/openmesh_v2/` (or `OPENMESH_V2_DIR`) |

```python
from analysis import datasets as D
D.install_v2('~/Downloads/openmesh-2.0.0.zip')   # once: unpacks into dataset/raw/openmesh_v2/
D.use('v2')                                      # every loader now reads v2 (or: OPENMESH_DATASET=v2)
D.describe()                                     # its files, and which are on disk
ds = D.open_cml()                                # the CML file, same shape for both datasets
level = D.signal_level(ds.sel(cml_id='6', sublink_id='sublink_1', time='2025-09'))
```

- Without `D.use` or `OPENMESH_DATASET` the code reads v1. Notebooks that support both have a
  `DATASET` knob in their setup cell (`'v1'` by default); scripts take `--dataset v1|v2`.
- `open_cml` gives both files one shape (`polarization`, str ids, frequency MHz, length m);
  `signal_level` merges v2's `rsl` and `rsl_avg` into one level. `load_ghcn` returns GHCN as
  one table layout, and `load_weather_networks` reads v2's flat ASOS file (flagged minutes set to NaN).
- **cml_ids are not shared**: v1 `'6'` and v2 `'6'` are different paths.
- CML attenuation baselines are built with
  `python src/analysis/cml_baseline.py --dataset v1|v2 [--freq 10min]` and go to the dataset's
  `derived/` folder (`raw/openmesh/derived/`, `raw/openmesh_v2/derived/`). For v1 the default
  window is the days of the fetched ASOS file.

## Directory Structure

```
dataset/
├── meta/                      # Station/link metadata and maps
│   ├── ASOS_stations.csv
│   ├── pws_metadata.csv
│   ├── links_metadata.csv
│   └── maps/                  # directional_map.html, frequency_map.html
├── raw/
│   ├── openmesh/              # v1: NetCDF files from Zenodo (+ derived/)
│   ├── openmesh_v2/           # v2: the unpacked Zenodo 2.0.0 record (+ derived/)
│   └── fetched/
│       ├── asos/              # NOAA ASOS CSVs (IEM API)
│       │   └── api_response/  # Optional raw API CSVs
│       └── wu/                # Weather Underground CSVs (WU API)
│           └── api_response/
├── archived/openmesh/         # Downloaded ZIPs from Zenodo
│   └── extracted/             # README.txt + other (organize=True) or full ZIP (organize=False)
├── examples/                  # Example notebooks (read and plot the data)
└── formats/                   # netCDF format docs
```

## Contents and Origins

### meta/

Station and link metadata. Filled by the OpenMesh extract pipeline or placed manually.

| File / folder | Description | Origin |
|---------------|-------------|--------|
| `ASOS_stations.csv` | NOAA ASOS station list (13 stations in NY, NJ and CT) | OpenMesh Zenodo extract or manual |
| `pws_metadata.csv` | Weather Underground PWS stations (NYC area) | OpenMesh Zenodo extract or manual |
| `links_metadata.csv` | Wireless link coordinates and properties | OpenMesh Zenodo extract |
| `maps/` | `directional_map.html`, `frequency_map.html` | OpenMesh Zenodo extract |

### raw/openmesh/

OpenMesh NetCDF files (wireless links and PWS) from Zenodo.

| File | Description | Origin |
|------|-------------|--------|
| `ds_openmesh.nc` | Wireless link RSL time series | [Zenodo 15287692](https://zenodo.org/records/15287692) → `OpenMesh.zip` → extract |
| `pws_opensense_sample_jan.nc` | WU PWS sample, 37 stations, 2024-01-15 → 2024-01-30 | Same `OpenMesh.zip` |
| `pws_wu_os.nc` | WU PWS, 37 stations, 2023-10-29 → 2024-07-01 (CC BY-NC 4.0) | [Zenodo 17508286](https://zenodo.org/records/17508286) → `PWS_NYC_WU.zip` → extract |

### raw/fetched/asos/

NOAA ASOS station data (CSV), fetched via IEM API.

| Pattern | Description | Origin |
|---------|-------------|--------|
| `ASOS_standard_*.csv` | Standardized 1‑min (or resampled) | `main.py asos` or `asos_pipeline.ipynb` |
| `ASOS_5min_*.csv`, `ASOS_1H_*.csv` | Resampled versions | Same fetch, resampled by pipeline |
| `api_response/ASOS_raw_*.csv` | Raw API response (optional) | Same API, saved with `--type raw` |

### raw/fetched/wu/

Weather Underground PWS data (CSV), fetched via WU API (hourly historical). Requires `WU_API_KEY`.

| Pattern | Description | Origin |
|---------|-------------|--------|
| `WU_*.csv` | Hourly PWS data for requested stations/dates | `main.py wu` or `wu_pipeline.ipynb` |
| `api_response/` | Raw API responses (optional) | Same API |

### archived/openmesh/

Downloaded ZIPs and extracted archive contents from Zenodo. ZIPs can be kept for backup or deleted to save space.

| File / folder | Description | Origin |
|---------------|-------------|--------|
| `OpenMesh.zip` | Main archive (~13 MB): links + PWS sample + metadata | [Zenodo 15287692](https://zenodo.org/records/15287692) |
| `PWS_NYC_WU.zip` | Full PWS dataset | [Zenodo 17508286](https://zenodo.org/records/17508286) |
| `extracted/` | `organize=True`: README.txt and unclassified files; `organize=False`: full ZIP contents | Extract pipeline |

### examples/

Example notebooks that read and plot the data. Versions of these are in the OpenMesh Zenodo archive; the copies here use repository paths:

- `openmesh_dataset_example.ipynb` — Wireless links visualization and exploration
- `read_pws_sample.ipynb` — Reading PWS sample data from NetCDF

To get the required data: `python src/fetch_data/main.py openmesh`

## Data Format Standards

All fetched data (ASOS and WU) uses standardized column names for cross-dataset compatibility:

| Column | Description | Unit |
|--------|-------------|------|
| `datetime` | UTC timestamp | — |
| `station_id` | Station identifier | — |
| `temperature` | Air temperature | °C |
| `dewpoint` | Dew point temperature | °C |
| `wind_speed` | Wind speed | m/s |
| `wind_direction` | Wind direction | degrees (0–360) |
| `wind_gust` | Wind gust speed | m/s |
| `precip_amount` | Precipitation amount | mm |
| `humidity` | Relative humidity | % |
| `pressure` | Atmospheric pressure | hPa |

See `src/fetch_data/config.py` for complete column definitions.

## File Naming Conventions

| Source | Pattern | Example |
|--------|---------|---------|
| ASOS (processed) | `ASOS_{resolution}_{start}_{end}.csv` | `ASOS_5min_2024-01-01_2024-01-29.csv` |
| ASOS (raw) | `ASOS_raw_{start}_{end}.csv` | — |
| WU (processed) | `WU_{start}_{end}.csv` | `WU_2024-01-01_2024-01-30.csv` |
| OpenMesh | Fixed names | `ds_openmesh.nc`, `pws_wu_os.nc` |

## How to Fetch or Load

| Goal | CLI | Notebook / code |
|------|-----|-----------------|
| OpenMesh (links + PWS sample) | `python src/fetch_data/main.py openmesh` | `OpenMesh/download_and_read_openmesh.ipynb` |
| WU PWS of v1 (Zenodo 17508286) | Same + PWS WU pipeline | `openmesh.run_pws_wu_pipeline()` |
| ASOS | `main.py asos -s JFK LGA --start ... --end ...` | `noaa_asos/asos_pipeline.ipynb` |
| WU (hourly) | `main.py wu -s ... --start ... --end ...` | `weather_underground/wu_pipeline.ipynb` |
| Load/fetch all + analyze | — | `analysis/analysis.ipynb` (set MODE and run) |

See `src/fetch_data/README.md` for full CLI reference and data source details.

## Usage in Code

**Do not hardcode `dataset/` paths.** Use centralized config:

From `src/analysis/`:
```python
from analysis.pipeline import get_default_paths
paths = get_default_paths()
# paths['openmesh_raw'], paths['asos'], paths['wu'], paths['meta'], etc.
```

From `src/fetch_data/`:
```python
from config import OUTPUT_DIRS, DATASET_DIR
# OUTPUT_DIRS['asos'], OUTPUT_DIRS['wu'], OUTPUT_DIRS['openmesh_raw'], etc.
```

## Dataset Organization (Download Flow)

When you download the OpenMesh dataset, files are automatically organized:

1. Downloads `OpenMesh.zip` from Zenodo → `dataset/archived/openmesh/`
2. Extracts and organizes:
   - Raw data (`*.nc`) → `dataset/raw/openmesh/`
   - Metadata (`*.csv`) → `dataset/meta/`
   - Notebooks (`*.ipynb`) → `dataset/examples/`
   - Maps (`*.html`) → `dataset/meta/maps/`
   - Docs and unclassified → `dataset/archived/openmesh/extracted/`