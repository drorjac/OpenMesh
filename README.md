# OpenMesh Dataset & Repository

**Status:** 🚧 Under active development | 📄 [ESSD Paper](https://essd.copernicus.org/preprints/essd-2025-238/)

This repository provides:
1. **Dataset access** – Full OpenMesh wireless-link dataset on Zenodo
2. **Download & read tools** – Automated notebook to fetch and explore the dataset
3. **Data fetching tools** – Scripts to retrieve supporting weather observations
4. **Example code** – Notebooks and scripts for analysis

---

## 1. Dataset on Zenodo

**Full dataset:** https://zenodo.org/records/15287692  
**File:** `OpenMesh.zip` (≈330 MB)

### Files in Zenodo archive:

**Commercial Microwave Links (CML):**
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
├── dataset/                    # Sample data & examples
│   ├── links/                  
│   │   ├── links_metadata.csv
│   │   └── openmesh_dataset_example.ipynb
│   ├── weather stations/       
│   │   ├── ASOS_stations.csv
│   │   ├── pws_metadata.csv
│   │   └── read_pws_sample.ipynb
│   ├── maps/                   
│   │   ├── directional_map.html
│   │   └── frequency_map.html
│   └── README.txt
│
├── src/                        # Data tools & processing
│   ├── datasets/
│   │   ├── download_and_read_openmesh.ipynb  # 📥 Download from Zenodo
│   │   ├── noaa/               # NOAA ASOS weather data
│   │   │   ├── asos_automated/ # Automated NCEI fetcher
│   │   │   └── asos_iem/       # IEM manual download processor
│   │   └── wu/                 # Weather Underground API fetcher
│   └── README.md
│
├── analysis/                   # 🚧 Under development
│   └── (Future analysis scripts)
│
└── requirements.txt            # Core dependencies
```

**Note:** Large NetCDF files are not in this repo. Download from Zenodo using the notebook.

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
# Install all dependencies (includes PyNNcml dependencies)
pip install -r requirements.txt

# Install PyNNcml in editable mode (for development)
cd PyNNcml
pip install -e .
cd ..
```

### Verify Installation

```bash
# Test imports
python -c "import numpy, pandas, xarray, matplotlib; import pynncml; print('✓ All imports successful')"
```

**Note:** The `requirements.txt` includes all dependencies needed for:
- Data processing (numpy, pandas, xarray)
- Visualization (matplotlib)
- PyNNcml (torch, torchvision, and other ML dependencies)
- Jupyter notebooks

---

## 4. Quick Start

### Option A: Download via Notebook (Recommended)
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the download notebook
jupyter notebook src/fetch_data/download_and_read_openmesh.ipynb

# This will:
# - Download OpenMesh.zip from Zenodo
# - Extract all files
# - Load and visualize the data
```

### Option B: Manual Download
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Download manually from Zenodo
# Visit: https://zenodo.org/records/15287692
# Download: OpenMesh.zip

# 3. Extract and explore
unzip OpenMesh.zip
jupyter notebook dataset/links/openmesh_dataset_example.ipynb
```

### Fetch Additional Weather Data
```bash
# NOAA ASOS data (automated)
cd src/fetch_data/noaa/asos_automated
python main.py --start-date 2024-01-01 --end-date 2024-12-31

# Weather Underground data
cd src/fetch_data/wu/fetch_data
python main.py  # Configure API key first
```

See [src/README.md](src/README.md) for detailed data fetching instructions.

---

## 5. Citation & License

### Dataset Citation
```
Jacobson, D. et al. (2025). OpenMesh: Opportunistic Weather Sensing Using 
NYC Community Mesh Network Data [Data set]. Zenodo. 
https://doi.org/10.5281/zenodo.15287692
```

### Paper Citation
```
Jacobson, D. et al. (2025). OpenMesh: Opportunistic Weather Sensing Using 
NYC Community Mesh Network Data. Earth System Science Data Discussions. 
https://doi.org/10.5194/essd-2025-238
```

**License:** CC BY 4.0

---

## 6. Data Sources

- **CML Data:** NYC Community Mesh Network
- **PWS Data:** Weather Underground Personal Weather Stations  
- **ASOS Data:** NOAA Automated Surface Observing System (JFK, LaGuardia, Central Park)

---

## 7. Contact & Contributing

- **Issues:** https://github.com/drorjac/OpenMesh/issues
- **ESSD Discussion:** https://essd.copernicus.org/preprints/essd-2025-238/#discussion
- **Affiliations:** Tel Aviv University, Columbia University

For questions about data fetching or processing, see module-specific READMEs in `src/datasets/`.
