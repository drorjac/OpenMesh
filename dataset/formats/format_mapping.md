# Data Source → OpenSense Format Mapping

Field-by-field translation tables from each project data source to the OpenSense netCDF standard.
Full specs are in the `.adoc` files in this folder.
Upstream reference: https://github.com/OpenSenseAction/OS_data_format_conventions

---

## OpenSense PWS Format — Quick Reference

Source spec: `netCDF_PWS.adoc`

### Dimensions

| Dimension | Notes |
|-----------|-------|
| `time` | Unlimited. UTC seconds since 1970-01-01. Timestamp = **end** of observation interval |
| `id` | PWS identifier — must be unique across the network |

### Variables

| Variable | Dims | Type | Units | Status |
|----------|------|------|-------|--------|
| `time` | time | int/float/double | seconds since 1970-01-01 UTC | Required |
| `id` | id | string | — | Required |
| `lat` | id | float/double | degrees WGS84 | Required |
| `lon` | id | float/double | degrees WGS84 | Required |
| `elev` | id | float/double | m above sea | Recommended |
| `Height_above_ground_level` | id | float/double | m | Recommended |
| `Environmental_class` | id | integer | — | Recommended |
| `hardware` | id | string | — | Optional |
| `rainfall_amount` | id, time | float/double | mm per time unit | Required |
| `temperature` | id, time | float/double | °C | Optional |
| `relative_humidity` | id, time | float/double | % | Optional |
| `wind_velocity` | id, time | float/double | m/s | Optional |
| `wind_direction` | id, time | float/double | degrees | Optional |
| `air_pressure` | id, time | float/double | hPa | Optional |

### Global Attributes (applies to CML, SML, PWS)

| Attribute | Status | Description |
|-----------|--------|-------------|
| `title` | Recommended | Brief description of dataset contents |
| `file_author(s)` | Recommended | Who produced the data and contact info |
| `institution` | Recommended | Where the dataset was produced |
| `date` | Recommended | When the dataset was created |
| `source` | Recommended | How data were obtained (instrument, API, model) |
| `version` | Recommended | Dataset version number or name |
| `history` | Recommended | Timestamped log of modifications |
| `naming_convention` | Recommended | Use `OpenSense-X` |
| `licence` | Recommended | Data license |
| `reference` | Optional | DOI or data source URL |
| `comment` | Optional | Extra info (coordinate precision, campaign period, non-standard fields) |

---

## ASOS → OpenSense PWS

ASOS data is fetched at 1-minute resolution via the IEM API (`src/fetch_data/noaa_asos/`).
Lat/lon/elev are not in the CSV rows — joined from `dataset/meta/ASOS_stations.csv`
(the `Station ID` column in metadata holds are 4-letter ICAO codes like `KJFK`; the data CSV uses
the 3-letter form `JFK`, so the leading `K` is stripped during the join).

**Converter:** `src/netCDF_converters/asos_to_netcdf.py`
**Output:** one netCDF4 file with one group per station (e.g. JFK, LGA, NYC),
`Conventions = OpenSense-PWS-v1.0-asos`. The output file is not part of the public data.

| ASOS column | OpenSense variable | Action |
|-------------|--------------------|--------|
| `datetime` | `time` | Convert to Unix epoch (UTC) |
| `station_id` | `id` + group name | Direct — e.g. `JFK`, `LGA` |
| *(ASOS_stations.csv)* | `lat` | Join `Latitude` on `Station ID` (strip `K` prefix) |
| *(ASOS_stations.csv)* | `lon` | Join `Longitude` on `Station ID` (strip `K` prefix) |
| *(ASOS_stations.csv)* | `elev` | Join `Elevation` on `Station ID` (strip `K` prefix) |
| `temperature` | `temperature` | Already °C |
| `wind_speed` | `wind_velocity` | Already m/s |
| `wind_direction` | `wind_direction` | Already degrees |
| `precip_amount` | `rainfall_amount` | Already mm per 1-minute interval |
| `humidity` | `relative_humidity` | % — only in resampled output (not in 1-min CSV) |
| `pressure` | `air_pressure` | hPa — only in resampled output (not in 1-min CSV) |

**ASOS extras (kept as non-spec variables in each group):**

| ASOS column | netCDF variable | Units | Notes |
|-------------|-----------------|-------|-------|
| `dewpoint` | `dewpoint` | degrees_celsius | numeric |
| `wind_gust` | `wind_gust` | ms-1 | numeric |
| `wind_gust_direction` | `wind_gust_direction` | degrees | numeric |
| `precip_rate` | `rainfall_rate` | mm h-1 | numeric |
| `precip_type` | `precip_type` | — | string (e.g. `NP`, `R-`, `S-`) |
| `precip_category` | `precip_category` | — | string (`dry`, `rain`, `snow`, `precip`, `missing`) |

