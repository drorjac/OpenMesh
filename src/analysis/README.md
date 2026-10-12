# Analysis pipeline

**Start here:** open `analysis.ipynb`, keep `MODE = 'fetch'` (default) and run all cells.
Missing inputs are downloaded (OpenMesh v1 files from Zenodo, ASOS 1-min data from the
Iowa Environmental Mesonet). Weather Underground data is only fetched with
`PWS_SOURCE = 'wu'` and needs a `WU_API_KEY` environment variable
(see [API_KEY_SETUP.md](../fetch_data/weather_underground/API_KEY_SETUP.md)).
`MODE = 'load'` reads only files already on disk.

- **`analysis.ipynb`**: the end-to-end example on the OpenMesh v1 release. Run it from the
  repo root or from `src/analysis/`. Knobs: `MODE`, `PWS_SOURCE`, `PWS_OPENMESH_SOURCE`.
- **`pipeline.py`**: `load_or_fetch_*` helpers, path resolution and the unified data
  format used by the notebook.
- **`plotting.py`**, **`analysis_functions.py`**: plots, CML–PWS matching, an example
  rolling-std rain detector.
- **`datasets.py`**: which OpenMesh dataset every loader reads, v1 (default) or Zenodo v2,
  and one reader for both CML layouts (`open_cml`, `signal_level`, `sublink_table`). See
  [dataset/README.md](../../dataset/README.md#choosing-the-dataset-v1-default-or-zenodo-v2).
- **`cml_baseline.py`**: builds the CML attenuation-baseline file used by the radar and map
  tutorials: `python src/analysis/cml_baseline.py --dataset v1|v2 --freq 1h|10min`.
- **`radar_utils.py`**, **`rain_maps.py`**, **`itu_rainrate.py`**: sensor vs MRMS radar
  comparison, IDW rain maps, ITU-R P.838-3 rain rate from attenuation.
- **`pws_qc/`**: PWS quality control (`notebooks/wu_pws_qc.ipynb` is its driver).

For CLI and data layout, see the root [README.md](../../README.md) and
[dataset/README.md](../../dataset/README.md).
