# Command Line Usage Guide

Complete reference for all CLI commands to fetch and download data.

**Location:** Run commands from project root or `src/fetch_data/` directory

---

## Quick Commands (TL;DR)

**Most common workflows:**

```bash
# Download OpenMesh dataset from Zenodo
python src/fetch_data/main.py openmesh

# Fetch ASOS airport data (standardized, metric units)
python src/fetch_data/main.py asos -s JFK LGA --start 2024-01-15 --end 2024-01-31

# Fetch Weather Underground PWS data
python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-01-15 --end 2024-01-31

# Check what data you have
python src/fetch_data/main.py status

# Run all pipelines with defaults
python src/fetch_data/main.py all
```

**Note:** WU requires API key (set `export WU_API_KEY="your_key"` or use `--api-key` flag)

---

## Quick Reference

```bash
# From project root:
python src/fetch_data/main.py <command> [options]

# Or from src/fetch_data/ directory:
python main.py <command> [options]
```

---

## 1. OpenMesh Dataset (Zenodo Download)

Download pre-collected NYC Mesh Network dataset from Zenodo.

### Basic Command
```bash
python src/fetch_data/main.py openmesh
```

**What it does:**
- Downloads `OpenMesh.zip` from Zenodo
- Extracts and organizes files
- Saves to `dataset/archived/openmesh/` and `dataset/raw/openmesh/`

**Output:**
- ZIP: `dataset/archived/openmesh/OpenMesh.zip`
- NetCDF: `dataset/raw/openmesh/*.nc`
- Metadata: `dataset/meta/*.csv`

**Note:** One-time download, not a live API fetch.

---

## 2. NOAA ASOS Data

Fetch 1-minute weather data from airport stations via IEM API.

### Basic Commands

**Save standardized data (default):**
```bash
python src/fetch_data/main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-30
```

**Save raw data (US units):**
```bash
python src/fetch_data/main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-30 --type raw
```

**Save standardized data (explicit):**
```bash
python src/fetch_data/main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-30 --type standard
```

**Save resampled data (5-minute intervals):**
```bash
python src/fetch_data/main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-30 --type resampled --resample-interval 5min
```

**Save resampled data (15-minute intervals):**
```bash
python src/fetch_data/main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-30 --type resampled --resample-interval 15min
```

**Save resampled data (hourly):**
```bash
python src/fetch_data/main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-30 --type resampled --resample-interval 1H
```

**With defaults (uses JFK, LGA, NYC, 2024-01-01 to 2024-01-30):**
```bash
python src/fetch_data/main.py asos
```

### Options

| Option | Description | Default |
|--------|-------------|-----------|
| `-s, --stations` | Station IDs (space-separated) | `JFK LGA NYC` |
| `--start` | Start date (YYYY-MM-DD) | `2024-01-01` |
| `--end` | End date (YYYY-MM-DD) | `2024-01-30` |
| `--type` | Data type: `raw`, `standard`, `resampled` | `standard` |
| `--resample-interval` | Interval for resampled type (e.g., `5min`, `15min`, `1H`) | `5min` |
| `--api-response` | Also save raw API response to `api_response/` subfolder | `False` |

### Output Files

**Raw data:**
- `dataset/raw/fetched/asos/api_response/ASOS_raw_YYYY-MM-DD_YYYY-MM-DD.csv`

**Standardized data:**
- `dataset/raw/fetched/asos/ASOS_standard_YYYY-MM-DD_YYYY-MM-DD.csv`

**Resampled data:**
- `dataset/raw/fetched/asos/ASOS_5min_YYYY-MM-DD_YYYY-MM-DD.csv`
- `dataset/raw/fetched/asos/ASOS_15min_YYYY-MM-DD_YYYY-MM-DD.csv`
- `dataset/raw/fetched/asos/ASOS_1H_YYYY-MM-DD_YYYY-MM-DD.csv`

### Station IDs

Use 3-letter airport codes:
- `JFK` - JFK Airport
- `LGA` - LaGuardia Airport
- `NYC` - Central Park

Find more stations:
- Metadata: `dataset/meta/ASOS_stations.csv`
- IEM Network: https://mesonet.agron.iastate.edu/sites/networks.php?network=ASOS

---

## 3. Weather Underground (PWS Data)

Fetch data from Personal Weather Stations via WU API.

### Basic Commands

**Fetch specific stations:**
```bash
python src/fetch_data/main.py wu -s KNYNEWYO1805 KNYNEWYO1850 --start 2024-01-01 --end 2024-01-30
```

**Fetch all stations from metadata:**
```bash
python src/fetch_data/main.py wu --all-stations --start 2024-01-01 --end 2024-01-30
```

**With API key (if not in environment):**
```bash
python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-30 --api-key YOUR_API_KEY
```

