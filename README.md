# OpenMesh

[ESSD Paper](https://essd.copernicus.org/preprints/essd-2025-238/) | [Zenodo Dataset](https://zenodo.org/records/15287692)

A wireless-link dataset for opportunistic urban weather sensing in New York City, with tools to download, explore, and extend the data.

## Dataset

The core dataset is hosted on Zenodo — no API keys needed, just download and extract.

### OpenMesh (wireless links + PWS sample)

**Zenodo:** [15287692](https://zenodo.org/records/15287692) — `OpenMesh.zip` (13 MB compressed, ~330 MB extracted)

Pre-collected NYC mesh network data (Oct 2023 – Jul 2024):

| File | Description |
|------|-------------|
| `ds_openmesh.nc` | Microwave link RSL time-series (OpenSense v1.0 NetCDF) |
| `pws_opensense_sample_jan.nc` | PWS sample — January only |
| `links_metadata.csv` | Link coordinates, frequency, polarization |
| `pws_metadata.csv` | PWS station locations and metadata |
| `ASOS_stations.csv` | NOAA ASOS station metadata |
| `directional_map.html`, `frequency_map.html` | Interactive link maps |

### PWS full time series

**Zenodo:** [17508286](https://zenodo.org/records/17508286) — `PWS_NYC_WU.zip`

Full Weather Underground PWS dataset (~8 months, aligned with the OpenMesh period), extracted as `pws_wu_os.nc`.

## Additional Data Sources (fetch any period)

Beyond the fixed Zenodo dataset, the repository includes tools to fetch weather data for any date range via APIs.

### NOAA ASOS (no API key)

1-minute airport weather data (temperature, wind, precipitation, pressure) from stations like JFK, LGA, and Central Park. Available back to 2000 via Iowa Environmental Mesonet. Data is delayed 18–36 hours.

### Weather Underground (API key required)

Hourly data from personal weather stations. Covers any period and any WU station. Get a free API key at [wunderground.com](https://www.wunderground.com/member/api-keys) — you'll need to register a virtual PWS to unlock API access. See [API_KEY_SETUP.md](src/fetch_data/weather_underground/API_KEY_SETUP.md) for details.

### PWS data: three options

| Option | Source | Period | API key |
|--------|--------|--------|---------|
| Sample | OpenMesh Zenodo | January only | No |
| Full | PWS Zenodo | ~8 months | No |
| API | Weather Underground | Any period | Yes |

## Setup

```bash
git clone https://github.com/drorjac/OpenMesh.git
cd OpenMesh
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

For WU data, also set your API key:
```bash
export WU_API_KEY="your_key"
```

## Quick Start

### CLI

```bash
python src/fetch_data/main.py openmesh                                                  # Download dataset from Zenodo
python src/fetch_data/main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-31   # Fetch ASOS data
python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-31    # Fetch WU data
python src/fetch_data/main.py status                                                    # Check what's downloaded
python src/fetch_data/main.py all                                                       # Run all pipelines
```

See [USAGE.md](src/fetch_data/USAGE.md) for the full CLI reference.

### Notebooks

| Notebook | Purpose |
|----------|---------|
| `src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb` | Download and explore the Zenodo dataset |
| `src/fetch_data/noaa_asos/asos_pipeline.ipynb` | Fetch and visualize ASOS data |
| `src/fetch_data/weather_underground/wu_pipeline.ipynb` | Fetch WU data (API key required) |

### Analysis

`src/analysis/analysis.ipynb` is the end-to-end notebook. It loads (or fetches) all data sources, converts them to a unified format, and runs basic analysis — time-series plots, link–PWS matching, and rain detection.

Set two options and run all cells:
- **MODE** (`'load'` or `'fetch'`) — load uses existing files; fetch downloads anything missing
- **PWS_OPENMESH_SOURCE** (`'sample'` or `'full'`) — which PWS dataset to use

## Repository Structure

```
OpenMesh/
├── README.md
├── requirements.txt
├── dataset/                       # All data lives here (see dataset/README.md)
│   ├── meta/                      # Station/link metadata, maps
│   ├── raw/                       # NetCDF (Zenodo) and API-fetched CSVs
│   ├── archived/                  # Downloaded ZIPs
│   └── examples/                  # Example notebooks from Zenodo
└── src/                           # All source code (see src/README.md)
    ├── fetch_data/                # CLI + modules for each data source
    │   ├── main.py
    │   ├── OpenMesh/
    │   ├── noaa_asos/
    │   └── weather_underground/
    └── analysis/                  # End-to-end analysis pipeline
        ├── analysis.ipynb
        ├── pipeline.py
        ├── plotting.py
        └── analysis_functions.py
```

`dataset/raw/` and `dataset/archived/` are populated after fetching and are gitignored. Metadata and examples are tracked.

## Citation

If you use this dataset, please cite both the data and the descriptor paper:

> Jacoby, D. et al. (2025). OpenMesh [Data set]. Zenodo. https://doi.org/10.5281/zenodo.15287692

> Jacoby, D. et al. (2025). OpenMesh: Wireless Signal Dataset for Opportunistic Urban Weather Sensing. *ESSD*. https://doi.org/10.5194/essd-2025-238

<details>
<summary>BibTeX</summary>

```bibtex
@article{jacoby2025openmesh,
  title={OpenMesh: Wireless Signal Dataset for Opportunistic Urban Weather Sensing in New York City},
  author={Jacoby, Dror and Yu, Shuyue and Hu, Qianfei and Hine, Zachary and Johnson, Rob and Ostrometzky, Jonatan and Kadota, Igor and Zussman, Gil and Messer, Hagit},
  journal={Earth System Science Data Discussions},
  volume={2025},
  pages={1--27},
  year={2025},
  publisher={Copernicus Publications},
  doi={10.5194/essd-2025-238}
}
```
</details>

**License:** CC BY 4.0

## Contributing

Branch from `dev`, open PRs back to `dev`.

## Roadmap

- Unified NetCDF format across all sources
- Data QC and cleaning functions
- [OpenSenseAction](https://github.com/OpenSenseAction) algorithm integration (RAINLINK, pypwsqc)
- End-to-end fetch → clean → analyze pipelines

## Contact

- **Issues:** https://github.com/drorjac/OpenMesh/issues
- **ESSD Discussion:** https://essd.copernicus.org/preprints/essd-2025-238/#discussion
- **Affiliations:** Tel Aviv University, Columbia University