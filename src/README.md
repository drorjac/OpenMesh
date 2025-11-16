# OpenMesh Project - Source Code

This directory contains all source code for the OpenMesh weather data analysis project.

## 📁 Structure
```
src/
├── fetch_data/          # Data fetching modules
├── data/                # Fetched and processed datasets
└── analysis/            # Analysis notebooks (coming soon)
```

## 🗂️ Directories

### `fetch_data/`
Scripts and notebooks for fetching weather data from various sources:
- **NOAA ASOS** - Airport weather stations via IEM API
- **Weather Underground** - Personal weather stations via WU API  
- **OpenMesh** - Pre-collected dataset from Zenodo

See `fetch_data/README.md` for details.

### `data/`
All fetched and processed data outputs:
- `noaa_asos/` - ASOS weather data (CSV format)
- `wu_pws/` - Weather Underground data (CSV/JSON format)
- `openmesh/` - OpenMesh dataset (NetCDF format)

**Note:** This folder is gitignored and not tracked in version control.

### `analysis/`
Analysis notebooks and scripts (coming soon).

## 🚀 Quick Start

1. Navigate to `fetch_data/` to download weather data
2. Outputs automatically save to `data/`
3. Use notebooks in `analysis/` for data exploration

## 📋 Requirements

- Python 3.8+
- See individual module READMEs for specific dependencies

---

Part of the OpenMesh project.
