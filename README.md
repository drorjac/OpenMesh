# OpenMesh Dataset & Repository
Status: 🚧 Under active development

This project offers **(i)** a lightweight code sample for exploring the OpenMesh *wireless‑link signal‑level* dataset and **(ii)** direct links to the **full dataset** hosted on Zenodo.

---
## 1  Dataset on Zenodo
Full‑resolution data (hundreds of MB) are available at:
<https://zenodo.org/records/15268341>

### Files included in the Zenodo archive
- **`links_rawdata.csv`** – wide‑format received‑signal‑level (RSL) time‑series; each column is a `sublink_id`, each row a UTC timestamp (values in dBm).
- **`links_metadata.csv`** – per‑link metadata: coordinates, link length (m), carrier frequency (MHz), and polarisation.
- **`OpenMesh.nc`** – NetCDF bundle compliant with the OpenSense wireless‑link spec v1.1.  
  • Dimensions `time`, `sublink_id`  
  • Coordinates (all metadata + `time_utc`)  
  • Data var `rsl` (float32, dBm)

---
## 2  Repository structure (this Git repo)
A trimmed sample and helper code are provided so you can experiment without downloading the full archive.

```
OpenMesh/
├─ dataset/
│  └─ sample_OpenMesh.nc        #  ≈5 MB excerpt of the full NetCDF
├─ examples/
│  └─ read_OpenMesh_nc.py       #  Demo: load NetCDF, plot, map, etc.
├─ requirements.txt             #  xarray, netCDF4, matplotlib, numpy
└─ README.md                    #  you are here
```

---
## Quick Start
```bash
# 1 Create / activate an environment
conda create -n openmesh python=3.11   # or: python -m venv .venv
conda activate openmesh                # or: source .venv/bin/activate

# 2 Install dependencies
pip install -r requirements.txt        # xarray, netCDF4, matplotlib, numpy

# 3 Run the demo script
python examples/read_OpenMesh_nc.py
```
git add -A          # adds updates, new files, and deletions

---
## Citation & Licence
- **Licence** – CC BY 4.0  
- **Zenodo DOI** – <https://doi.org/10.5281/zenodo.15268341>  
- **Repository** – <https://github.com/drorjac/OpenMesh>

