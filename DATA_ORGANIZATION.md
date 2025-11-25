# Data Organization

## Standard Data Location

**All downloaded and processed data files should be stored in:**
```
src/data/
```

This is the **unique, standard location** for all data files.

## Directory Structure

```
OpenMesh-fresh/
├── dataset/                    # Example files and metadata only (small files)
│   ├── links/
│   │   ├── links_metadata.csv
│   │   └── openmesh_dataset_example.ipynb
│   ├── maps/
│   └── weather stations/
│
└── src/
    └── data/                  # ⭐ STANDARD DATA LOCATION
        ├── openmesh/          # OpenMesh CML dataset
        │   ├── OpenMesh.zip
        │   └── extracted/
        │       └── dataset/
        │           ├── links/
        │           │   ├── ds_openmesh.nc      # Large NetCDF file
        │           │   └── links_metadata.csv
        │           ├── weather stations/
        │           └── maps/
        ├── openmrg/           # OpenMRG dataset (optional)
        ├── noaa_asos/         # NOAA ASOS weather data
        └── wu_pws/            # Weather Underground PWS data
```

## Usage in Notebooks

### From `src/analysis/` notebooks:
```python
from pathlib import Path
BASE_DATA_DIR = Path("../../src/data")
OPENMESH_DATA_DIR = BASE_DATA_DIR / "openmesh"
```

### From `src/fetch_data/` notebooks:
```python
from pathlib import Path
DOWNLOAD_DIR = Path("../../src/data/openmesh")
```

## Key Points

1. **`src/data/`** - Standard location for all data (gitignored)
2. **`dataset/`** - Only example files, metadata, and small files (tracked in git)
3. **No duplicates** - All data goes to `src/data/` only
4. **Functions** - Use extraction functions from `src/fetch_data/`

## Migration

If you have data in the root `data/` folder, you can:
1. Move it to `src/data/` 
2. Or delete it (it will be re-downloaded to the correct location)

## Functions

Download and extraction functions are located in:
- `src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb` - OpenMesh download/extract
- `PyNNcml/pynncml/datasets/loaders.py` - PyNNcml download functions

All notebooks should use these existing functions rather than reimplementing them.