**Save API response data (raw + processed):**
```bash
python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-30 --api-response
```

**With defaults:**
```bash
python src/fetch_data/main.py wu
```

### Options

| Option | Description | Default |
|--------|-------------|-----------|
| `-s, --stations` | Station IDs (space-separated) | `KNYNEWYO1805 KNYNEWYO1850` |
| `--all-stations` | Load all stations from `dataset/meta/pws_metadata.csv` | `False` |
| `--start` | Start date (YYYY-MM-DD) | `2024-01-01` |
| `--end` | End date (YYYY-MM-DD) | `2024-01-30` |
| `--api-key` | WU API key (or set `WU_API_KEY` env var) | From env/config |
| `--api-response` | Also save raw API response to `api_response/` subfolder | `False` |

### API Key Setup

**Option 1: Environment variable**
```bash
export WU_API_KEY="your_api_key_here"
python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-30
```

**Option 2: Command line**
```bash
python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-30 --api-key your_api_key_here
```

**Option 3: Config file**
Add to `src/fetch_data/weather_underground/config.py`

**Get API Key:** https://www.wunderground.com/member/api-keys

### Output Files

**Processed data:**
- `dataset/raw/fetched/wu/WU_YYYY-MM-DD_YYYY-MM-DD.csv`

**API response (if `--api-response` used):**
- `dataset/raw/fetched/wu/api_response/WU_YYYY-MM-DD_YYYY-MM-DD.csv`

### Station IDs

Find stations:
- Metadata: `dataset/meta/pws_metadata.csv`
- WU Map: https://www.wunderground.com/wundermap

---

## 4. Dataset Status

Check what data files are currently saved.

```bash
python src/fetch_data/main.py status
```

**Shows:**
- Available files in each output directory
- File sizes and modification dates
- Summary of dataset structure

---

## 5. Run All Pipelines

Run all data fetching pipelines with default settings.

```bash
python src/fetch_data/main.py all
```

**Runs:**
1. OpenMesh download
2. ASOS fetch (default stations and dates)
3. WU fetch (default stations and dates)

---

## Examples

### Example 1: Fetch ASOS data for January 2024 (standardized)
```bash
python src/fetch_data/main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-31 --type standard
```

### Example 2: Fetch ASOS raw data and save to api_response folder
```bash
python src/fetch_data/main.py asos -s JFK LGA --start 2024-01-01 --end 2024-01-15 --type raw
```

### Example 3: Fetch ASOS hourly resampled data
```bash
python src/fetch_data/main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-30 --type resampled --resample-interval 1H
```

### Example 4: Fetch WU data for all stations in June
```bash
export WU_API_KEY="your_key"
python src/fetch_data/main.py wu --all-stations --start 2024-06-01 --end 2024-06-30
```

### Example 5: Fetch WU data with API response saved
```bash
python src/fetch_data/main.py wu -s KNYNEWYO1805 KNYNEWYO1850 --start 2024-01-01 --end 2024-01-30 --api-response
```

---

## Default Settings

Default values are defined in `main.py` (lines 50-60):

**ASOS defaults:**
- Stations: `['JFK', 'LGA', 'NYC']`
- Start: `2024-01-01`
- End: `2024-01-30`

**WU defaults:**
- Stations: `['KNYNEWYO1805', 'KNYNEWYO1850']`
- Start: `2024-01-01`
- End: `2024-01-30`

Edit these in `main.py` to customize quick runs without CLI arguments.

---

## Output Directory Structure

```
dataset/
├── archived/
│   └── openmesh/
│       └── OpenMesh.zip
├── raw/
│   ├── openmesh/
│   │   └── *.nc (NetCDF files)
│   └── fetched/
│       ├── asos/
│       │   ├── ASOS_standard_*.csv
│       │   ├── ASOS_5min_*.csv
│       │   ├── ASOS_1H_*.csv
│       │   └── api_response/
│       │       └── ASOS_raw_*.csv
│       └── wu/
│           ├── WU_*.csv
│           └── api_response/
│               └── WU_*.csv
└── meta/
    ├── ASOS_stations.csv
    └── pws_metadata.csv
```

---

## Troubleshooting

### ASOS: No data fetched
- Check date range (data is delayed 18-36 hours)
- Verify station IDs are correct
- Check internet connection

### WU: API key error
- Set `WU_API_KEY` environment variable
- Or use `--api-key` flag
- Or add to `weather_underground/config.py`

### File already exists
- Files will be overwritten by default
- Check if you want to keep existing data before rerunning

### Permission errors
- Ensure write permissions to `dataset/` directory
- Check disk space

---

## See Also

- **README.md** - Overview and quick start
- **src/fetch_data/README.md** - Module overview
- **src/README.md** - Source code documentation
- **dataset/README.md** - Dataset structure and formats