# OpenMesh

[ESSD Paper](https://essd.copernicus.org/preprints/essd-2025-238/) | [Zenodo Dataset](https://zenodo.org/records/15287692)

A wireless-link dataset for opportunistic urban weather sensing in New York City, with tools to download, explore, and extend the data.

## About

OpenMesh is an open dataset and analysis framework that turns commercial wireless link (CML) attenuation data from an urban mesh network into rainfall estimates. The dataset covers New York City from October 2023 to July 2024 and is paired with co-located personal weather station (PWS) measurements for validation.

The project demonstrates that commodity network infrastructure can serve as a distributed rainfall sensor — no specialized hardware required.

## Features

- **Ready-to-use dataset** — pre-collected CML and PWS data hosted on Zenodo, downloadable in one command
- **End-to-end pipeline** — fetch, preprocess, and analyze data from a single notebook
- **Multiple data sources** — OpenMesh CML, ASOS airport stations, and Weather Underground PWS
- **Reproducible analysis** — all figures and results from the ESSD paper are reproducible from the provided notebooks
- **Extensible** — bring your own CML or weather data and plug it into the pipeline

## Repository Structure

```
OpenMesh/
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

Pre-collected NYC mesh network data (Oct 2023 - Jul 2024), hosted on Zenodo:

- [OpenMesh](https://zenodo.org/records/15287692): wireless links and PWS sample (13 MB zip, ~330 MB extracted)
- [PWS full](https://zenodo.org/records/17508286): full 8-month PWS dataset

## Citation

If you use this dataset, please cite both the data and the descriptor paper:

> Jacoby, D. et al. (2025). OpenMesh [Data set]. Zenodo. https://doi.org/10.5281/zenodo.15287692

> Jacoby, D. et al. (2025). OpenMesh: Wireless Signal Dataset for Opportunistic Urban Weather Sensing. *ESSD*. https://doi.org/10.5194/essd-2025-238

<details>
<summary>BibTeX</summary>

```bibtex
@article{jacoby2025openmesh,
  title={OpenMesh: Wireless Signal Dataset for Opportunistic Urban Weather Sensing in New York City},
  author={Jacoby, Dror and Yu, Shuyue and Hu, Qianfei and Hine, Zachary and Johnson, Rob and Ostrometzky, Jonatan and Kadota, Igor and Zussman, Gil and Messer, Hagit},
  journal={Earth System Science Data Discussions},
  volume={2025},
  pages={1--27},
  year={2025},
  publisher={Copernicus Publications},
  doi={10.5194/essd-2025-238}
}
```
</details>

**License:** CC BY 4.0

## Contact

- **Issues:** https://github.com/drorjac/OpenMesh/issues
- **ESSD Discussion:** https://essd.copernicus.org/preprints/essd-2025-238/#discussion
- **Affiliations:** Tel Aviv University, Columbia University

## Get Started

**Recommended first run:** After environment setup below, open [`src/analysis/analysis.ipynb`](src/analysis/analysis.ipynb), set `MODE = 'fetch'`, and run all cells. That downloads the default datasets (Zenodo OpenMesh, ASOS/WU per notebook config) and runs the bundled analysis. Most users only need this step plus setup.

Use **Python 3.11** or **3.12** (tested). Pre-release Python (e.g. 3.14) is not recommended for Jupyter—see [DETAILS.md](DETAILS.md#setup). Dependencies are listed in [`requirements.txt`](requirements.txt) (e.g. NumPy, pandas, xarray, matplotlib, netCDF4, Jupyter, tqdm). Optional Weather Underground fetches need `WU_API_KEY`; see DETAILS.md.

```bash
git clone https://github.com/drorjac/OpenMesh.git
cd OpenMesh
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

The tutorial notebook [`src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb`](src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb) is also self-contained: run all cells from the top (through extract) and `load_links()` works without running the CLI separately. See [DETAILS.md](DETAILS.md#notebooks).

For CLI options, other notebooks, and data source details see [DETAILS.md](DETAILS.md).
