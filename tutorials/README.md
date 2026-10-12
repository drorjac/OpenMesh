# Tutorials

A suggested reading order for new users. Set up the environment first — see the
main [README](../README.md#get-started). Not every notebook runs on public data: the
**Data** column says what each one needs, and each notebook repeats it in a
"Data needed" note at the top.

**Data sources**

| source | access | fetched / read by |
|---|---|---|
| OpenMesh ESSD archive, [Zenodo 15287692](https://doi.org/10.5281/zenodo.15287692): 75 CMLs, 2023-10-29 → 2024-07-01, plus a 2-week WU PWS sample | public, CC BY 4.0 | `src/fetch_data/OpenMesh/` |
| WU PWS, [Zenodo 17508286](https://doi.org/10.5281/zenodo.17508286): 37 stations, ESSD period | public, CC BY-NC 4.0 | manual download (see `dataset/README.md`) |
| ASOS 1-minute (IEM API, no key) | public | `src/fetch_data/noaa_asos/` |
| NOAA MRMS radar (AWS open data, IEM mirror) | public | `src/fetch_data/mrms/` |
| OpenMesh 2.0.0, [Zenodo 23283445](https://doi.org/10.5281/zenodo.23283445): 359 CMLs to 2026-05-31, 5 ASOS, 7 GHCN daily, 10 MRMS days | access-restricted for now | `analysis.datasets` with `DATASET = 'v2'` |
| Full-period study files in `dataset/raw/full/outputs/` (ASOS, WU PWS, NY Mesonet, GHCN daily, CML attenuation baselines) | local to the repository owner, not published | `analysis.datasets` with `DATASET = 'v1'` |

| # | Notebook | What it shows | Data | Time |
|---|----------|---------------|------|------|
| 1 | [`download_and_read_openmesh.ipynb`](../src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb) | Download the OpenMesh archive from Zenodo and load links | Zenodo 15287692 (13 MB zip) | a few min (download speed) |
| 2 | [`openmesh_dataset_example.ipynb`](../dataset/examples/openmesh_dataset_example.ipynb) | Explore wireless links: map, frequencies, signal time series | output of #1 | <1 min |
| 3 | [`read_pws_sample.ipynb`](../dataset/examples/read_pws_sample.ipynb) | Read the personal-weather-station sample | output of #1 | <1 min |
| 4 | [`asos_gauge_melt_qc.ipynb`](asos_gauge_melt_qc.ipynb) | Fetch ASOS 1-minute data and apply the `gauge_melt` QC filter (on / flag / off) | IEM API (public, no key) | ~1 min |
| 5 | [`analysis.ipynb`](../src/analysis/analysis.ipynb) | End-to-end: CML signal vs. weather | output of #1 + ASOS from IEM (WU fetch needs a `WU_API_KEY`) | ~3 min |

## Radar track (MRMS)

Fetch NOAA MRMS radar for NYC, merge it with every sensor, compare, and map.

| # | Notebook | What it shows | Data | Time |
|---|----------|---------------|------|------|
| R1 | [`radar_01_fetch_mrms.ipynb`](radar_01_fetch_mrms.ipynb) | MRMS products; fetch + cache for NYC; the 15-event catalog | MRMS (public). §4 rebuilds the catalog from the local full-period ASOS/GHCN files if present, otherwise loads the committed `dataset/meta/radar_events.csv` | ~30 s (cached) |
| R2 | [`radar_02_merge_sensors.ipynb`](radar_02_merge_sensors.ipynb) | Pre-process ASOS, WU PWS, Mesonet and CML to hourly mm; merge with radar at each sensor | full-period study files (local) or Zenodo 2.0.0 (restricted) + MRMS cache from R1 | ~1 min |
| R3 | [`radar_03_compare_sensors.ipynb`](radar_03_compare_sensors.ipynb) | Scores: sensor vs. radar, sensor vs. sensor, event totals vs. NOAA daily, precip type | as R2 | ~4 min |
| R4 | [`radar_04_rain_maps.ipynb`](radar_04_rain_maps.ipynb) | Rainfall maps (IDW) from CML, PWS and all gauges vs. MRMS; CML QC; IDW settings | as R2 | ~4 min |

R2–R4 read the full-period study files by default (`DATASET = 'v1'`). With
`DATASET = 'v2'` in the setup cell they read the Zenodo 2.0.0 record instead (ASOS, GHCN
and CML only: v2 has no WU PWS or Mesonet). The 10-min CML attenuation file is built
once with `python src/analysis/cml_baseline.py --dataset v2 --freq 10min`.

Code: `src/fetch_data/mrms/` (fetching), `src/analysis/radar_utils.py` (catalog,
merging, comparison, figures) and `src/analysis/rain_maps.py` (IDW maps, map scores,
CML retrieval QC, map figures). Fetch all events from the command line with
`python src/fetch_data/mrms/fetch_events.py`.

**Data formats:** the netCDF layouts used above are specified in
[`dataset/formats/`](../dataset/formats/README.md).