The extras are listed in the root `comment` attribute so downstream tools know
they're outside the strict OpenSense PWS spec.

---

## WU (Weather Underground) → OpenSense PWS

WU data is fetched at hourly resolution (`src/fetch_data/weather_underground/`).
Lat/lon are already in the CSV rows. Additional metadata in `dataset/meta/pws_metadata.csv` (columns `Station ID`, `Latitude`, `Longitude`, `Elevation`).

| WU column | OpenSense variable | Action |
|-----------|--------------------|--------|
| `datetime` | `time` | Convert to Unix epoch (UTC) |
| `station_id` | `id` | Direct — e.g. `KNYNEWYO1805` |
| `latitude` | `lat` | Already degrees WGS84 |
| `longitude` | `lon` | Already degrees WGS84 |
| *(pws_metadata.csv)* | `elev` | Join the `Elevation` column on its `Station ID` column (= WU `station_id`) |
| `temperature` | `temperature` | Already °C |
| `humidity` | `relative_humidity` | Already % |
| `wind_speed` | `wind_velocity` | Already m/s |
| `wind_direction` | `wind_direction` | Already degrees |
| `precip_amount` | `rainfall_amount` | Already mm |
| `pressure` | `air_pressure` | Already hPa |
| `dewpoint` | — | No OpenSense field; include in `comment` if needed |

**WU columns with no OpenSense equivalent** (drop or put in `comment`):
`temperature_high/low`, `dewpoint_high/low`, `heat_index*`, `wind_chill*`,
`wind_speed_high/low/gust*`, `pressure_min`, `pressure_trend`,
`solar_radiation_high`, `uv_index_high`, `qc_status`, `timestamp_unix`, `timezone`

---

## NY Mesonet → OpenSense PWS

There is no public Mesonet data in this project. The converter
`src/netCDF_converters/mesonet_to_netcdf.py` turns NY Mesonet per-station CSV files
(5-minute data) into the extended PWS layout described in `netCDF_mesonet.adoc`;
its `COLUMN_MAP` lists every column. The main fields:

| Mesonet CSV column | OpenSense variable | Action |
|--------------------|--------------------|--------|
| `station` | `id` + group name | Direct, e.g. `BKLN` |
| `latitude [degrees_north]` | `lat` | degrees WGS84 |
| `longitude [degrees_east]` | `lon` | degrees WGS84 |
| `elevation [m]` | `elev` | m above sea |
| `temp_2m [degC]` | `temperature` | Already °C |
| `relative_humidity [percent]` | `relative_humidity` | % |
| `avg_wind_speed_merge [m/s]` | `wind_velocity` | Already m/s |
| `wind_direction_merge [degrees]` | `wind_direction` | degrees |
| `precip_incremental [mm]` | `rainfall_amount` | mm per interval |
| `station_pressure [mbar]` | `air_pressure` | mbar = hPa |

---

## OpenSense CML Format — Quick Reference

Source spec: `netCDF_CML.adoc`

The CML data (`dataset/raw/openmesh/ds_openmesh.nc`) is already in OpenSense format — no
conversion needed. This section is a reference for understanding the structure.

### Dimensions

| Dimension | Notes |
|-----------|-------|
| `time` | Unlimited. UTC seconds since 1970-01-01 |
| `cml_id` | Link identifier — unique across the network |
| `sublink_id` | Sublink identifier — unique within each CML |

### Key variables

| Variable | Dims | Units | Status |
|----------|------|-------|--------|
| `site_0_lat`, `site_0_lon` | cml_id | degrees WGS84 | Required |
| `site_1_lat`, `site_1_lon` | cml_id | degrees WGS84 | Required |
| `site_0_alt`, `site_1_alt` | cml_id | m above sea | Recommended |
| `length` | cml_id | m | Optional |
| `frequency` | cml_id, sublink_id | MHz | Required |
| `polarisation` | cml_id, sublink_id | 'vertical'/'horizontal' | Recommended |
| `tsl` | cml_id, sublink_id, time | dBm | Required* |
| `rsl` | cml_id, sublink_id, time | dBm | Required* |

For min/max (NMS) sampling: `tsl_max`, `tsl_min`, `rsl_max`, `rsl_min` (dBm, Required*).
*When TSL or RSL is constant, only the varying variable is required.
