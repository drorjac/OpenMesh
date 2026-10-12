# Tutorials

A suggested reading order for new users. Set up the environment first — see the
main [README](../README.md#get-started). Not every notebook runs on public data: the
**Data** column says what each one needs, and each notebook repeats it in a
"Data needed" note at the top.

**Data sources**

| source | access | fetched / read by |
|---|---|---|
| OpenMesh ESSD archive, [Zenodo 15287692](https://doi.org/10.5281/zenodo.15287692): 75 CMLs, 2023-10-29 → 2024-07-01, plus a 2-week WU PWS sample | public, CC BY 4.0 | `src/fetch_data/OpenMesh/` |
| WU PWS, [Zenodo 17508286](https://doi.org/10.5281/zenodo.17508286): 37 stations, ESSD period | public, CC BY-NC 4.0 | `src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb` |
| ASOS 1-minute (IEM API, no key) | public | `src/fetch_data/noaa_asos/` |
| NOAA MRMS radar (AWS open data, IEM mirror) | public | `src/fetch_data/mrms/` |
| OpenMesh 2.0.0, [Zenodo 23283445](https://doi.org/10.5281/zenodo.23283445): 359 CMLs to 2026-05-31, 5 ASOS, 7 GHCN daily, 10 MRMS days | public (Zenodo) | `analysis.datasets` with `DATASET = 'v2'` |
| Full-period study files in `dataset/raw/full/outputs/` (ASOS, WU PWS, NY Mesonet, GHCN daily, CML attenuation baselines) | local to the repository owner, not published | `analysis.datasets` with `DATASET = 'v1'` |

| # | Notebook | What it shows | Data | Time |
|---|----------|---------------|------|------|
| 1 | [`download_and_read_openmesh.ipynb`](../src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb) | Download the OpenMesh archive from Zenodo and load links | Zenodo 15287692 (13 MB zip) | a few min (download speed) |
| 2 | [`openmesh_dataset_example.ipynb`](../dataset/examples/openmesh_dataset_example.ipynb) | Explore wireless links: map, frequencies, signal time series | output of #1 | <1 min |
| 3 | [`read_pws_sample.ipynb`](../dataset/examples/read_pws_sample.ipynb) | Read the personal-weather-station sample | output of #1 | <1 min |
| 4 | [`asos_gauge_melt_qc.ipynb`](asos_gauge_melt_qc.ipynb) | Fetch ASOS 1-minute data and apply the `gauge_melt` QC filter (on / flag / off) | IEM API (public, no key) | ~1 min |
| 5 | [`analysis.ipynb`](../src/analysis/analysis.ipynb) | End-to-end: CML signal vs. weather | output of #1 + ASOS from IEM (WU fetch needs a `WU_API_KEY`) | ~3 min |

## Radar (MRMS)

NOAA MRMS radar for one rain event, next to every sensor, and rainfall maps from the sensors.

| # | Notebook | What it shows | Data | Time |
|---|----------|---------------|------|------|
| R1 | [`mrms_pipeline.ipynb`](../src/fetch_data/mrms/mrms_pipeline.ipynb) | How to fetch MRMS: products, area, window or event list (incl. the repository's event catalog), cache | MRMS (public, AWS open data) | ~1 min |
| R2 | [`radar.ipynb`](radar.ipynb) | MRMS QPE, rain rate and precipitation type for one event; radar vs. ASOS, WU PWS and CML (hourly scores with n); IDW rain maps vs. radar | `DATASET = 'essd'` (default): public only — ESSD CML file (#1), WU PWS (Zenodo 17508286, optional), ASOS and MRMS fetched for the event window. `'v2'`: Zenodo 2.0.0, full period. `'v1'`: the authors' local files | a few min first run, <1 min after |

With `DATASET = 'essd'` the notebook downloads what is missing and builds the CML
attenuation file for the event window (`src/analysis/cml_baseline.py --dataset essd`).
With `'v2'` build the 10-min CML attenuation file once with
`python src/analysis/cml_baseline.py --dataset v2 --freq 10min`.

Code: `src/fetch_data/mrms/` (fetching), `src/analysis/radar_utils.py` (catalog,
merging, comparison, figures) and `src/analysis/rain_maps.py` (IDW maps, map scores,
CML retrieval QC, map figures). Fetch all events from the command line with
`python src/fetch_data/mrms/fetch_events.py`.

**Data formats:** the netCDF layouts used above are specified in
[`dataset/formats/`](../dataset/formats/README.md).
