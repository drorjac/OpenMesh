# OpenMesh Dataset & Repository

[ESSD Paper](https://essd.copernicus.org/preprints/essd-2025-238/) | [Zenodo Dataset](https://zenodo.org/records/15287692)

OpenMesh is a wireless-link dataset for opportunistic urban weather sensing in NYC. This repository provides tools to download, explore, and analyze the data.

---

## Dataset

**Zenodo:** https://zenodo.org/records/15287692
**File:** `OpenMesh.zip` (13 MB compressed, ~330 MB extracted)

### Contents

**Microwave Links (ML):**
`ds_openmesh.nc` – OpenSense v1.0 compliant NetCDF with RSL time-series;
`links_metadata.csv` – Link coordinates, frequency, polarization

**Personal Weather Stations (PWS):**
`pws_opensense_sample_jan.nc` – OpenSense v1.0 compliant NetCDF sample (January);
`pws_metadata.csv` – Station locations and metadata

**Maps & Documentation:**
`directional_map.html`, `frequency_map.html` – Interactive link maps;
`ASOS_stations.csv` – NOAA ASOS station metadata;
`README.txt` – Variable descriptions

---

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## Quick Start

### Command Line Interface

```bash
python src/fetch_data/main.py openmesh
python src/fetch_data/main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-31
python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-31
python src/fetch_data/main.py status
```

WU requires an API key. Set `export WU_API_KEY="your_key"` or use `--api-key`. See [API key setup](src/fetch_data/weather_underground/API_KEY_SETUP.md).

### Notebooks

- **Download & explore:** `src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb`
- **ASOS pipeline:** `src/fetch_data/noaa_asos/asos_pipeline.ipynb`
- **WU pipeline:** `src/fetch_data/weather_underground/wu_pipeline.ipynb` (API key required)
- **End-to-end analysis:** `src/analysis/analysis.ipynb` — fetch or load all data (ASOS, WU, CML, PWS), run basic analysis, plots, and CML–PWS matching. Set **MODE** to `'load'` or `'fetch'`.

See [USAGE.md](src/fetch_data/USAGE.md) for detailed CLI and data fetching documentation.

---

## Repository Structure

```
OpenMesh/
├── README.md
├── requirements.txt
├── dataset/
│   ├── DATA_ORGANIZATION.md
│   ├── README.md
│   ├── examples/
│   │   ├── openmesh_dataset_example.ipynb
│   │   └── read_pws_sample.ipynb
│   ├── meta/
│   │   ├── ASOS_stations.csv
│   │   ├── links_metadata.csv
│   │   ├── pws_metadata.csv
│   │   └── maps/
│   │       ├── directional_map.html
│   │       └── frequency_map.html
│   ├── archived/              # Downloaded ZIPs and extracted files
│   └── raw/                   # Downloaded NetCDF and API-fetched data
└── src/
    ├── README.md
    ├── analysis/
    │   ├── analysis.ipynb     # End-to-end fetch/load + analysis
    │   ├── analysis_functions.py
    │   ├── pipeline.py
    │   └── plotting.py
    └── fetch_data/
        ├── USAGE.md
        ├── config.py
        ├── main.py            # CLI interface
        ├── OpenMesh/
        │   ├── download_and_read_openmesh.ipynb
        │   └── openmesh.py
        ├── noaa_asos/
        │   ├── asos_pipeline.ipynb
        │   ├── asos_fetch.py
        │   └── config.py
        └── weather_underground/
            ├── API_KEY_SETUP.md
            ├── wu_pipeline.ipynb
            ├── wu_fetch.py
            └── config.py
```

**Note:** `dataset/archived/` and `dataset/raw/` are populated after running the download notebooks or CLI. Large NetCDF files are not in this repo — download from Zenodo.

---

## Data Sources

- **Microwave Links:** NYC Community Mesh Network
- **PWS:** January sample included in OpenMesh.zip (`pws_opensense_sample_jan.nc`). Full WU PWS dataset (~8 months, `pws_wu_os.nc`) available at https://zenodo.org/uploads/17508286. Any period can be fetched via the WU API (key required) using `src/fetch_data/weather_underground/wu_pipeline.ipynb` or the CLI.
- **ASOS:** NOAA Automated Surface Observing System (JFK, LaGuardia, Central Park)

---

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

---

## Contributing & Contact

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines, branches, and roadmap.

- **Issues:** https://github.com/drorjac/OpenMesh/issues
- **ESSD Discussion:** https://essd.copernicus.org/preprints/essd-2025-238/#discussion