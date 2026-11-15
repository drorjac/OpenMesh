# Data sources

Every dataset this repository reads or fetches: who provides it, its terms, what you need to get it,
and how the code gets it. Links checked on 2026-11-15.

## Summary

| Source | Provider | Needs | Terms | In this repo |
|---|---|---|---|---|
| OpenMesh v2 (2.0.0) | Zenodo [10.5281/zenodo.23283445](https://doi.org/10.5281/zenodo.23283445) | nothing | CC BY 4.0 | downloaded on first use |
| OpenMesh v1 (ESSD) | Zenodo [10.5281/zenodo.15287692](https://doi.org/10.5281/zenodo.15287692) | nothing | CC BY 4.0 | downloaded on first use |
| WU PWS of v1 | Zenodo [10.5281/zenodo.17508286](https://doi.org/10.5281/zenodo.17508286) | nothing | CC BY-NC 4.0 | downloaded on request |
| MRMS radar | NOAA, [AWS Open Data](https://registry.opendata.aws/noaa-mrms-pds/) | nothing | public domain (NOAA) | fetched, any period |
| KOKX NEXRAD Level III | NOAA, [AWS Open Data](https://registry.opendata.aws/noaa-nexrad/) | nothing | public domain (NOAA) | fetched, any period |
| ASOS 1-minute | NOAA NCEI, via the [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu/request/asos/1min.phtml) | nothing | public domain (NOAA) | fetched, any period |
| GHCN-Daily | [NOAA NCEI](https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily) | nothing | public domain (NOAA); CoCoRaHS stations: [CoCoRaHS](https://www.cocorahs.org/) terms | fetched, any period |
| Weather Underground PWS | [The Weather Company](https://www.wunderground.com/pws/overview) | **an API key** | WU terms of use (no redistribution) | fetched, any period |
| NYS Mesonet | [New York State Mesonet](https://www.nysmesonet.org/about/data) | **a data request** | [NYS Mesonet Data Access Policy](https://www.nysmesonet.org/documents/NYS_Mesonet_Data_Access_Policy.pdf) | converter only, no data |

None of the NOAA sources or the Zenodo records needs an account or a key.

The v1 and v2 records are separate releases, not one series continued: different link sets and cml_ids, sampling and
reference networks. Only v1 has Weather Underground PWS data; v2 has ASOS, GHCN-Daily and 10 radar days.

## OpenMesh records (Zenodo)

- **v2, OpenMesh 2.0.0**: [10.5281/zenodo.23283445](https://doi.org/10.5281/zenodo.23283445), file
  `openmesh-2.0.0.zip` (606 MB, md5 `0ea526b7d48ced4d59e2adbf12cb92cd`). 372 links / 758 sublinks,
  2023-10-29 to 2026-11-01, with ASOS, GHCN-Daily and 10 days of MRMS and KOKX radar. The zip holds its own
  reader (`tools/openmesh_tools`) and three notebooks.
  `from analysis import datasets as D; D.ensure('v2')` downloads it (resumable, md5-checked) and unpacks it into
  `dataset/raw/openmesh_v2/`; the same from the shell: `python src/fetch_data/main.py openmesh_v2`.
  For a zip you already have: `D.install_v2('<zip>')`. For data kept elsewhere: `OPENMESH_V2_DIR=<folder>`.
- **v1, the ESSD record**: [10.5281/zenodo.15287692](https://doi.org/10.5281/zenodo.15287692) (`OpenMesh.zip`),
  75 links / 103 sublinks, 2023-10-29 to 2024-07-01: `python src/fetch_data/main.py openmesh`.
  Its 37 Weather Underground stations are a separate record,
  [10.5281/zenodo.17508286](https://doi.org/10.5281/zenodo.17508286) (`PWS_NYC_WU.zip`, CC BY-NC 4.0).

## MRMS radar

- **What:** NOAA Multi-Radar Multi-Sensor products (QPE, precipitation rate, precipitation type, reflectivity),
  0.01°, every 2 min to 1 h; [product tables](https://www.nssl.noaa.gov/projects/mrms/operational/tables.php).
- **Where:** the `noaa-mrms-pds` bucket of [AWS Open Data](https://registry.opendata.aws/noaa-mrms-pds/)
  (from October 2020); older days from the [IEM MTArchive](https://mtarchive.geol.iastate.edu/).
- **How:** `python src/fetch_data/main.py mrms --start 2024-02-13 --end 2024-02-14 --products MultiSensor_QPE_01H_Pass2 PrecipFlag`,
  or `python src/fetch_data/radar_events.py fetch mrms --day 2024-02-13`. Fields are cropped to NYC
  (`--bbox` for another area); `--list-products` lists the archive. Code: `src/fetch_data/mrms/`.
- **Needs:** `eccodes` with its Python binding (GRIB2), installed by `environment.yml`.

## KOKX NEXRAD

- **What:** Level III products of the Upton, NY radar (KOKX): base reflectivity `N0B` and hydrometeor class `HHC`,
  0.25 km gates, every 5–10 min, sampled at the link paths.
- **Where:** the `unidata-nexrad-level3` bucket, part of [NOAA NEXRAD on AWS](https://registry.opendata.aws/noaa-nexrad/).
- **How:** `python src/fetch_data/radar_events.py fetch kokx --day 2024-02-13 --dataset v2`. Code: `src/fetch_data/nexrad/`.
- **Needs:** `metpy` (Level III decoding).

## ASOS 1-minute

- **What:** 1-minute precipitation, temperature, wind and pressure at airport stations (NYC: JFK, LGA, NYC
  Central Park, EWR, TEB; any ASOS station works).
- **Where:** NOAA NCEI publishes the 1-minute archive monthly; the
  [Iowa Environmental Mesonet (IEM)](https://mesonet.agron.iastate.edu/request/asos/1min.phtml) serves it from 2000
  on, usually up to one or two days ago (the page shows the last available date).
- **How:** `python src/fetch_data/main.py asos -s JFK LGA NYC EWR TEB --start 2024-02-13 --end 2024-02-14`, or
  `D.fetch_v1_asos(start, end)` for the v1 window. Code: `src/fetch_data/noaa_asos/`.

## GHCN-Daily

- **What:** daily precipitation, snowfall, snow depth and temperature. The defaults are the 7 stations of the v2 record:
  4 NWS first-order stations (Central Park, JFK, LaGuardia, Newark) and 3 [CoCoRaHS](https://www.cocorahs.org/)
  volunteer gauges (Palisades Park NJ, Jersey City NJ, Howard Beach NY). CoCoRaHS gauges have gaps on days without a report.
- **Where:** [NOAA NCEI GHCN-Daily](https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily),
  one CSV per station under `https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/`.
- **How:** `D.fetch_v1_ghcn(start, end)`, or in Python
  `from noaa_daily import fetch_all_stations, NYC_STATIONS` (with `src/fetch_data` on the path). Code: `src/fetch_data/noaa_daily/`.

## Weather Underground PWS (API key required)

- **What:** personal weather station observations; the fetcher asks for hourly history by default
  (the API also has an `all` history at the station's own interval, typically 5 min).
- **Where:** the PWS API of The Weather Company (`https://api.weather.com/v2/pws`).
- **Needs:** an API key. The Weather Company gives free keys to owners of a personal weather station that sends
  data to Weather Underground; the key is on your account's [API keys page](https://www.wunderground.com/member/api-keys).
  The key and the data are under the Weather Underground / The Weather Company terms of use, which do not allow
  redistributing the data. Never commit the key.
- **How:** `export WU_API_KEY=<your key>`, then
  `python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-02-13 --end 2024-02-14`.
  Without a key the fetcher stops with a message that says how to set one. Details:
  [API_KEY_SETUP.md](src/fetch_data/weather_underground/API_KEY_SETUP.md). Code: `src/fetch_data/weather_underground/`.
- The v1 stations are also on Zenodo ([10.5281/zenodo.17508286](https://doi.org/10.5281/zenodo.17508286)), no key needed.

## NYS Mesonet (data by request)

- **What:** the New York State Mesonet, 127 standard stations with 5-minute weather data, including NYC.
- **Getting it:** not downloadable through an open API. Request it from the NYS Mesonet:
  [data information](https://www.nysmesonet.org/about/data), [request data](https://www.nysmesonet.org/weather/requestdata),
  and the [Data Access Policy](https://www.nysmesonet.org/documents/NYS_Mesonet_Data_Access_Policy.pdf). The data are free
  for personal use; other uses are licensed, and a cost-recovery fee may apply.
- **In this repo:** no Mesonet data and no fetcher. `src/netCDF_converters/mesonet_to_netcdf.py` turns the
  5-minute station CSVs you receive into netCDF (layout: `dataset/formats/netCDF_mesonet.adoc`).
