# Environment Setup

## Quick Start (5 min)

Choose one option below.

### Option 1: Conda (Recommended)

Guaranteed to work with all features (radar, MRMS, KOKX).

```bash
git clone https://github.com/drorjac/OpenMesh.git
cd OpenMesh
conda env create -f environment.yml
conda activate openmesh
```

Verify:
```bash
python -c "import metpy, xarray, eccodes; print('✓ Ready')"
```

### Option 2: pip + venv

Simpler but may have issues with C extensions (pyarrow, eccodes).

```bash
git clone https://github.com/drorjac/OpenMesh.git
cd OpenMesh
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Verify:
```bash
python -c "import xarray, pandas; print('✓ Ready')"
```

**Note:** If radar fetching fails with "No module named 'pyarrow'", use conda instead.

## What's Installed

| Component | Purpose | Install |
|-----------|---------|---------|
| **Core** | numpy, pandas, xarray, scipy | Both |
| **Visualization** | matplotlib, folium | Both |
| **NetCDF** | netCDF4 | Both |
| **MRMS Radar** | eccodes (GRIB2 decoding) | Both |
| **KOKX NEXRAD** | metpy (Level III decoding) | Both |
| **Parquet** | pyarrow (caching) | Both |
| **Jupyter** | jupyter, ipykernel | Both |
| **Testing** | pytest | Both |

## Next Steps

1. **First time?** Start with [tutorials/README.md](tutorials/README.md)
2. **Just fetch data?** See [FETCHING.md](FETCHING.md)
3. **Full analysis?** Open [`tutorials/analysis.ipynb`](tutorials/analysis.ipynb)

## Troubleshooting

**"No module named X"**
- Conda install: `conda install -c conda-forge X`
- pip install: `pip install X`

**Jupyter kernel issues**
- Restart kernel: **Kernel → Restart Kernel**
- Check kernel: **Kernel → Change kernel** (select openmesh)

**Radar fetch fails**
- Use conda (better for C extensions)
- Check internet connection
- Data may not exist for your date

**Still stuck?** See [DETAILS.md](DETAILS.md#troubleshooting)
