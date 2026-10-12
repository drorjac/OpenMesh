# Paper link table (private)

`links_metadata_map_reduced.csv` — the link selection behind the paper's OpenSense
CML file `dataset/raw/full/paper/ds_opensense_cml.nc` (292 CMLs, 2023-10-29 → 2026-04-30;
`analysis.datasets` name: `'local'`).
One row per OpenSense (cml_id, sublink_id): which raw channel (`cml_api` +
`data_channel`) of `nycmesh_data_20231029_to_20260430.nc` fills it, plus site
coordinates, length (m), frequency (MHz), band, polarization, device and endpoint names.

- Source: `~/openmesh-opensense-builder/final_metadata/links_metadata_map_reduced.csv`
  (copied 2026-09-27; identical to `dataset/raw/full/paper/links_metadata_final.csv`).
- Built by the builder's metadata notebooks: filters step1–step5 (+ step4b) and
  co-located merges `merge_colocated(10m, >20m)`, then renumbered to cml_id 1..292
  with dense sublink ids.
- Contains node coordinates and device names — keep it in the private repo.

Rebuild the paper file (reproduces it exactly):

```bash
python src/netCDF_converters/nycmesh_to_opensense_cml.py \
    dataset/raw/full/nycmesh_data_20231029_to_20260430.nc \
    dataset/meta/paper/links_metadata_map_reduced.csv \
    dataset/raw/full/paper/ds_opensense_cml.nc \
    --filters "step1_picks,step2_picks,step3_picks,step4_picks,step4b_picks,step5_picks;merge_colocated(10m,>20m)"
```
