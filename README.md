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

## Datasets

The code reads one of two public datasets. **v1 is the default.**

> **Note:** v2 (OpenMesh 2.0.0) will be available on Zenodo soon. Until then, use v1.

| | **v1** (default): the ESSD record | **v2**: OpenMesh 2.0.0 |
|---|---|---|
| Zenodo | CML: [10.5281/zenodo.15287692](https://doi.org/10.5281/zenodo.15287692) (`OpenMesh.zip`, 13 MB) · WU PWS: [10.5281/zenodo.17508286](https://doi.org/10.5281/zenodo.17508286) (`PWS_NYC_WU.zip`) | [10.5281/zenodo.23283445](https://doi.org/10.5281/zenodo.23283445) (`openmesh-2.0.0.zip`) |
| Contents | 75 CMLs / 103 sublinks, 1 min; 37 Weather Underground PWS (a 2-week sample is in `OpenMesh.zip`); ASOS 1-min data fetched from the public IEM API for the window you need | 359 CMLs / 732 sublinks (38 at 57–71 GHz, 6 at 24 GHz, 315 at 5 GHz); 5 ASOS, 7 GHCN-Daily stations, 10 MRMS days; no WU PWS or Mesonet |
| Period | 2023-10-29 → 2024-07-01 | 2023-10-29 → 2026-05-31 |
| Licence | CML: CC BY 4.0 · PWS: CC BY-NC 4.0 (WU terms restrict redistribution) | CC BY 4.0 |
| How to get it | [`download_and_read_openmesh.ipynb`](src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb), `python src/fetch_data/main.py openmesh` (`openmesh.py`), or automatically in [`tutorials/radar.ipynb`](tutorials/radar.ipynb) | download `openmesh-2.0.0.zip` from the record, then `D.install_v2('<path>/openmesh-2.0.0.zip')` once |
| Folder | `dataset/raw/openmesh/` (or `OPENMESH_V1_DIR`) | `dataset/raw/openmesh_v2/` (or `OPENMESH_V2_DIR`) |

**Choosing.** Every loader follows one setting (`from analysis import datasets as D`):
`D.use('v2')` in a session, `OPENMESH_DATASET=v2` in the environment, the `DATASET` knob
in a notebook's setup cell, or `--dataset v2` for scripts such as
`src/analysis/cml_baseline.py`. Without any of these the code reads v1.
cml_ids are not shared between the two (v1 `'6'` and v2 `'6'` are different paths).
See [dataset/README.md](dataset/README.md#choosing-the-dataset-v1-default-or-v2).

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
| v1: OpenMesh ESSD data ([Zenodo 15287692](https://doi.org/10.5281/zenodo.15287692)) | CC BY 4.0 |
| v1: WU PWS ([Zenodo 17508286](https://doi.org/10.5281/zenodo.17508286)) | CC BY-NC 4.0 |
| v2: OpenMesh 2.0.0 ([Zenodo 23283445](https://doi.org/10.5281/zenodo.23283445)) | CC BY 4.0 |

## Contact

- **Issues:** https://github.com/drorjac/OpenMesh/issues
- **ESSD paper & review history:** https://essd.copernicus.org/articles/18/5817/2026/
- **Affiliations:** Tel Aviv University, Columbia University

## Get Started

**New here?** Follow the ordered [tutorials](tutorials/README.md).

**Recommended first run:** After environment setup below, open [`src/analysis/analysis.ipynb`](src/analysis/analysis.ipynb), set `MODE = 'fetch'`, and run all cells. That downloads the v1 files (Zenodo OpenMesh, ASOS/WU per notebook config) and runs the bundled analysis. Most users only need this step plus setup.

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
