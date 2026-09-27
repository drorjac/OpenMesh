# netCDF converters

Every script that turns raw data into the project's netCDF files lives here. Each
has a module docstring with its input, output and usage; all run from the command
line (`python <script>.py --help`) or as an import.

**Defaults** are the converters behind the published Zenodo files (marked ★); the
others handle the later full-period data and are optional.

| Converter | Input | Output (layout) | Produces |
|---|---|---|---|
| ★ `openmesh_to_opensense_cml.py` | OpenMesh CML dataset (cml_id × sublink_id × time, rsl + link metadata) | OpenSense-CML-v1.0 | Zenodo `ds_openmesh.nc` (record 15287692) |
| ★ `wu_pws_csv_to_opensense.py` | WU PWS CSVs + station metadata (2023-2024 format) | OpenSense-PWS-v1.0, one group per station | Zenodo `pws_wu_os.nc` (record 17508286) |
| `nycmesh_to_netcdf.py` | NYC Mesh daily zips of device JSON (local folder or Box) + link metadata CSV | `nycmesh_data_<s>_to_<e>.nc` — raw CML, (time, cml_id), rsl / rsl_remote / rsl_60g / rsl_60g_remote | `dataset/raw/full/nycmesh_data_20231029_to_20260430.nc` |
| `nycmesh_to_opensense_cml.py` (optional) | raw CML netCDF above + link table (selection, renumbering) | OpenSense-CML-v1.0, (cml_id, sublink_id, time) | `dataset/raw/full/paper/ds_opensense_cml.nc` |
| `wu_pws_csv_to_netcdf.py` (optional) | scraped WU CSVs, 2025-2026 format (PWS + airports) + station metadata | OpenSense-PWS-v1.0, one group per station | `dataset/raw/full/pws_wu_network.nc`, `pws_data_new.nc` |
| `airport_wu_csv_to_netcdf.py` | scraped WU airport CSVs | grouped PWS layout | `dataset/raw/full/airport_wu_dates.nc` |
| `asos_to_netcdf.py` | `ASOS_standard_*.csv` (from `fetch_data/noaa_asos`) | OpenSense-PWS-v1.0-asos, one group per station | `outputs/asos_2023-10-01_2026-04-23.nc` |
| `asos_flat_to_netcdf.py` | `ASOS_standard_*.csv` | OpenSense-PWS-v1.0, flat (id, time) | `dataset/raw/full/asos_nyc_network.nc`; used by the ASOS fetch pipeline |
| `mesonet_to_netcdf.py` | NY Mesonet 5-min CSVs | OpenSense-PWS-v1.0-mesonet, grouped | `outputs/mesonet_2023-08-01_2026-03-04.nc` |
| `noaa_daily_to_netcdf.py` | NOAA GHCN-Daily (from `fetch_data/noaa_daily`) | grouped PWS layout | daily station netCDF |
| `merge_pws_opensense.py` | N grouped PWS files | one merged grouped file (later file wins) | `outputs/pws_wu_merged_*.nc` |
| `merge_airport_wu_to_pws.py` | `airport_wu_dates.nc` + merged PWS QC file | merged PWS QC file | `outputs/pws_wu_merged_2023-06-07_*_qc.nc` |
| `build_stations_metadata.py` | the netCDF files above | `dataset/meta/stations_full.{csv,json}` | station table |

Not here: MRMS radar is cached as netCDF by `src/fetch_data/mrms` (and exported by
`mrms/mrms_pipeline.ipynb`); the PWS QC file is written by `analysis.pws_qc`; the CML
attenuation file by `methods/cml_baseline.py` — those are analysis products, not
conversions of raw data.

Format specs: `dataset/formats/` (netCDF_CML.adoc, netCDF_PWS.adoc, netCDF_mesonet.adoc).
Readers: `analysis.netcdf_utils.load_pws_grouped`, `analysis.nycmesh_utils.load_weather_networks`.
