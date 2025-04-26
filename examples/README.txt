# OpenMesh Dataset

The **OpenMesh** project provides a comprehensive dataset of commercial microwave link (CML) measurements and supporting metadata for opportunistic urban rainfall sensing in New York City. This repository contains:

- `links_rawdata.csv`\
  Cleaned RSL time series in wide‐format CSV. Rows are UTC timestamps; columns (1…N) are sublink IDs the Received Signal Level (dBm).

- `links_metadata.csv`\
  Cleaned metadata CSV. Each row corresponds to one `sublink_id` and includes:

  - `site_0_lat`, `site_0_lon` (WGS84 °)
  - `site_1_lat`, `site_1_lon` (WGS84 °)
  - `length` (m)
  - `frequency` (MHz)
  - `polarization` (string)

- `OpenMesh.nc`\
  NetCDF file compliant with the OpenSense CML spec v1.1:

  - **Dimensions**: `time` (epoch seconds since 1970-01-01 UTC), `sublink_id` (1…N)
  - **Coords**: all metadata variables + `time_utc` decoding to `datetime64[ns]`
  - **Data var**: `rsl` (float32, dBm)

- `example_read_cml_nc.ipynb`\
  Interactive Jupyter notebook demonstrating how to load, explore, and visualize `OpenMesh.nc` with xarray and matplotlib.

- `example_read_cml_nc.py`\
  Plain‐script equivalent for the notebook; runs end‐to‐end plots and summaries in a terminal or script environment.

- `read_OpenMesh_nc.py`\
  Minimal example script to read `OpenMesh.nc`, print global attributes, plot frequency and length distributions, and show a sample link time series with baseline subtraction.

- `README.md`\
  This file: overview of contents, file descriptions, and usage instructions.

---

## Quickstart

1. **Clone the repository** or download the Zenodo archive:

   ```bash
   git clone https://github.com/drorjac/OpenMesh.git
   cd OpenMesh
   ```

2. **Install dependencies** (Python ≥3.8):

   ```bash
   pip install xarray matplotlib
   ```

3. **Run the example** notebook:

   ```bash
   jupyter notebook example_read_cml_nc.ipynb
   ```

   Or execute the script:

   ```bash
   python example_read_cml_nc.py
   ```

4. **Inspect the NetCDF** directly with xarray in your own code:

   ```python
   import xarray as xr
   ds = xr.open_dataset('OpenMesh.nc')
   ds
   ```

---

## Reproducibility & Further Analysis

All data cleaning, conversion code, and downstream analysis scripts live in the [OpenMesh GitHub](https://github.com/drorjac/OpenMesh). You can reproduce the full pipeline:

- Start from raw CSVs in `raw/`
- Run `convert_to_netcdf.ipynb` to generate `OpenMesh.nc`
- Explore with the provided examples

Pull requests and issues are welcome!

---

## Citation & License

- **License**: CC BY 4.0 ([https://creativecommons.org/licenses/by/4.0/](https://creativecommons.org/licenses/by/4.0/))
- **Zenodo DOI**: [https://doi.org/10.5281/zenodo.XXXXXXX](https://doi.org/10.5281/zenodo.XXXXXXX)
- **GitHub**: [https://github.com/drorjac/OpenMesh](https://github.com/drorjac/OpenMesh)

Please cite as:\
*Jacoby, D.* (2025). *OpenMesh: Wireless Signal Dataset for Opportunistic Urban Weather Sensing in New York City* [Data set]. Zenodo. [https://doi.org/10.5281/zenodo.XXXXXXX](https://doi.org/10.5281/zenodo.XXXXXXX)

