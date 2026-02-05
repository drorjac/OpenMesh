# OpenMesh Dataset & Repository

**Status:** Under active development | [ESSD Paper](https://essd.copernicus.org/preprints/essd-2025-238/)

This repository provides:
1. **Dataset access** – Full OpenMesh wireless-link dataset on Zenodo
2. **Download & read tools** – Automated notebook to fetch and explore the dataset
3. **Data fetching tools** – Scripts to retrieve supporting weather observations (ASOS, WU, OpenMesh)
4. **End-to-end analysis** – `src/analysis/analysis.ipynb` lets you **fetch or load** all data (ASOS, WU, CML, PWS) and run **basic analysis** (unified format, plots, CML–PWS matching) from one place
5. **Example code** – Notebooks and scripts for exploration and custom analysis

---

## 1. Dataset on Zenodo

**Full dataset:** https://zenodo.org/records/15287692  
**File:** `OpenMesh.zip` (13 MB compressed, 330 MB extracted)

### Files in Zenodo archive:

**Microwave Links (ML):**
- `ds_openmesh.nc` – OpenSense v1.0 compliant NetCDF with RSL time-series
- `links_metadata.csv` – Link coordinates, frequency, polarization
- `openmesh_dataset_example.ipynb` – Example notebook for exploring CML data

**Personal Weather Stations (PWS):**
- `pws_opensense_sample_jan.nc` – OpenSense v1.0 compliant NetCDF sample (January)
- `pws_metadata.csv` – Station locations and metadata
- `read_pws_sample.ipynb` – Example notebook for PWS data
- `ASOS_stations.csv` – NOAA ASOS station metadata

**Maps & Documentation:**
- `directional_map.html` – Interactive map of link directions
- `frequency_map.html` – Interactive map colored by frequency bands
- `README.txt` – Dataset documentation and variable descriptions (extracts to `dataset/archived/openmesh/extracted/`)

---

## 2. Repository Structure

```
OpenMesh/
├── dataset/                    # All downloaded and fetched data
│   ├── raw/
│   │   ├── openmesh/          # OpenMesh NetCDF files
│   │   └── fetched/           # API-fetched data
│   │       ├── asos/          # NOAA ASOS data
│   │       └── wu/            # Weather Underground data
│   ├── meta/                  # Station metadata (CSVs, maps)
│   │   ├── maps/
│   │   ├── ASOS_stations.csv
│   │   ├── pws_metadata.csv
│   │   └── links_metadata.csv
│   ├── archived/              # Downloaded ZIP files
│   │   └── openmesh/          # OpenMesh.zip, PWS_NYC_WU.zip, extracted/
│   └── examples/              # Example notebooks
│
├── src/                       # Source code
│   ├── fetch_data/            # Data fetching modules (complete)
│   │   ├── OpenMesh/
│   │   ├── noaa_asos/
│   │   ├── weather_underground/
│   │   └── main.py            # CLI interface
│   └── analysis/              # analysis.ipynb: end-to-end fetch/load + basic analysis
│
└── requirements.txt           # Core dependencies
```

**Note:** Large NetCDF files are not in this repo. Download from Zenodo using the notebook or CLI.

---

## 3. Environment Setup

### Create Virtual Environment (Recommended)

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate
```

### Install Dependencies

```bash
# Install all dependencies
pip install -r requirements.txt
```

### Verify Installation

```bash
# Test imports
python -c "import numpy, pandas, xarray, matplotlib; print('All imports successful')"
```

**Note:** The `requirements.txt` includes all dependencies needed for:
- Data processing (numpy, pandas, xarray)
- Visualization (matplotlib)
- Running notebooks

---

## 4. Quick Start

### Option A: Command Line Interface (Recommended)

```bash
# Install dependencies
pip install -r requirements.txt

# Run from project root (recommended):
python src/fetch_data/main.py openmesh
python src/fetch_data/main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-31
python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-31
python src/fetch_data/main.py status

# Or from src/fetch_data/:
cd src/fetch_data && python main.py openmesh
```

**Note:** WU requires an API key. Set `export WU_API_KEY="your_key"` or use `--api-key`. See [API key setup](src/fetch_data/weather_underground/API_KEY_SETUP.md) and [USAGE](src/fetch_data/USAGE.md) for details.

### Option B: Notebook Interface

```bash
# Install dependencies
pip install -r requirements.txt
```

Open the download notebook in your editor: `src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb`. Run all cells to:
- Download OpenMesh.zip from Zenodo
- Extract all files
- Load and visualize the data

### Option C: Manual Download

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Download manually from Zenodo
# Visit: https://zenodo.org/records/15287692
# Download: OpenMesh.zip

# 3. Extract to dataset/archived/openmesh/
unzip OpenMesh.zip -d dataset/archived/openmesh/

# 4. Explore with example notebooks (open in your editor)
# e.g. dataset/examples/openmesh_dataset_example.ipynb
```

**End-to-end workflow (fetch, load, analyze):** Open `src/analysis/analysis.ipynb`. Set **MODE** to `'load'` (from existing files) or `'fetch'` (download if missing); choose PWS source (sample/full); run all cells for unified data, plots, and CML–PWS analysis.

**Pipeline notebooks:** OpenMesh — `src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb`; ASOS — `src/fetch_data/noaa_asos/asos_pipeline.ipynb`; WU — `src/fetch_data/weather_underground/wu_pipeline.ipynb`.

See [src/fetch_data/README.md](src/fetch_data/README.md) and [USAGE](src/fetch_data/USAGE.md) for data fetching and CLI details.

---

## 5. Citation & License

### Citation

If you use this dataset, please cite both the data and the descriptor paper:

**Data:**
> Jacoby, D. et al. (2025). OpenMesh [Data set]. Zenodo. https://doi.org/10.5281/zenodo.15287692

**Paper:**
> Jacoby, D. et al. (2025). OpenMesh: Wireless Signal Dataset for Opportunistic Urban Weather Sensing. *Earth System Science Data Discussions*. https://doi.org/10.5194/essd-2025-238

**BibTeX:**
```bibtex
@article{jacoby2025openmesh,
  title={OpenMesh: Wireless Signal Dataset for Opportunistic Urban Weather Sensing in New York City},
  author={Jacoby, Dror and Yu, Shuyue and Hu, Qianfei and Hine, Zachary and Johnson, Rob and Ostrometzky, Jonatan and Kadota, Igor and Zussman, Gil and Messer, Hagit},
  journal={Earth System Science Data Discussions},
  volume={2025},
  pages={1--27},
  year={2025},
  publisher={Copernicus Publications, G{\"o}ttingen, Germany},
  doi={10.5194/essd-2025-238}
}
```

**License:** CC BY 4.0

---

## 6. Data Sources

- **Microwave Links Data:** NYC Community Mesh Network
- **PWS (Personal Weather Stations) data** can be obtained in three ways:
  - **Sample (Zenodo):** January PWS sample in OpenMesh.zip → `pws_opensense_sample_jan.nc`
  - **Full (Zenodo):** Full PWS dataset (PWS Zenodo) → `pws_wu_os.nc` (~8 months)
  - **API:** Any period via Weather Underground API (hourly data; API key required)
- **ASOS Data:** NOAA Automated Surface Observing System (JFK, LaGuardia, Central Park)

See [src/fetch_data/README.md](src/fetch_data/README.md) for details on each option.


---

## 7. Branches

| Branch | Status | Description |
|--------|--------|-------------|
| `main` | Stable | Current release - data fetching pipelines |
| `dev` | Active | Development branch - upcoming features |

---

## 8. Roadmap

Upcoming in `dev` branch:

- **Unified Data Format** - All sources standardized to NetCDF (xarray-compatible)
- **Cleaning Functions** - Data QC, outlier detection, gap filling, sensor validation
- **OpenSenseAction Integration** - Run [OpenSenseAction](https://github.com/OpenSenseAction) algorithms directly:
  - RAINLINK rainfall estimation
  - CML wet/dry classification
  - PWS quality control (pypwsqc)
- **End-to-End Pipelines** - Fetch → Clean → Process → Analyze in single workflow
- **Applied Examples** - Ready-to-use notebooks for rainfall estimation

---

## Contributing

1. Fork the repo
2. Branch from `dev`:
```bash
   git checkout dev && git checkout -b feature/your-feature
```
3. Commit, push, open PR to `dev`

Ideas: OpenSenseAction algorithms, cleaning functions, new data sources, NetCDF utilities.

---

## Contact

- **Issues:** https://github.com/drorjac/OpenMesh/issues
- **ESSD Discussion:** https://essd.copernicus.org/preprints/essd-2025-238/#discussion
- **Affiliations:** Tel Aviv University, Columbia University