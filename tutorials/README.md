# Tutorials

`radar.ipynb` runs on either public dataset: set `DATASET = 'v1'` (default, the ESSD record)
or `'v2'` (OpenMesh 2.0.0) in its setup cell. See the [README](../README.md#datasets).
`asos_gauge_melt_qc.ipynb` needs no dataset, only internet access. `v2/` holds the example
notebooks of the v2 record itself.

## `radar.ipynb` — radar next to every sensor

MRMS and KOKX NEXRAD radar for one rain event and for all rain events of the dataset, next to
CML, ASOS, WU PWS (v1) and GHCN daily.

- §1 the rainy days of the dataset (event catalog) and the data each one has
- §2 raw radar: MRMS QPE, rate and precipitation type; single KOKX scans (reflectivity,
  hydrometeor class); the v2 record's MRMS and KOKX files of the day, checked against AWS
- §3 every sensor next to both radars: map, time series, scatter, scores, one CML link in
  its raw 10-min form
- §4 sensors against each other: hourly vs. the nearest ASOS gauge, event totals vs. GHCN
- §5 the same comparison pooled over all rain events
- §6 link QC, then IDW rainfall maps from the sensors vs. the radar
- §7 the radar adjusted with CML and/or gauges (mean-field bias, additive,
  multiplicative), scored at ASOS gauges the products have not seen

First run with `'v1'` downloads the ESSD archive, ASOS (IEM) and GHCN (NCEI) and builds the
CML attenuation file (15–30 min); radar downloads add a few minutes. Later runs read caches.

## `asos_gauge_melt_qc.ipynb` — ASOS gauge-melt QC

ASOS 1-min precipitation and the `gauge_melt` QC that removes melt water reported by heated
tipping buckets after snow. About 1 min.

## `v2/` — the v2 record's notebooks

The three notebooks of OpenMesh 2.0.0 ([Zenodo 23283445](https://doi.org/10.5281/zenodo.23283445)),
run on the record in `dataset/raw/openmesh_v2/`; on first run they download it from Zenodo (~600 MB, `D.ensure('v2')`). They
read it through `analysis.datasets` and call the helpers in `src/analysis/v2/`.

- `00_quickstart` — open the files with plain xarray; choose an event and a link; the network;
  every sublink of the link; the nearest gauge (about 1 min)
- `01_data_overview` — every file and how to open it; raw series; the sampling; the tables
  against the netCDF and the OpenSense conventions; map, density, frequencies; availability;
  data quality (about 3 min: it summarises the whole links file)
- `02_analysis` — links, ASOS, GHCN and radar together: example days, rain accumulation of
  60 GHz links against radar and gauges (ITU-R P.838), blackouts, recovery after rain and
  snow, dry baselines, the 10 radar days, radar along the links (about 3 min)

`v2/make_notebooks.py` writes the three notebooks; then
`jupyter nbconvert --to notebook --execute --inplace v2/0*.ipynb`.

## More

- Download and read the OpenMesh records: [`src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb`](../src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb)
- Full analysis pipeline: [`src/analysis/analysis.ipynb`](../src/analysis/analysis.ipynb)
- Radar fetching reference: [FETCHING.md](../FETCHING.md) · setup: [SETUP.md](../SETUP.md) · details: [DETAILS.md](../DETAILS.md)
