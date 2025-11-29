# OpenMesh Data Fetching Branch

**Branch:** `openmesh-fetch`  
**Purpose:** Extend repository APIs and develop data fetching capabilities for multiple datasets

**Note:** This branch maintains a similar structure to the `main` branch, with a focus on data acquisition and API extensions.

## Overview

This branch focuses on extending the OpenMesh repository's data fetching capabilities, supporting multiple weather data sources and providing robust APIs for data retrieval and processing.

## Key Features

### 1. Multi-Source Data Fetching

- **NOAA ASOS** – Automated Surface Observing System weather stations
  - IEM API integration
  - Multiple station support
  - 5-minute and hourly resolution
  - See: `src/fetch_data/noaa_asos/`

- **Weather Underground** – Personal Weather Stations (PWS)
  - Community weather station network
  - Historical data retrieval
  - Metadata-based station discovery
  - See: `src/fetch_data/weather_underground/`

- **OpenMesh CML** – Commercial Microwave Links
  - Zenodo dataset download
  - NetCDF processing
  - See: `src/fetch_data/OpenMesh/`

### 2. API Extensions

- **Auto-fetch functionality** – Automatically fetch data when not available locally
- **Flexible loading modes** – `load`, `fetch`, or `auto` modes
- **Date range matching** – Automatic period alignment across datasets
- **Multi-format support** – NetCDF, CSV, and grouped data structures

### 3. Data Processing

- **Standard format conversion** – Unified data structures across sources
- **Time alignment** – Synchronize data from multiple sources
- **Quality filtering** – Data validation and cleaning
- **Export capabilities** – Multiple output formats

## Repository Structure

```
openmesh-fetch/
├── src/
│   ├── fetch_data/
│   │   ├── noaa_asos/          # NOAA ASOS data fetching
│   │   │   ├── asos_functions.py
│   │   │   ├── asos_pipeline.ipynb
│   │   │   └── asos_plotting.py
│   │   ├── weather_underground/ # Weather Underground PWS
│   │   │   ├── wu_functions.py
│   │   │   ├── wu_pipeline.ipynb
│   │   │   └── wu_plotting.py
│   │   └── OpenMesh/            # OpenMesh CML download
│   │       └── download_and_read_openmesh.ipynb
│   ├── analysis/
│   │   ├── load_data.py         # Unified data loading
│   │   └── plotting.py           # Visualization tools
│   └── config.py                 # API key management
└── src/data/                     # Data storage (gitignored)
    ├── noaa_asos/
    ├── wu_pws/
    └── openmesh/
```

## Usage Examples

### Fetch NOAA ASOS Data

```python
from src.analysis.load_data import load_noaa_asos

# Auto-fetch if not available
df_asos = load_noaa_asos(
    start_date='20240115',
    end_date='20240130',
    mode='auto',  # 'load', 'fetch', or 'auto'
    stations=['KJFK', 'KLGA', 'KNYC'],
    resolution='5min'
)
```

### Fetch Weather Underground Data

```python
from src.fetch_data.weather_underground.wu_functions import run_wu_pipeline

# Run complete pipeline
validated_dates = run_wu_pipeline(
    station_ids=['KNYNEWYO1805', 'KNYNEWYO1659'],
    start_date='2024-01-15',
    end_date='2024-01-30',
    export_all=False
)
```

## Configuration

### API Keys

API keys are managed securely:
- Environment variables (recommended)
- `src/config_secrets.py` (gitignored)
- See `src/config_secrets.example.py` for template

### Data Storage

All fetched data is stored in `src/data/` (gitignored):
- Large files are not committed
- CSV and NetCDF files excluded from version control
- See `.gitignore` for details

## Development Roadmap

- [ ] Additional weather data sources
- [ ] Real-time data fetching
- [ ] Data caching and optimization
- [ ] Extended API coverage
- [ ] Multi-region support

## Contributing

When adding new data sources:
1. Create functions in appropriate `src/fetch_data/` subdirectory
2. Integrate with `load_data.py` for unified access
3. Add configuration options
4. Update documentation

## Related Documentation

- [Main README](../README.md) – Overall repository structure
- [Software Development Branch](README-openmesh-software.md) – OpenSense methods and QC
- [NOAA ASOS README](src/fetch_data/noaa_asos/README.md) – ASOS-specific documentation
- [Weather Underground README](src/fetch_data/weather_underground/README.md) – WU-specific documentation

