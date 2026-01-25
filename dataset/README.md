# Dataset Directory

This directory contains all downloaded and fetched weather data for the OpenMesh project.

**Note:** This directory is gitignored and not tracked in version control due to large file sizes.

## Directory Structure

```
dataset/
├── archived/                   # Downloaded ZIP files
│   └── openmesh/
│       └── OpenMesh.zip       # Original Zenodo download
│
├── raw/                        # Raw data files
│   ├── openmesh/              # OpenMesh NetCDF files from Zenodo
│   └── fetched/               # API-fetched data
│       ├── asos/              # NOAA ASOS airport weather data
│       └── wu/                # Weather Underground PWS data
│
├── meta/                       # Station metadata and maps
│   ├── openmesh/              # OpenMesh-specific metadata
│   ├── maps/                  # Interactive HTML maps
│   ├── ASOS_stations.csv      # NOAA station metadata
│   └── pws_metadata.csv       # PWS station metadata
│
└── examples/                   # Example Jupyter notebooks from Zenodo
```

---

## Contents

### archived/openmesh/

Original downloaded ZIP file from Zenodo:

- `OpenMesh.zip` - Complete dataset archive (13 MB compressed)

**Source:** https://zenodo.org/records/15287692  
**Note:** After extraction and organization, the ZIP can be kept for backup or deleted to save space.

### raw/openmesh/

OpenMesh dataset files downloaded from Zenodo:

- `ds_openmesh.nc` - Main microwave links dataset (OpenSense v1.0 compliant NetCDF)
- `pws_opensense_sample_jan.nc` - PWS sample data for January
- `pws_opensense_os.nc` - Complete PWS dataset (OpenSense format)

**Format:** NetCDF  
**Source:** https://zenodo.org/records/15287692

### raw/fetched/asos/

NOAA ASOS airport weather station data fetched via IEM API:

- Processed files: `ASOS_1min_YYYY-MM-DD_YYYY-MM-DD.csv`
- API response files (optional): `api_response/ASOS_raw_YYYY-MM-DD_YYYY-MM-DD.csv`

**Stations:** JFK, LGA, NYC (configurable)  
**Resolution:** 1-minute readings  
**Format:** CSV with standardized columns (temperature, wind, precipitation, etc.)

### raw/fetched/wu/

Weather Underground Personal Weather Station data fetched via API:

- Processed files: `WU_YYYY-MM-DD_YYYY-MM-DD.csv`
- API response files (optional): `api_response/WU_raw_YYYY-MM-DD_YYYY-MM-DD.csv`

**Stations:** NYC area PWS stations (see metadata)  
**Resolution:** Variable (typically 5-30 minutes)  
**Format:** CSV with standardized columns

### meta/

Station metadata and reference files:

**Station Metadata:**
- `ASOS_stations.csv` - NOAA airport stations (location, codes, elevation)
- `pws_metadata.csv` - Weather Underground stations (location, IDs)
- `openmesh/links_metadata.csv` - Microwave link coordinates and properties

**Maps:**
- `maps/directional_map.html` - Interactive map showing link directions
- `maps/frequency_map.html` - Interactive map colored by frequency bands

### examples/

Example Jupyter notebooks included in the Zenodo dataset:

- `openmesh_dataset_example.ipynb` - Load and visualize microwave links data
- `read_pws_sample.ipynb` - Load and explore PWS data
- `pws_with_pypwsqc.ipynb` - PWS data with quality control

**Source:** Extracted from `OpenMesh.zip` during dataset organization  
**Purpose:** Tutorial notebooks showing how to load and work with the OpenMesh data

---

## Data Format Standards

All fetched data (ASOS and WU) uses standardized column names for cross-dataset compatibility:

**Shared columns:**
- `datetime` - UTC timestamp
- `station_id` - Station identifier
- `temperature` - Air temperature (°C)
- `dewpoint` - Dew point temperature (°C)
- `wind_speed` - Wind speed (m/s)
- `wind_direction` - Wind direction (degrees, 0-360)
- `wind_gust` - Wind gust speed (m/s)
- `precip_amount` - Precipitation amount (mm)
- `humidity` - Relative humidity (%)
- `pressure` - Atmospheric pressure (hPa)

See `src/fetch_data/config.py` for complete column definitions.

---

## File Naming Conventions

**ASOS files:**
- Processed: `ASOS_1min_YYYY-MM-DD_YYYY-MM-DD.csv`
- Raw API: `ASOS_raw_YYYY-MM-DD_YYYY-MM-DD.csv`

**Weather Underground files:**
- Processed: `WU_YYYY-MM-DD_YYYY-MM-DD.csv`
- Raw API: `WU_raw_YYYY-MM-DD_YYYY-MM-DD.csv`

**OpenMesh files:**
- Main dataset: `ds_openmesh.nc`
- PWS samples: `pws_opensense_*.nc`

---

## Fetching Additional Data

To fetch more weather data, use the CLI from `src/fetch_data/`:

```bash
cd src/fetch_data

# ASOS data
python main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-31

# Weather Underground data
python main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-31

# Check what's available
python main.py status
```

See `src/fetch_data/README.md` for detailed instructions.

---

## Dataset Organization

When you download the OpenMesh dataset using the CLI or notebook, files are automatically organized:

**Download:**
```bash
cd src/fetch_data
python main.py openmesh
```

**What happens:**
1. Downloads `OpenMesh.zip` from Zenodo → `dataset/archived/openmesh/`
2. Extracts and organizes files:
   - Raw data (*.nc) → `dataset/raw/openmesh/`
   - Metadata (*.csv) → `dataset/meta/openmesh/`
   - Notebooks (*.ipynb) → `dataset/examples/`
   - Maps (*.html) → `dataset/meta/maps/`

**Result:** Clean, organized structure ready for analysis.

**Note:** The original ZIP in `archived/` can be kept as backup or deleted to save space (13 MB).

---

