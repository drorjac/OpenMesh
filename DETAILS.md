# OpenMesh: Details

Full reference for data sources, setup, CLI, notebooks, and repository structure.

## Dataset files

The code reads two datasets: **v1** (default), the ESSD record = the two Zenodo records
below plus ASOS fetched from the IEM API, and **v2**, OpenMesh 2.0.0. Switch with
`analysis.datasets.use('v2')`, `OPENMESH_DATASET=v2`, a notebook's `DATASET` knob or
`--dataset v2`.

### v1: OpenMesh (wireless links + PWS sample)

**Zenodo:** [15287692](https://zenodo.org/records/15287692) — `OpenMesh.zip` (13 MB compressed, ~330 MB extracted), CC BY 4.0

| File | Description |
|------|-------------|
| `ds_openmesh.nc` | Microwave link RSL time series, 75 CMLs / 103 sublinks, 2023-10-29 → 2024-07-01, 1 min (OpenSense v1.0 NetCDF) |
| `pws_opensense_sample_jan.nc` | WU PWS sample, 37 stations, 2024-01-15 → 2024-01-30 |
| `links_metadata.csv` | Link coordinates, frequency, polarization |
| `pws_metadata.csv` | PWS station locations and metadata |
| `ASOS_stations.csv` | NOAA ASOS station list (13 stations) |
| `directional_map.html`, `frequency_map.html` | Interactive link maps |

### v1: PWS full time series

**Zenodo:** [17508286](https://zenodo.org/records/17508286) — `PWS_NYC_WU.zip`, CC BY-NC 4.0 (WU terms restrict redistribution)

37 Weather Underground stations for 2023-10-29 → 2024-07-01, extracted as `pws_wu_os.nc`.

### v2: OpenMesh 2.0.0

**Zenodo:** [23283445](https://doi.org/10.5281/zenodo.23283445), CC BY 4.0. 359 CMLs / 732 sublinks, 2023-10-29 → 2026-05-31, with 5 ASOS, 7 GHCN-Daily stations and 10 MRMS days. Download `openmesh-2.0.0.zip` from the record and unpack it with `analysis.datasets.install_v2`. See [dataset/README.md](dataset/README.md#choosing-the-dataset-v1-default-or-v2).

## Additional data sources (fetch any period)

Beyond the fixed Zenodo dataset, the repository includes tools to fetch weather data for any date range via APIs.

### NOAA ASOS (no API key)

1-minute airport weather data (temperature, wind, precipitation, pressure) from stations like JFK, LGA, and Central Park. Available back to 2000 via Iowa Environmental Mesonet. Data is delayed 18-36 hours.

### Weather Underground (API key required)

Hourly data from personal weather stations. Covers any period and any WU station. Get a free API key at [wunderground.com](https://www.wunderground.com/member/api-keys) — you'll need to register a virtual PWS to unlock API access. See [API_KEY_SETUP.md](src/fetch_data/weather_underground/API_KEY_SETUP.md) for details.

### PWS data: three options

| Option | Source | Period | API key |
|--------|--------|--------|---------|
| Sample | OpenMesh Zenodo | 2024-01-15 → 2024-01-30 | No |
| Full | PWS Zenodo | 2023-10-29 → 2024-07-01 | No |
| API | Weather Underground | Any period | Yes |

## Setup

**Python:** tested on **3.11** and **3.12**.

```bash
git clone https://github.com/drorjac/OpenMesh.git
cd OpenMesh
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

For WU data, also set your API key:
```bash
export WU_API_KEY="your_key"
```

## CLI

```bash
python src/fetch_data/main.py openmesh                                                  # Download dataset from Zenodo
python src/fetch_data/main.py asos -s JFK LGA NYC --start 2024-01-01 --end 2024-01-31  # Fetch ASOS data
python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-31   # Fetch WU data
python src/fetch_data/main.py status                                                    # Check what's downloaded
python src/fetch_data/main.py all                                                       # Run all pipelines
```

See [USAGE.md](src/fetch_data/USAGE.md) for the full CLI reference.

## Notebooks

**OpenMesh download notebook:** `src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb` runs download plus `extract_openmesh(organize=True)`, which places NetCDF under `dataset/raw/openmesh/` and CSV metadata under `dataset/meta/`. You do **not** need to run `python src/fetch_data/main.py openmesh` first; run the notebook cells in order through extract, then `load_links()` will find `ds_openmesh.nc`. (Using `organize=False` only extracts into `archived/.../extracted/` and will **not** satisfy `load_links()`.)

| Notebook | Purpose |
|----------|---------|
| `src/analysis/analysis.ipynb` | End-to-end analysis (recommended starting point) |
| `src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb` | Download and explore Zenodo (self-contained for `dataset/raw/openmesh/` when extract uses default organization) |
| `dataset/examples/openmesh_dataset_example.ipynb` | Explore wireless links |
| `dataset/examples/read_pws_sample.ipynb` | Read PWS sample NetCDF |
| `src/fetch_data/noaa_asos/asos_pipeline.ipynb` | Fetch and visualize ASOS data |
| `src/fetch_data/weather_underground/wu_pipeline.ipynb` | Fetch WU data (API key required) |
| `src/fetch_data/mrms/mrms_pipeline.ipynb` | Fetch and inspect MRMS radar for NYC (no key) |
| `tutorials/radar.ipynb` | MRMS radar for one event: radar fields, radar vs. gauges / PWS / CML, IDW rain maps vs. radar (public data by default; see `tutorials/README.md`) |
| `tutorials/asos_gauge_melt_qc.ipynb` | ASOS heated-gauge snowmelt QC (see `tutorials/README.md` for the full reading order) |

## netCDF converters

All raw-data → netCDF converters (CML raw and OpenSense, WU PWS, ASOS grouped and flat,
Mesonet, NOAA daily, merges) are in `src/netCDF_converters/`; see its
[README](src/netCDF_converters/README.md) for inputs, outputs and which file each produced.

## Repository structure

```
OpenMesh/
├── README.md
├── DETAILS.md
├── requirements.txt
├── dataset/                       # All data lives here (see dataset/README.md)
│   ├── meta/                      # Station/link metadata, maps
│   ├── raw/                       # NetCDF (Zenodo) and API-fetched CSVs
│   ├── archived/                  # Downloaded ZIPs
│   ├── examples/                  # Example notebooks (read and plot the data)
│   └── formats/                   # netCDF format docs and OpenSense examples
└── src/                           # All source code (see src/README.md)
    ├── fetch_data/                # CLI + modules for each data source
    │   ├── main.py
    │   ├── OpenMesh/
    │   ├── noaa_asos/
    │   └── weather_underground/
    └── analysis/                  # End-to-end analysis pipeline
        ├── analysis.ipynb
        ├── pipeline.py
        ├── plotting.py
        └── analysis_functions.py
```

`dataset/raw/` and `dataset/archived/` are populated after fetching and are gitignored. Metadata and examples are tracked.

## Contributing

Branch from `dev`, open PRs back to `dev`.

## Roadmap

- Unified NetCDF format across all sources
- Data QC and cleaning functions
- [OpenSenseAction](https://github.com/OpenSenseAction) algorithm integration (RAINLINK, pypwsqc)
- End-to-end fetch, clean, and analyze pipelines
