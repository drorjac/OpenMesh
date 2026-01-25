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
└── analysis/            # Analysis notebooks and scripts
    ├── pipeline.py      # Data loading and processing pipeline
    ├── plotting.py      # Visualization functions
    └── *.ipynb          # Analysis notebooks
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

Analysis notebooks and scripts for exploring and analyzing weather data from all sources.

**Key Files:**
- `pipeline.py` - Data loading pipeline with functions:
  - `load_all_datasets()` - Load ASOS, WU, and OpenMesh data
  - `fetch_asos_data()`, `fetch_wu_data()` - Fetch new data from APIs
  - `load_asos_from_files()`, `load_wu_from_files()` - Load from saved CSVs
  - `convert_to_unified_format()` - Resample and standardize all datasets
  - `get_default_paths()` - Get standard data directory paths
- `plotting.py` - Visualization utilities
- `analysis.ipynb` - Main end-to-end analysis notebook (loads all data sources, converts to unified format, visualizations)
- `load_and_analyze_datasets.ipynb` - Dataset loading and exploration notebook

**Key Functions:**
- Data loading uses same functions as `asos_pipeline.ipynb` (`load_all_data()`, `select_longest_dataset()` from `asos_fetch.py`) for consistency
- Unified format conversion resamples all datasets to common intervals (default 5-min)
- Supports fetching new data or loading from existing files 

## Data Output Location

All data is saved to `../dataset/` at the project root:
```
dataset/
├── raw/
│   ├── fetched/
│   │   ├── asos/              # ASOS data (CSV)
│   │   └── wu/                # Weather Underground data (CSV)
│   └── openmesh/              # OpenMesh dataset (NetCDF)
├── meta/                       # Station metadata (CSV)
└── archived/                   # Downloaded ZIP files
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

1. Open notebooks in `analysis/` directory
2. Configure date ranges and stations in notebook cells
3. Run cells to load, process, and visualize data

Example workflow:
- Load ASOS data using `load_all_data()` from `asos_fetch.py`
- Select longest dataset with `select_longest_dataset()`
- Convert to unified format with `convert_to_unified_format()`
- Visualize and analyze

## Key Design Patterns

**Modular Functions:** Core functionality is in Python modules (`.py` files), notebooks call these functions
**Consistent APIs:** Same functions used across notebooks (e.g., `load_all_data()`, `select_longest_dataset()`)
**Unified Format:** All datasets can be converted to common structure for cross-dataset analysis
**Flexible Loading:** Support for fetching from APIs or loading from saved files

## Requirements

- Python 3.8+
- See `fetch_data/README.md` for specific dependencies
- Jupyter notebooks for interactive analysis