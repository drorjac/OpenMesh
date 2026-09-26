# Tutorials

A suggested reading order for new users. Each notebook runs top to bottom on
public data (Zenodo archive or public APIs). Set up the environment first — see the
main [README](../README.md#get-started).

| # | Notebook | What you learn | Data | Time |
|---|----------|----------------|------|------|
| 1 | [`download_and_read_openmesh.ipynb`](../src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb) | Download the OpenMesh archive from Zenodo and load links | Zenodo (13 MB zip) | a few min (download speed) |
| 2 | [`openmesh_dataset_example.ipynb`](../dataset/examples/openmesh_dataset_example.ipynb) | Explore wireless links: map, frequencies, signal time series | output of #1 | <1 min |
| 3 | [`read_pws_sample.ipynb`](../dataset/examples/read_pws_sample.ipynb) | Read the personal-weather-station sample | output of #1 | <1 min |
| 4 | [`asos_gauge_melt_qc.ipynb`](asos_gauge_melt_qc.ipynb) | Why raw ASOS precipitation is wrong after snowstorms, and the QC that fixes it | IEM API (no key) | ~1 min |
| 5 | [`analysis.ipynb`](../src/analysis/analysis.ipynb) | End-to-end: CML signal vs. weather | outputs of #1 + fetches | ~3 min |

## Radar track (MRMS)

Fetch NOAA MRMS radar for NYC, merge it with every sensor, and compare. Tutorial 1 §1–3
runs on public data; everything else needs the full-period study files in
`dataset/raw/full/outputs/` (local, not in the Zenodo archive).

| # | Notebook | What you learn | Time |
|---|----------|----------------|------|
| R1 | [`radar_01_fetch_mrms.ipynb`](radar_01_fetch_mrms.ipynb) | MRMS products; fetch + cache for NYC; build the 15-event catalog (5 snow / 5 rain / 5 mix) | ~30 s (cached) |
| R2 | [`radar_02_merge_sensors.ipynb`](radar_02_merge_sensors.ipynb) | Pre-process ASOS, WU PWS, Mesonet and CML to hourly mm; merge with radar at each sensor | ~1 min |
| R3 | [`radar_03_compare_sensors.ipynb`](radar_03_compare_sensors.ipynb) | NRMSE and friends: sensor vs. radar, sensor vs. sensor, event totals vs. NOAA daily, precip type | ~4 min |

Code: `src/fetch_data/mrms/` (fetching, ported from pcpn_maps) and
`src/analysis/radar_utils.py` (catalog, merging, comparison, figures). Fetch all events
from the command line with `python src/fetch_data/mrms/fetch_events.py`.

**Data formats:** the netCDF layouts used above are specified in
[`dataset/formats/`](../dataset/formats/README.md).
