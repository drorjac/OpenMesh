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

**Data formats:** the netCDF layouts used above are specified in
[`dataset/formats/`](../dataset/formats/README.md).
