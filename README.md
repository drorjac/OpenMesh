# OpenMesh Dataset & Repository

**Status:** Under active development | [ESSD Paper](https://essd.copernicus.org/preprints/essd-2025-238/)

This repository provides:
1. **Dataset access** – Full OpenMesh wireless-link dataset on Zenodo
2. **Download & read tools** – Automated notebook to fetch and explore the dataset
3. **Data fetching tools** – Scripts to retrieve supporting weather observations
4. **Example code** – Notebooks and scripts for analysis

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
- `README.txt` – Dataset documentation and variable descriptions

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
│   ├── meta/                  # Station metadata (meta/ or meta/openmesh/)
│   │   ├── openmesh/          # OpenMesh links, ASOS, PWS (duplicates ok)
│   │   ├── maps/
│   │   ├── ASOS_stations.csv
│   │   └── pws_metadata.csv
│   ├── archived/              # Downloaded ZIP files
│   └── examples/              # Example notebooks
│
├── src/                       # Source code
│   ├── fetch_data/            # Data fetching modules (complete)
│   │   ├── OpenMesh/
│   │   ├── noaa_asos/
│   │   ├── weather_underground/
│   │   └── main.py            # CLI interface
│   └── analysis/              # Analysis tools (in development)
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
- Jupyter notebooks

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

# Run the download notebook
jupyter notebook src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb

# This will:
# - Download OpenMesh.zip from Zenodo
# - Extract all files
# - Load and visualize the data
```

### Option C: Manual Download

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Download manually from Zenodo
# Visit: https://zenodo.org/records/15287692
# Download: OpenMesh.zip

# 3. Extract to dataset/archived/openmesh/
unzip OpenMesh.zip -d dataset/archived/openmesh/

# 4. Explore with example notebooks
jupyter notebook dataset/examples/openmesh_dataset_example.ipynb
```

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
- **PWS Data:** Weather Underground Personal Weather Stations  
- **ASOS Data:** NOAA Automated Surface Observing System (JFK, LaGuardia, Central Park)

---

## 7. Contact & Contributing

- **Issues:** https://github.com/drorjac/OpenMesh/issues
- **ESSD Discussion:** https://essd.copernicus.org/preprints/essd-2025-238/#discussion
- **Affiliations:** Tel Aviv University, Columbia University

For questions about data fetching or processing, see module-specific READMEs in `src/fetch_data/`.