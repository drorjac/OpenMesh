# OpenMesh

[ESSD Paper](https://doi.org/10.5194/essd-18-5817-2026) | [Dataset v1 (Zenodo)](https://doi.org/10.5281/zenodo.15287692) | [Dataset v2 (Zenodo)](https://doi.org/10.5281/zenodo.23283445) | [Code (Zenodo)](https://doi.org/10.5281/zenodo.18510358)

A wireless-link dataset for opportunistic urban weather sensing in New York City, with tools to download, explore, and extend the data.

## About

OpenMesh is a dataset of received signal levels from commercial microwave links (CMLs) in a community mesh network in New York City, with code to download, read and analyse it. This repository serves two public datasets:

- **v1, the ESSD record** ([10.5281/zenodo.15287692](https://doi.org/10.5281/zenodo.15287692)): 75 CMLs / 103 sublinks, 2023-10-29 to 2024-07-01, with personal weather station (PWS) data for the same period. Described in the [ESSD paper](https://doi.org/10.5194/essd-18-5817-2026).
- **v2, OpenMesh 2.0.0** ([10.5281/zenodo.23283445](https://doi.org/10.5281/zenodo.23283445)): 378 CMLs / 772 sublinks, 2023-10-29 to 2026-11-01, with ASOS, GHCN-Daily and radar reference data. Notebooks in [`tutorials/v2/`](tutorials/v2/).

The code reads v1 by default; see [Datasets](#datasets) to switch.

## Contents

- Download tools for the Zenodo records and for ASOS and Weather Underground data
- Example notebooks that read and plot the data
- An analysis notebook that fetches, preprocesses and analyses the data
- Converters from raw data to OpenSense-style netCDF (`src/netCDF_converters/`)

## Repository Structure

```
OpenMesh/
├── tutorials/              # Tutorials — start here (radar.ipynb: radar next to every sensor)
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

| | **v1** (default): the ESSD record | **v2**: OpenMesh 2.0.0 |
|---|---|---|
| Zenodo | CML: [10.5281/zenodo.15287692](https://doi.org/10.5281/zenodo.15287692) (`OpenMesh.zip`, 13 MB) · WU PWS: [10.5281/zenodo.17508286](https://doi.org/10.5281/zenodo.17508286) (`PWS_NYC_WU.zip`) | [10.5281/zenodo.23283445](https://doi.org/10.5281/zenodo.23283445) (`openmesh-2.0.0.zip`) |
| Contents | 75 CMLs / 103 sublinks, 1 min; 37 Weather Underground PWS (a 2-week sample is in `OpenMesh.zip`); ASOS 1-min data fetched from the public IEM API for the window you need | 378 CMLs / 772 sublinks (40 at 58–69 GHz, 6 at 24 GHz, 332 at 5 GHz); 5 ASOS, 7 GHCN-Daily stations, 10 radar days (MRMS and KOKX); no WU PWS or Mesonet |
| Period | 2023-10-29 → 2024-07-01 | 2023-10-29 → 2026-11-01 |
| Licence | CML: CC BY 4.0 · PWS: CC BY-NC 4.0 (WU terms restrict redistribution) | CC BY 4.0 |
| How to get it | [`download_and_read_openmesh.ipynb`](src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb), `python src/fetch_data/main.py openmesh` (`openmesh.py`), or automatically in [`tutorials/radar.ipynb`](tutorials/radar.ipynb) | automatically on first use: `D.ensure('v2')` (called by the v2 notebooks and `tutorials/radar.ipynb`) downloads `openmesh-2.0.0.zip` (~600 MB, resumable, md5-checked) and unpacks it; or `D.install_v2('<zip>')` for a zip you already have |
| Folder | `dataset/raw/openmesh/` (or `OPENMESH_V1_DIR`) | `dataset/raw/openmesh_v2/` (or `OPENMESH_V2_DIR`) |

**Choosing.** Every loader follows one setting (`from analysis import datasets as D`):
`D.use('v2')` in a session, `OPENMESH_DATASET=v2` in the environment, the `DATASET` knob
in a notebook's setup cell, or `--dataset v2` for scripts such as
`src/analysis/cml_baseline.py`. Without any of these the code reads v1.
cml_ids are not shared between the two (v1 `'6'` and v2 `'6'` are different paths).
See [dataset/README.md](dataset/README.md#choosing-the-dataset-v1-default-or-v2).

## Citation

If you use the data, please cite the dataset version you used and the descriptor paper:

> v1: Jacoby, D. et al. (2025). OpenMesh [Data set]. Zenodo. https://doi.org/10.5281/zenodo.15287692

> v2: Jacoby, D., Yu, S., Cao, C., Johnson, R., Morf, O., Hermstein, K., Ostrometzky, J., Messer, H., and Zussman, G. (2026). OpenMesh: A Continuously Updated Wireless Signal Dataset for Opportunistic Weather Sensing in New York City (2.0.0) [Data set]. Zenodo. https://doi.org/10.5281/zenodo.23283445

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

## Fetchable Datasets

Beyond the OpenMesh records, the code fetches these public datasets for any window:

| Dataset | Source | Resolution | Coverage | How to fetch |
|---------|--------|-----------|----------|--------------|
| **MRMS radar** | NOAA (AWS open data) | 0.01°, 1 h / 15 min / 2 min | CONUS, cropped to NYC; 2020-10 → present (IEM archive before) | `src/fetch_data/mrms`; `python src/fetch_data/radar_events.py fetch mrms` |
| **KOKX NEXRAD** | NOAA Level-3 (AWS open data) | 0.25 km gates, ~5–10 min | Upton, NY radar, sampled over NYC | `src/fetch_data/nexrad`; `python src/fetch_data/radar_events.py fetch kokx` |
| **ASOS** | Iowa Environmental Mesonet API | 1 min | 5 NYC stations (any ASOS station) | `src/fetch_data/noaa_asos`; `analysis.datasets.fetch_v1_asos` |
| **GHCN daily** | NOAA NCEI | daily | 7 NYC stations (any GHCN station) | `src/fetch_data/noaa_daily`; `analysis.datasets.fetch_v1_ghcn` (in the v2 record) |
| **Weather Underground PWS** | WU API* | 5–15 min | any WU station | `src/fetch_data/weather_underground` |

*Requires an API key; see [DETAILS.md](DETAILS.md#weather-underground)

See **[FETCHING.md](FETCHING.md)** for radar products, domains and usage.

## Getting Started

### 1. Environment Setup (5 min)

See **[SETUP.md](SETUP.md)** for conda or pip installation.

### 2. Choose Your Path

**Path A: Just fetch data** (15 min)
- See **[FETCHING.md](FETCHING.md)** for MRMS/KOKX/ASOS examples
- Run: `python src/fetch_data/radar_events.py fetch mrms --day 2024-01-19`

**Path B: Tutorials** (1–2 hours)
- See **[tutorials/README.md](tutorials/README.md)**
- [`tutorials/radar.ipynb`](tutorials/radar.ipynb): MRMS and KOKX radar next to CML, ASOS, PWS and GHCN, for one event and all rain events (v1 or v2)
- [`tutorials/v2/`](tutorials/v2/): the v2 record's own notebooks (quickstart, data overview, analysis)

**Path C: Full analysis** (2–3 hours)
- Open [`src/analysis/analysis.ipynb`](src/analysis/analysis.ipynb), set `MODE = 'fetch'`, run all
- Downloads v1 data (Zenodo) and runs the complete pipeline

### Details

- Tested on **Python 3.11 and 3.12**
- Optional: Weather Underground API key; see [DETAILS.md](DETAILS.md#weather-underground)
- For advanced config and CLI options, see [DETAILS.md](DETAILS.md)
