# OpenMesh Project - Source Code

This directory contains the source code for the OpenMesh weather data analysis project.

## Structure

```
src/
├── fetch_data/              # Data fetching modules and CLI
│   ├── noaa_asos/           # ASOS 1-minute data fetching (IEM)
│   ├── weather_underground/ # WU personal weather stations (WU / The Weather Company API, own key)
│   ├── OpenMesh/            # OpenMesh dataset download (Zenodo)
│   ├── mrms/                # NOAA MRMS radar products (AWS open data, IEM fallback)
│   ├── noaa_daily/          # NOAA GHCN-Daily station records (NCEI)
│   ├── main.py              # Unified CLI interface
│   └── README.md            # Data sources, setup, and quick start
├── netCDF_converters/       # Scripts that turn raw downloads into the project's netCDF files
│   └── README.md            # Converter table: input, output layout, product
└── analysis/                # End-to-end analysis pipeline
    ├── analysis.ipynb       # Main notebook
    ├── pipeline.py          # Load/fetch pipeline and unified format
    └── README.md            # Pipeline details and usage
```

All fetched and processed data is saved to `../dataset/` at the project root, not in `src/`. Raw data and archives are gitignored; metadata (`meta/`) and example notebooks (`examples/`) are tracked.

## fetch_data/

Scripts and CLI for fetching data from: NOAA ASOS (airport stations via IEM), Weather Underground (personal weather stations, through the WU / The Weather Company API with your own key; follow their terms of use), OpenMesh (pre-collected NYC mesh network data from Zenodo), NOAA MRMS radar, and NOAA GHCN-Daily station records.

Provides both a unified command-line interface (`main.py`) and interactive Jupyter notebooks for each source.

```bash
python src/fetch_data/main.py status     # Show dataset status
python src/fetch_data/main.py asos       # Fetch ASOS data
python src/fetch_data/main.py wu         # Fetch WU data
python src/fetch_data/main.py openmesh   # Download OpenMesh dataset
python src/fetch_data/main.py mrms --start 2024-01-09 --end 2024-01-10   # Fetch MRMS radar
```

For data sources, configuration, API key setup, and full CLI reference, see [`fetch_data/README.md`](fetch_data/README.md) and [`fetch_data/USAGE.md`](fetch_data/USAGE.md).

## netCDF_converters/

Command-line scripts (`python <script>.py --help`) that convert the raw downloads (OpenMesh / NYC Mesh CML data, WU CSVs, ASOS, NY Mesonet, GHCN-Daily) to the project's netCDF layouts (OpenSense CML / PWS). See [`netCDF_converters/README.md`](netCDF_converters/README.md).

## analysis/

End-to-end fetch/load and analysis for all data sources (ASOS, WU, OpenMesh wireless links, PWS).

The main notebook (`analysis.ipynb`) is driven by a single **MODE** setting (`'load'` or `'fetch'`). Fetch mode downloads any missing data (from APIs or Zenodo) then loads it; load mode uses existing files only.

The pipeline unifies all sources into a common format — resampling to shared intervals (e.g. 5-min), standardizing columns, and matching wireless links to nearby PWS stations for cross-dataset comparison.

**Getting started:**
1. Open `analysis/analysis.ipynb`
2. In Section 2 (Configuration): set **MODE**, date range, stations, and **PWS_OPENMESH_SOURCE** (`'sample'` or `'full'`)
3. Run all cells

For pipeline functions, analysis details, and key design patterns, see [`analysis/README.md`](analysis/README.md).

## Requirements

- Python **3.11** or **3.12** (recommended; matches root README)
- pandas, numpy, matplotlib, requests
- Jupyter notebooks for interactive analysis
- Weather Underground only: API key required (see [`fetch_data/README.md`](fetch_data/README.md))