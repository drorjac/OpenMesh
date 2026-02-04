# OpenMesh Project - Source Code

This directory contains all source code for the OpenMesh weather data analysis project.

## Structure
```
src/
├── fetch_data/          # Data fetching modules and CLI
│   ├── main.py          # Unified CLI interface
│   ├── config.py        # Shared configuration and paths
│   ├── noaa_asos/       # ASOS data fetching
│   ├── weather_underground/  # WU data fetching
│   └── OpenMesh/        # OpenMesh dataset download
└── analysis/            # End-to-end fetch/load + basic analysis
    ├── pipeline.py      # Load/fetch pipeline and unified format
    ├── plotting.py      # Visualization functions
    ├── analysis_functions.py
    ├── analysis.ipynb   # Main notebook: fetch or load all data, analyze
    └── README.md
```

Data storage: All fetched and processed data is saved to `../dataset/` at the project root, not in `src/`.

## Directories

### fetch_data/

Scripts and CLI for fetching weather data from various sources. Provides a unified command-line interface and modular functions for each data source.

**Key Files:**
- `main.py` - Unified CLI interface for all data sources
- `config.py` - Shared configuration, output paths, and utility functions
- `USAGE.md` - Detailed CLI command reference

**Subdirectories:**

**noaa_asos/**
- `asos_fetch.py` - Core functions: `fetch_all_stations_1min()`, `process_all_stations()`, `save_asos()`, `load_all_data()`, `select_longest_dataset()`
- `asos_pipeline.ipynb` - Interactive pipeline notebook for fetching, processing, and visualizing ASOS data
- `config.py` - ASOS-specific column mappings and constants

**weather_underground/**
- `wu_fetch.py` - Core functions: `run_wu_pipeline()`, `get_station_list()`, `read_pws_metadata()`
- `wu_pipeline.ipynb` - Interactive pipeline notebook for WU data
- `config.py` - WU-specific column mappings and constants

**OpenMesh/**
- `openmesh.py` - Download and extraction functions for NetCDF datasets
- `download_and_read_openmesh.ipynb` - Download and load notebook

**Quick Start:**
```bash
cd fetch_data
python main.py status
python main.py asos -s JFK --start 2024-01-01 --end 2024-01-31
python main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-31
```

See `fetch_data/README.md` and `fetch_data/USAGE.md` for detailed usage.

### analysis/

End-to-end fetch/load and basic analysis for all data sources (ASOS, WU, OpenMesh CML, PWS). One notebook drives everything via **MODE** (`'load'` or `'fetch'`).

**Key Files:**
- `pipeline.py` - Load/fetch and unified format:
  - `get_default_paths()`, `load_metadata()` - Paths and metadata
  - `load_or_fetch_data(mode, ...)` - Load or fetch ASOS & WU (same MODE as notebook)
  - `load_or_fetch_openmesh(paths, mode, pws_source)` - Load or fetch CML & PWS; fetches from Zenodo if missing when `mode='fetch'`
  - `load_openmesh_cml()`, `load_pws_from_netcdf()` - Direct loaders (used by pipeline)
  - `prepare_analysis_data()` - Unified format, resampling, CML–PWS matching
- `plotting.py` - Visualization utilities
- `analysis_functions.py` - Rain detection, link filtering, etc.
- `analysis.ipynb` - **Main notebook:** set MODE and PWS source in config; run all cells to fetch (if needed), load, unify, and run basic analysis (plots, CML–PWS panels)

**Key behavior:**
- **MODE** controls load vs fetch for both Section 4 (ASOS/WU) and Section 5 (OpenMesh/PWS). Fetch mode downloads missing data (APIs or Zenodo) then loads.
- Unified format conversion resamples to common intervals (e.g. 5-min). Uses fetch_data modules under the hood for consistency. 

## Data Output Location

All data is saved to `../dataset/` at the project root:
```
dataset/
├── raw/
│   ├── fetched/
│   │   ├── asos/              # ASOS data (CSV)
│   │   └── wu/                # Weather Underground data (CSV)
│   └── openmesh/              # OpenMesh NetCDF (ds_openmesh.nc, pws_*.nc)
├── meta/                      # Station metadata (CSVs, maps/)
├── archived/openmesh/         # OpenMesh.zip, PWS_NYC_WU.zip
└── examples/                  # Example notebooks (from OpenMesh extract)
```

Note: The `dataset/` folder is gitignored and not tracked in version control.

## Getting Started

### Fetching Data

1. Navigate to `fetch_data/` directory
2. Use `main.py` CLI or individual pipeline notebooks
3. Data automatically saves to `../dataset/`

Example:
```bash
cd fetch_data
python main.py asos -s JFK LGA --start 2024-01-01 --end 2024-01-31 --type standard
```

### Analysis

1. Open `analysis/analysis.ipynb`
2. In Section 2 (Configuration): set **MODE** (`'load'` or `'fetch'`), date range, stations, and **PWS_OPENMESH_SOURCE** (`'sample'` or `'full'`)
3. Run all cells: data is loaded or fetched as needed, then unified and visualized

Example: `MODE='fetch'` fetches missing ASOS/WU/OpenMesh data; `MODE='load'` uses existing files only (prompts to use fetch if files are missing).

## Key Design Patterns

**Modular functions:** Core logic is in `.py` modules; notebooks call them (e.g. `pipeline.load_or_fetch_data`, `openmesh.load_pws`).
**Single MODE:** One setting (load vs fetch) in `analysis.ipynb` drives ASOS, WU, and OpenMesh; fetch mode downloads missing data then loads.
**Unified format:** `prepare_analysis_data()` resamples and standardizes all sources for cross-dataset analysis.
**Paths:** Use `get_default_paths()` or `fetch_data.config.OUTPUT_DIRS` so all code points at `dataset/`.

## Requirements

- Python 3.8+
- See `fetch_data/README.md` for specific dependencies
- Jupyter notebooks for interactive analysis