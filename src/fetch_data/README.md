# Data Fetching & Download

Scripts and notebooks for downloading and fetching weather data from various sources.

## Folder Structure

```
src/fetch_data/
├── config.py                           # Shared paths & output dirs (dataset/...)
├── main.py                             # CLI for all pipelines
├── OpenMesh/
│   ├── download_and_read_openmesh.ipynb
│   └── openmesh.py
├── noaa_asos/
│   ├── asos_pipeline.ipynb
│   ├── asos_fetch.py
│   └── config.py
├── weather_underground/
│   ├── wu_pipeline.ipynb
│   ├── wu_fetch.py
│   └── config.py
├── README.md
└── USAGE.md                            # Full CLI reference

dataset/                                # All data saved here (paths from config.py)
├── meta/                               # Metadata (CSVs)
│   ├── ASOS_stations.csv
│   ├── pws_metadata.csv
│   ├── links_metadata.csv
│   └── maps/
├── raw/
│   ├── fetched/                        # API-fetched data
│   │   ├── asos/                       # ASOS_standard_*.csv, ASOS_5min_*.csv, etc.
│   │   │   └── api_response/           # Optional raw API CSVs
│   │   └── wu/                         # WU_*.csv
│   │       └── api_response/
│   └── openmesh/                       # Created by OpenMesh pipeline: *.nc
├── archived/openmesh/                  # OpenMesh.zip, PWS_NYC_WU.zip, extracted/
│   └── extracted/                      # README + other (organize=True) or full ZIP (organize=False)
└── examples/                           # Example notebooks for reading sample data
```

## Data Sources

### 1. OpenMesh Dataset (Zenodo Download)

**Source:** Zenodo repository — Pre-collected NYC Mesh Network data  
**Type:** Dataset download (not live API)  
**Data:** Pre-collected weather & network data (Oct 2023 – Jul 2024)  
**API Key:** Not required  
**Repository:** https://zenodo.org/records/15287692

What's included:
- Wireless links weather data
- Personal Weather Stations (PWS) data
- Station metadata and network topology

**Quick Start:**

CLI:
```bash
python src/fetch_data/main.py openmesh
```

Notebook: Open `OpenMesh/download_and_read_openmesh.ipynb`, run cells 4–5 (downloads ZIP and extracts/organizes files).

Python:
```python
from src.fetch_data.OpenMesh.openmesh import run_openmesh_pipeline, run_pws_wu_pipeline, load_pws, load_links

run_openmesh_pipeline()   # Download + extract OpenMesh.zip
run_pws_wu_pipeline()     # Download + extract PWS_NYC_WU.zip → pws_wu_os.nc

# Load data
pws = load_pws(sample=True)   # pws_opensense_sample_jan.nc
pws = load_pws(sample=False)  # pws_wu_os.nc
links_ds = load_links()
```

Output Structure:
- ZIP file: `dataset/archived/openmesh/OpenMesh.zip`
- Extracted (docs / as-is): `dataset/archived/openmesh/extracted/` (README.txt and other when organize=True; full ZIP when organize=False)
- Raw data: `dataset/raw/openmesh/*.nc` (NetCDF files)
- Metadata: `dataset/meta/*.csv`
- Examples: `dataset/examples/*.ipynb`
- Maps: `dataset/meta/maps/*.html`

Note: This is a one-time download of a pre-existing dataset, not a live API fetch.

**1.2 PWS Weather Underground (Zenodo Download)**

**Source:** Zenodo — PWS NYC Weather Underground dataset  
**Type:** Dataset download (not live API)  
**Data:** Full PWS time series (NetCDF), ~8 months of measurements (aligned with OpenMesh period)  
**API Key:** Not required  
**Repository:** https://zenodo.org/records/17508286

- Download: `PWS_NYC_WU.zip` from the repository above (or via `openmesh.py` / pipeline).
- Extracts to: `dataset/raw/openmesh/pws_wu_os.nc`
- Sample PWS from the main OpenMesh ZIP (above) is: `dataset/raw/openmesh/pws_opensense_sample_jan.nc`

---

### PWS / Weather Underground data: three options

| Option | Source | Period | Resolution | API key |
|--------|--------|--------|------------|---------|
| **Sample** | OpenMesh Zenodo (1.1) | January sample | NetCDF (higher res) | No |
| **Full** | PWS Zenodo (1.2) | ~8 months of measurements | NetCDF (higher res) | No |
| **API** | Weather Underground (2.2) | Any period you request | Hourly | Yes |

