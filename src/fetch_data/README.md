# Data Fetching & Download

Scripts and notebooks for downloading and fetching weather data from various sources.

**Last Updated:** 2025-01-16 - Added CLI interface (`main.py`) and standardized data structure

## Folder Structure

```
fetch_data/
├── OpenMesh/
│   ├── download_and_read_openmesh.ipynb  # Download & extract
│   └── openmesh.py                       # Download/load functions
│
├── noaa_asos/
│   ├── asos_pipeline.ipynb             # Main notebook
│   ├── asos_fetch.py                   # Fetch, process & plot functions
│   └── config.py                       # Column mapping & config
│
├── weather_underground/
│   ├── wu_pipeline.ipynb               # Main notebook
│   ├── wu_fetch.py                     # Fetch, process & plot functions
│   └── config.py                       # Column mapping & config
│
└── main.py                             # CLI interface for all pipelines

dataset/                                # All data saved here
├── archived/                           # Downloaded ZIP files
│   └── openmesh/
│       └── OpenMesh.zip
├── meta/                               # Metadata files (CSVs)
│   ├── openmesh/                       # OpenMesh metadata
│   ├── ASOS_stations.csv
│   └── pws_metadata.csv
├── examples/                           # Example notebooks
└── raw/                                # Raw data
    ├── openmesh/                       # Extracted OpenMesh data (NetCDF)
    └── fetched/                        # API-fetched data
        ├── asos/
        │   └── api_response/          # API response data (optional)
        └── wu/
            └── api_response/          # API response data (optional)
```

## Data Sources

### 1. OpenMesh Dataset (Zenodo Download)

**Source:** Zenodo repository - Pre-collected NYC Mesh Network data  
**Type:** Dataset download (not live API)  
**Data:** Pre-collected weather & network data (Oct 2023 - Jul 2024)  
**API Key:** Not required  
**Repository:** https://zenodo.org/records/15287692

What's included:
- Commercial Microwave Links (CML) weather data
- Personal Weather Stations (PWS) data  
- Station metadata and network topology

**Quick Start:**

CLI:
```bash
cd src/fetch_data
python main.py openmesh
```

Notebook:
1. Open `OpenMesh/download_and_read_openmesh.ipynb`
2. Run cells 4-5 (downloads ZIP and extracts/organizes files)

Output Structure:
- ZIP file: `dataset/archived/openmesh/OpenMesh.zip`
- Raw data: `dataset/raw/openmesh/*.nc` (NetCDF files)
- Metadata: `dataset/meta/openmesh/*.csv`
- Examples: `dataset/examples/*.ipynb`
- Maps: `dataset/meta/maps/*.html`

Note: This is a one-time download of a pre-existing dataset, not a live API fetch.

---

### 2. API-Fetched Data Sources

**2.1 NOAA ASOS** (`noaa_asos/`)

**Source:** Iowa Environmental Mesonet (IEM) ASOS API  
**Data:** Airport weather stations (temp, wind, precip, pressure)  
**Resolution:** 1-minute readings  
**API Key:** Not required  
**Manual Download:** https://mesonet.agron.iastate.edu/request/download.phtml

Quick Start:
1. Open `asos_pipeline.ipynb`
2. Configure date period and stations in cell 2:
```python
START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2024, 1, 30)
DATA_RESOLUTION = '5min'  # or 'hourly'
STATION_IDS = ['JFK', 'LGA', 'NYC']  # Any US airport codes
```
3. Run all cells

Station Selection:
- Use 3-letter airport codes (e.g., JFK, LGA, NYC)
- NYC stations metadata: See `dataset/meta/ASOS_stations.csv`
- Or find stations manually at: https://mesonet.agron.iastate.edu/sites/networks.php?network=ASOS

**2.2 Weather Underground** (`weather_underground/`)

**Source:** Weather Underground Personal Weather Stations API  
**Data:** Community weather stations  
**Resolution:** Variable (typically 5-30 minutes)  
**API Key:** Required  
**Get Key:** https://www.wunderground.com/member/api-keys

Quick Start:
1. Set environment variable: `export WU_API_KEY="your_key_here"`
2. Open `wu_pipeline.ipynb`
3. Configure date period and stations:
```python
START_DATE = "20240101"
END_DATE = "20240130"
STATION_IDS = ["KNYNEWYO1805", "KNYNEWYO1850"]
```
4. Run all cells

Station Selection:
- Pre-selected NYC PWS stations available in pipeline
- NYC stations metadata: See `dataset/meta/pws_metadata.csv`
- Or search manually at: https://www.wunderground.com/wundermap

## Output Location

**OpenMesh (Download):**
- ZIP: `dataset/archived/openmesh/OpenMesh.zip`
- Raw: `dataset/raw/openmesh/*.nc`
- Meta: `dataset/meta/openmesh/*.csv`

**API-Fetched Data:**
- Processed: `dataset/raw/fetched/{asos|wu}/*.csv`
- API Response (optional): `dataset/raw/fetched/{asos|wu}/api_response/*.csv`

Examples:
- `dataset/raw/fetched/asos/ASOS_1min_2024-01-01_2024-01-29.csv` (processed)
- `dataset/raw/fetched/asos/api_response/ASOS_raw_2024-01-01_2024-01-29.csv` (API response)
- `dataset/raw/fetched/wu/WU_2024-01-01_2024-01-30.csv` (processed)
- `dataset/raw/openmesh/ds_openmesh.nc` (OpenMesh NetCDF)

## Command Line Interface

Use `main.py` to run all pipelines from the command line (alternative to notebooks).

**📖 For complete command reference, see [USAGE.md](USAGE.md)**

### Quick Examples

```bash
# From project root:
python src/fetch_data/main.py <command> [options]

# Or from src/fetch_data/ directory:
cd src/fetch_data
python main.py <command> [options]
```

**Common commands:**
```bash
python src/fetch_data/main.py status              # Show dataset status
python src/fetch_data/main.py openmesh            # Download OpenMesh dataset
python src/fetch_data/main.py asos                # Fetch ASOS data (defaults)
python src/fetch_data/main.py wu                  # Fetch WU data (defaults)
python src/fetch_data/main.py all                 # Run all pipelines
```

**ASOS examples:**
```bash
# Standardized data (default)
python src/fetch_data/main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-30

# Raw data (saves to api_response/ folder)
python src/fetch_data/main.py asos -s JFK LGA --start 2024-01-01 --end 2024-01-30 --type raw

# Resampled hourly data
python src/fetch_data/main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-30 --type resampled --resample-interval 1H
```

**WU examples:**
```bash
# Specific stations
python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-30

# All stations from metadata
python src/fetch_data/main.py wu --all-stations --start 2024-01-01 --end 2024-01-30
```

See **[USAGE.md](USAGE.md)** for complete documentation with all options and examples.

## Configuration

The project uses modular configuration:

- `config.py` - Shared paths and output directories
- `noaa_asos/config.py` - ASOS-specific settings
- `weather_underground/config.py` - WU-specific settings (includes API key)

## Requirements

- Python 3.8+
- pandas, numpy, matplotlib, requests
- Weather Underground only: API key required

## Station Metadata

Station metadata files are located in `dataset/meta/`:
- `ASOS_stations.csv` - NOAA airport weather stations (NYC area)
- `pws_metadata.csv` - Weather Underground personal weather stations (NYC)

Use these files to find station IDs for your area of interest.