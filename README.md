# OpenMesh

[ESSD Paper](https://doi.org/10.5194/essd-18-5817-2026) | [Zenodo Dataset](https://doi.org/10.5281/zenodo.15287692) | [Code (Zenodo)](https://doi.org/10.5281/zenodo.18510358)

A wireless-link dataset for opportunistic urban weather sensing in New York City, with tools to download, explore, and extend the data.

## About

OpenMesh is a dataset of received signal levels from commercial microwave links (CMLs) in a community mesh network in New York City, with code to download, read and analyse it. The ESSD release covers 2023-10-29 to 2024-07-01, with personal weather station (PWS) data for the same period.

## Contents

- Download tools for the Zenodo records and for ASOS and Weather Underground data
- Example notebooks that read and plot the data
- An analysis notebook that fetches, preprocesses and analyses the data
- Converters from raw data to OpenSense-style netCDF (`src/netCDF_converters/`)

## Repository Structure

```
OpenMesh/
├── tutorials/              # Ordered tutorial path — start here
├── src/
│   ├── analysis/           # Main analysis notebook and pipeline
│   │   └── analysis.ipynb  # Start here for the full pipeline
│   ├── fetch_data/         # Data download utilities and tutorials
│   │   └── OpenMesh/       # OpenMesh-specific download notebook
│   └── README.md
├── dataset/                # Local data storage (populated after download)
├── requirements.txt
├── DETAILS.md              # Extended setup, CLI, and notebook docs
└── README.md
```

## Dataset

| Record | Contents | Licence |
|--------|----------|---------|
| [OpenMesh (ESSD)](https://doi.org/10.5281/zenodo.15287692) | `OpenMesh.zip` (13 MB, ~330 MB extracted): 75 CMLs / 103 sublinks, 2023-10-29 → 2024-07-01, 1 min; a 2-week WU PWS sample (2024-01-15 → 2024-01-30, 37 stations); station lists | CC BY 4.0 |
| [PWS full](https://doi.org/10.5281/zenodo.17508286) | 37 Weather Underground stations for the ESSD period | CC BY-NC 4.0 (WU terms restrict redistribution) |
| [OpenMesh 2.0.0](https://doi.org/10.5281/zenodo.23283445) | 359 CMLs / 732 sublinks (38 CMLs at 57–71 GHz, 6 at 24 GHz, 315 at 5 GHz), 2023-10-29 → 2026-05-31; 5 ASOS, 7 GHCN-Daily stations, 10 MRMS days; no WU or Mesonet. Files are access-restricted for now: request access on Zenodo | CC BY 4.0 |

The code reads either v1 (default) or v2 (Zenodo 2.0.0), switched in one place:
`analysis.datasets.use('v2')`, a `DATASET` knob in the notebooks, or `OPENMESH_DATASET=v2`.
v1 is the set of files under `dataset/raw/` on the authors' machine. Of these, only
`openmesh/ds_openmesh.nc` (and the PWS records) are public; the full-period files under
`raw/full/` are not, so code that needs them will not run on a fresh clone.
See [dataset/README.md](dataset/README.md#choosing-the-dataset-v1-default-or-zenodo-v2).

## Citation

If you use this dataset, please cite both the data and the descriptor paper:

> Jacoby, D. et al. (2025). OpenMesh [Data set]. Zenodo. https://doi.org/10.5281/zenodo.15287692

> Jacoby, D., Yu, S., Hu, Q., Hine, Z., Johnson, R., Ostrometzky, J., Kadota, I., Zussman, G., and Messer, H. (2026). OpenMesh: wireless signal dataset for opportunistic urban weather sensing in New York City. *Earth System Science Data*, 18, 5817–5836. https://doi.org/10.5194/essd-18-5817-2026

<details>
<summary>BibTeX</summary>

```bibtex
@article{jacoby2026openmesh,
  title={OpenMesh: wireless signal dataset for opportunistic urban weather sensing in New York City},
  author={Jacoby, Dror and Yu, Shuyue and Hu, Qianfei and Hine, Zachary and Johnson, Rob and Ostrometzky, Jonatan and Kadota, Igor and Zussman, Gil and Messer, Hagit},
  journal={Earth System Science Data},
  volume={18},
  pages={5817--5836},
  year={2026},
  publisher={Copernicus Publications},
  doi={10.5194/essd-18-5817-2026}
}
```
</details>

## Licences

| Item | Licence |
|------|---------|
| Code in this repository | MIT ([LICENSE](LICENSE)) |
| Code archive v1.1.0 ([Zenodo 18510358](https://doi.org/10.5281/zenodo.18510358)) | CC BY 4.0 (as archived) |
| OpenMesh ESSD data ([Zenodo 15287692](https://doi.org/10.5281/zenodo.15287692)) | CC BY 4.0 |
| PWS full ([Zenodo 17508286](https://doi.org/10.5281/zenodo.17508286)) | CC BY-NC 4.0 |
| OpenMesh 2.0.0 ([Zenodo 23283445](https://doi.org/10.5281/zenodo.23283445)) | CC BY 4.0 |

## Contact

- **Issues:** https://github.com/drorjac/OpenMesh/issues
- **ESSD paper & review history:** https://essd.copernicus.org/articles/18/5817/2026/
- **Affiliations:** Tel Aviv University, Columbia University

## Get Started

**New here?** Follow the ordered [tutorials](tutorials/README.md).

**Recommended first run:** After environment setup below, open [`src/analysis/analysis.ipynb`](src/analysis/analysis.ipynb), set `MODE = 'fetch'`, and run all cells. That downloads the default datasets (Zenodo OpenMesh, ASOS/WU per notebook config) and runs the bundled analysis. Most users only need this step plus setup.

Tested on **Python 3.11** and **3.12**. Dependencies are listed in [`requirements.txt`](requirements.txt) (e.g. NumPy, pandas, xarray, matplotlib, netCDF4, Jupyter, tqdm). Optional Weather Underground fetches need `WU_API_KEY`; see DETAILS.md.

```bash
git clone https://github.com/drorjac/OpenMesh.git
cd OpenMesh
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

The tutorial notebook [`src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb`](src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb) is also self-contained: run all cells from the top (through extract) and `load_links()` works without running the CLI separately. See [DETAILS.md](DETAILS.md#notebooks).

For CLI options, other notebooks, and data source details see [DETAILS.md](DETAILS.md).
