# formats/

Reference hub for the **OpenSense netCDF format conventions** used across this project.

## Role

All data in OpenMesh — whether fetched from external APIs (ASOS, WU, mesonet) or downloaded from
Zenodo (CML, PWS) — targets a single output format: the OpenSense netCDF standard. This folder
holds the official specs, working examples, and a field-by-field mapping guide showing how each
source dataset converts to that standard.

**When adding a new data source or writing a converter, start here.**

## Contents

| File | Role |
|------|------|
| `netCDF_CML.adoc` | Official OpenSense spec: CML (Commercial Microwave Link) |
| `netCDF_PWS.adoc` | Official OpenSense spec: PWS (Personal Weather Station) |
| `CML_example_dataset.ipynb` | Working example: reading and navigating CML netCDF structure |
| `PWS_example_dataset.ipynb` | Working example: reading and navigating PWS netCDF structure |
| `format_mapping.md` | Field mapping: ASOS / WU / mesonet → OpenSense PWS + CML reference |

Files not yet mirrored locally (available upstream):
- `netCDF_SML.adoc` — Satellite Microwave Link spec
- `netCDF_global_attributes.adoc` — Global attribute conventions for all types

## Official Source

All specs originate from:
**<https://github.com/OpenSenseAction/OS_data_format_conventions>**

The `.adoc` files are mirrored from that repo. If the spec is updated upstream, replace the local
copies.

## Which format applies to each data source?

| Data source | OpenSense target format | Status | Converter |
|-------------|------------------------|--------|-----------|
| OpenSense CML (Zenodo `ds_openmesh.nc`) | CML | Already in format | — |
| OpenSense PWS (Zenodo `pws_wu_os.nc`, `pws_opensense_sample_jan.nc`) | PWS | Already in format | — |
| WU (Weather Underground) | PWS | Converted (merged) | `src/netCDF_converters/merge_pws_opensense.py` |
| ASOS (airport stations) | PWS | Converted | `src/netCDF_converters/asos_to_netcdf.py` |
| Mesonet (NY Mesonet) | PWS | Converted | `src/netCDF_converters/mesonet_to_netcdf.py` |

All three converters emit the **group-per-station** layout used by the OpenSense PWS
samples (one netCDF4 group per station, `id=1` inside each). Outputs land in
`dataset/raw/full/outputs/`. See `format_mapping.md` for field-by-field translation tables.

## Examples vs. Specs

The notebooks (`CML_example_dataset.ipynb`, `PWS_example_dataset.ipynb`) are from the upstream
OpenSense repo. They demonstrate how to read and explore the format but are not the primary project
examples — for project-specific usage see `dataset/examples/`. Use these notebooks here to
understand the netCDF structure when writing converters.
