# OpenMesh Dataset

Download and load the OpenMesh NYC Mesh Network dataset (and PWS WU subset) from Zenodo.

## Contents

| File | Role |
|------|------|
| `openmesh.py` | Download, extract, and load functions |
| `download_and_read_openmesh.ipynb` | Step-by-step download, extract, load, and plot |

## Data sources

- **OpenMesh (main):** Zenodo [15287692](https://zenodo.org/records/15287692) → `OpenMesh.zip`  
  CML + PWS sample + metadata. Extracts to `dataset/raw/openmesh/`, `dataset/meta/`, `dataset/examples/`, `dataset/meta/maps/`; README.txt and other unclassified files → `dataset/archived/openmesh/extracted/`. With `organize=False`, all files go to `dataset/archived/openmesh/extracted/`.
- **PWS WU (full):** Zenodo [17508286](https://zenodo.org/records/17508286) → `PWS_NYC_WU.zip`  
  Full PWS time series. Extracts to `dataset/raw/openmesh/pws_wu_os.nc`.

## Quick start

**CLI (from project root):**
```bash
python src/fetch_data/main.py openmesh
```

**Notebook:** Open `download_and_read_openmesh.ipynb`, run the download/extract cells (e.g. 4–5).

**Python:**
```python
from src.fetch_data.OpenMesh.openmesh import run_openmesh_pipeline, run_pws_wu_pipeline, load_pws, load_links

run_openmesh_pipeline()   # Download + extract OpenMesh.zip
run_pws_wu_pipeline()    # Download + extract PWS_NYC_WU.zip → pws_wu_os.nc

# Load data
pws = load_pws(sample=True)   # pws_opensense_sample_jan.nc
pws = load_pws(sample=False)  # pws_wu_os.nc
links_ds = load_links()
```

## Output locations

- Archives: `dataset/archived/openmesh/` (OpenMesh.zip, optionally PWS_NYC_WU.zip)
- Extracted (docs / as-is): `dataset/archived/openmesh/extracted/` (README.txt and other when `organize=True`; full ZIP contents when `organize=False`)
- Raw NetCDF: `dataset/raw/openmesh/` (`*.nc`)
- Metadata: `dataset/meta/*.csv`, `dataset/meta/maps/*.html`
- Examples: `dataset/examples/*.ipynb`

See parent [../README.md](../README.md) for full fetch_data layout and CLI.
