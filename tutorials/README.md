# Tutorials

`radar.ipynb` runs on either public dataset: set `DATASET = 'v1'` (default, the ESSD record)
or `'v2'` (OpenMesh 2.0.0) in its setup cell. See the [README](../README.md#datasets).
`asos_gauge_melt_qc.ipynb` needs no dataset, only internet access.

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

## More

- Download and read the OpenMesh records: [`src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb`](../src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb)
- Full analysis pipeline: [`src/analysis/analysis.ipynb`](../src/analysis/analysis.ipynb)
- Radar fetching reference: [FETCHING.md](../FETCHING.md) · setup: [SETUP.md](../SETUP.md) · details: [DETAILS.md](../DETAILS.md)
