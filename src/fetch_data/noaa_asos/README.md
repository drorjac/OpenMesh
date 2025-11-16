# NOAA ASOS API - Airport Weather Data Fetching

Quick example for fetching data from NOAA ASOS stations via Iowa Environmental Mesonet (IEM) API.

## 📁 Files

- **`asos_complete_pipeline.ipynb`** - Complete workflow notebook
- **`asos_functions.py`** - API fetching & processing functions
- **`asos_plotting.py`** - Visualization functions

## 🚀 Quick Start

1. Open `asos_complete_pipeline.ipynb`
2. Configure dates, resolution, and station codes:
```python
   START_DATE = datetime(2024, 1, 1)
   END_DATE = datetime(2024, 1, 30)
   DATA_RESOLUTION = '5min'  # or 'hourly'
   STATION_IDS = ['KJFK', 'KLGA', 'KNYC']
```
3. Run the notebook (no API key needed!)

## 📊 What You Get

- **Variables:** Temperature, dewpoint, wind, pressure, precipitation, humidity, visibility
- **Resolution:** 5-minute or hourly
- **Format:** Clean CSV files with metric units
- **Stations:** 4000+ US airport stations available

## 🌐 Data Source

- **API:** Iowa Environmental Mesonet (IEM)
- **Manual Download:** https://mesonet.agron.iastate.edu/request/download.phtml
- **Station List:** https://mesonet.agron.iastate.edu/sites/networks.php?network=ASOS

## 📍 Finding Station Codes

Use any 4-letter airport code (ICAO):
- JFK Airport → `KJFK`
- LaGuardia → `KLGA`
- O'Hare → `KORD`
- LAX → `KLAX`

Part of the OpenMesh project.