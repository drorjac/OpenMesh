# Weather Underground API - Data Fetching

Fetch historical weather data from Weather Underground Personal Weather Stations (PWS) API.

## 📁 Files

- **`wu_pipeline.ipynb`** - Complete workflow notebook
- **`wu_fetch.py`** - API fetching functions
- **`wu_plotting.py`** - Plotting and visualization functions
- **`config.py`** - Column mapping, API configuration, and API key management

## 🔑 API Key Configuration

Weather Underground requires an API key for authentication.

**📖 For complete API key setup instructions, see [API_KEY_SETUP.md](API_KEY_SETUP.md)**

### Quick Setup (Recommended)

```bash
# Set environment variable (persists if added to ~/.zshrc)
export WU_API_KEY="your_api_key_here"
```

**Get your API key:** https://www.wunderground.com/member/api-keys

### Configuration Methods

1. **Environment Variable** ⭐ (Recommended) - Most secure
2. **Config File** - Fallback in `config.py`
3. **CLI Argument** - Use `--api-key` flag

See [API_KEY_SETUP.md](API_KEY_SETUP.md) for detailed instructions, troubleshooting, and security best practices.

## 🚀 Quick Start

1. **Configure API key** (see above)
2. **Run via CLI:**
   ```bash
   python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-30
   ```
3. **Or use notebook:**
   - Open `wu_pipeline.ipynb`
   - Configure station IDs and date range
   - Run all cells

## 📊 Output

Fetches historical weather data at hourly resolution (aggregated):
- Clean CSV files with standardized column names
- Precipitation data (rate and total)
- Temperature, humidity, wind, pressure
- Metadata and station information

**Output location:** `dataset/raw/fetched/wu/WU_YYYY-MM-DD_YYYY-MM-DD.csv`

## 📖 See Also

- **Main README:** `src/fetch_data/README.md` - Overview of all data sources
- **Usage Guide:** `src/fetch_data/USAGE.md` - Complete CLI command reference
- **Config File:** `config.py` - Detailed API key configuration and column mappings

---

Part of the OpenMesh project.