- **Sample:** `pws_opensense_sample_jan.nc` from OpenMesh.zip (`main.py openmesh`).
- **Full:** `pws_wu_os.nc` from PWS_NYC_WU.zip (Zenodo 17508286); run OpenMesh PWS WU pipeline or download the ZIP.
- **API:** `main.py wu` with `WU_API_KEY`; fetches hourly historical data for chosen stations and date range.

---

### 2. API-Fetched Data Sources

#### 2.1 NOAA ASOS (`noaa_asos/`)

**Source:** Iowa Environmental Mesonet (IEM) ASOS 1-minute archive  
**Data:** Airport weather stations (temp, wind, precip, pressure)  
**Resolution:** 1-minute readings  
**API Key:** Not required  
**Endpoint:** https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py  
**Docs:** https://mesonet.agron.iastate.edu/request/asos/1min.phtml  
**Archive:** Available for US ASOS sites back to 2000

This pipeline uses the **1-minute ASOS archive** which NCEI (National Centers for Environmental Information) collects directly from ASOS stations via phone twice daily. IEM processes and provides a clean, accessible download. Data is delayed 18–36 hours (not real-time) due to the NCEI collection method.

**Variables:**

| Variable | Unit | Description |
|----------|------|-------------|
| `temp_c` | °C | Temperature |
| `dewpoint_c` | °C | Dewpoint |
| `wind_speed_ms` | m/s | Wind speed |
| `wind_gust_ms` | m/s | Wind gust |
| `wind_dir_deg` | ° | Wind direction |
| `visibility_km` | km | Visibility |
| `precip_type` | — | Precipitation type (rain, snow, etc.) |
| `precip_mm` | mm | Precipitation |

**Quick Start:**
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

#### 2.2 Weather Underground (`weather_underground/`)

**Source:** Weather Underground Personal Weather Stations API  
**Data:** Community weather stations  
**Resolution:** Variable (typically 5–30 minutes), fetched as hourly aggregates  
**API Key:** Required — [Get key here](https://www.wunderground.com/member/api-keys)  
**Output:** Clean CSV files with standardized column names (precipitation rate/total, temperature, humidity, wind, pressure)

**API Key Configuration:**

For complete setup instructions, see [weather_underground/API_KEY_SETUP.md](weather_underground/API_KEY_SETUP.md).

| Method | Details |
|--------|---------|
| **Environment variable** (recommended) | `export WU_API_KEY="your_key_here"` |
| **Config file** (fallback) | Set in `weather_underground/config.py` |
| **CLI argument** | Use `--api-key` flag |

**Quick Start:**
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
- Raw: `dataset/raw/openmesh/*.nc` (e.g. `pws_opensense_sample_jan.nc` from OpenMesh.zip; `pws_wu_os.nc` from PWS_NYC_WU.zip)
- Meta: `dataset/meta/*.csv`

**API-Fetched Data:**
- Processed: `dataset/raw/fetched/{asos|wu}/*.csv`
- API Response (optional): `dataset/raw/fetched/{asos|wu}/api_response/*.csv`

Examples:
- `dataset/raw/fetched/asos/ASOS_standard_2024-01-01_2024-01-29.csv` (standardized)
- `dataset/raw/fetched/asos/ASOS_5min_2024-01-01_2024-01-29.csv` (resampled)
- `dataset/raw/fetched/asos/api_response/ASOS_raw_2024-01-01_2024-01-29.csv` (raw API)
- `dataset/raw/fetched/wu/WU_2024-01-01_2024-01-30.csv`
- `dataset/raw/openmesh/ds_openmesh.nc` (after OpenMesh pipeline)

## Command Line Interface

Use `main.py` to run all pipelines from the command line (alternative to notebooks).

**For complete command reference, see [USAGE.md](USAGE.md)**

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

- `config.py` — Shared paths and output directories
- `noaa_asos/config.py` — ASOS-specific settings
- `weather_underground/config.py` — WU-specific settings (includes API key)

## Requirements

- Python 3.8+
- pandas, numpy, matplotlib, requests
- Weather Underground only: API key required

## Station Metadata

Station metadata files are located in `dataset/meta/`:
- `ASOS_stations.csv` — NOAA airport weather stations (NYC area)
- `pws_metadata.csv` — Weather Underground personal weather stations (NYC)

Use these files to find station IDs for your area of interest.