# Data Fetching

Scripts and notebooks for fetching weather data from various sources.

**Last Updated:** 2025-11-16 - Added complete pipeline notebooks with modular functions

## 📁 Folder Structure
```
fetch_data/
├── noaa_asos/
│   ├── asos_complete_pipeline.ipynb    # Main notebook
│   ├── asos_functions.py               # Fetch & process functions
│   └── asos_plotting.py                # Visualization functions
│
├── weather_underground/
│   ├── wu_complete_pipeline.ipynb      # Main notebook
│   ├── wu_functions.py                 # Fetch & process functions
│   └── wu_meta_mapping.py              # Metadata utilities
│
└── openmesh/
    └── download_and_read_openmesh.ipynb  # Download & extract

data/                                   # All outputs saved here
├── noaa_asos/
├── wu_pws/
└── openmesh/
```

## 📊 Data Sources

### 1. NOAA ASOS (`noaa_asos/`)
**Source:** Iowa Environmental Mesonet (IEM) ASOS API  
**Data:** Airport weather stations (temp, wind, precip, pressure)  
**Resolution:** 5-minute or hourly  
**API Key:** Not required ✓  
**Manual Download:** https://mesonet.agron.iastate.edu/request/download.phtml

**Quick Start:**
1. Open `asos_complete_pipeline.ipynb`
2. Configure date period and stations in cell 2:
```python
   START_DATE = datetime(2024, 1, 1)
   END_DATE = datetime(2024, 1, 30)
   DATA_RESOLUTION = '5min'  # or 'hourly'
   STATION_IDS = ['KJFK', 'KLGA', 'KNYC']  # Any US airport codes
```
3. Run all cells

**Station Selection:**
- Use 4-letter ICAO codes (e.g., KJFK, KLGA, KNYC)
- NYC stations metadata: See `../dataset/weather stations/ASOS_stations.csv`
- Or find stations manually at: https://mesonet.agron.iastate.edu/sites/networks.php?network=ASOS

### 2. Weather Underground (`weather_underground/`)
**Source:** Weather Underground Personal Weather Stations API  
**Data:** Community weather stations  
**Resolution:** Variable (typically 5-30 minutes)  
**API Key:** Required ⚠️  
**Get Key:** https://www.wunderground.com/member/api-keys

**Quick Start:**
1. Set environment variable: `export WU_API_KEY="your_key_here"`
2. Open `wu_complete_pipeline.ipynb`
3. Configure date period and stations:
```python
   START_DATE = "20240101"
   END_DATE = "20240130"
   STATION_IDS = ["KNYNEWYO1805", "KNYNEWYO1850"]
```
4. Run all cells

**Station Selection:**
- Pre-selected NYC PWS stations available in pipeline
- NYC stations metadata: See `../dataset/weather stations/pws_metadata.csv`
- Or search manually at: https://www.wunderground.com/wundermap

### 3. OpenMesh (`openmesh/`)
**Source:** Zenodo repository (NYC Mesh Network data)  
**Data:** Pre-collected weather & network data (2023-2024)  
**API Key:** Not required ✓  
**Repository:** https://zenodo.org/records/15287692

**Quick Start:**
1. Open `download_and_read_openmesh.ipynb`
2. Run all cells (auto-downloads and extracts)
3. Data extracts to `data/openmesh/extracted/dataset/`

**Included Data:**
- Commercial Microwave Links (CML) weather data
- Personal Weather Stations (PWS) data
- Station metadata and network topology

## 🎯 Output Location

All fetched data saves to: `src/data/<source_name>/`

Examples:
- `data/noaa_asos/KJFK_20240101_20240130_5min.csv`
- `data/wu_pws/weather_clean_20240101_20240130.csv`
- `data/openmesh/extracted/dataset/`

## 📋 Requirements

- Python 3.8+
- pandas, numpy, matplotlib, requests
- **Weather Underground only:** API key required

## 📍 Station Metadata

Station metadata files are located in `../dataset/weather stations/`:
- `ASOS_stations.csv` - NOAA airport weather stations (NYC area)
- `pws_metadata.csv` - Weather Underground personal weather stations (NYC)

Use these files to find station IDs for your area of interest.


