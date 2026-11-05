# Radar data

OpenMesh reads two radar sources, both NOAA open data on AWS, fetched on demand and cached
under `dataset/raw/radar/`. [`tutorials/radar.ipynb`](tutorials/radar.ipynb) shows both next
to every sensor (CML, ASOS, WU PWS, GHCN); this page is the reference for fetching them.

| | MRMS | KOKX NEXRAD |
|---|---|---|
| What | Multi-Radar/Multi-Sensor mosaic (all radars + gauges + model), surface products | One WSR-88D radar (Upton, NY, ~90 km east of the links), Level-3 products: reflectivity etc. of the 0.5° tilt (~1–1.5 km above ground over the links), hydrometeor class of the hybrid scan |
| Products | `MultiSensor_QPE_01H_Pass2` (hourly, gauge-corrected), `RadarOnly_QPE_01H`, `RadarOnly_QPE_15M`, `PrecipRate` (2 min), `PrecipFlag` (2 min, surface type), `RadarQualityIndex` | `N0B` reflectivity (dBZ), `N0X` differential reflectivity (dB), `N0C` correlation coefficient (0.5° tilt); `HHC` hybrid hydrometeor class (per gate, the lowest usable tilt) |
| Grid | 0.01° (~1 km), cropped to a domain (default NYC: 40.48–40.93 N, 74.27–73.68 W) | polar, 0.25 km gates; sampled at the CML paths and at the MRMS NYC cell centres (the gate containing each point) |
| Source | AWS `noaa-mrms-pds` (fallback: IEM archive, before 2020-10) | AWS `unidata-nexrad-level3` |
| Code | [`src/fetch_data/mrms/`](src/fetch_data/mrms) | [`src/fetch_data/nexrad/kokx.py`](src/fetch_data/nexrad/kokx.py) |
| Cache | `dataset/raw/radar/mrms/cache/` (one netCDF per product, domain, step) | `dataset/raw/radar/nexrad/<dataset>/<product>/` (one parquet per hour) |

Time convention: UTC. MRMS hourly QPE is labelled by the end of the hour (12:00 holds
11:00–12:00); KOKX scans by their valid time, one scan per 10 min kept.

## MRMS

```python
from fetch_data.mrms import MRMSClient, NYC, hourly_rainfall, event_accumulation
client = MRMSClient()
qpe = client.load("MultiSensor_QPE_01H_Pass2", "2024-03-23 00:00", "2024-03-24 00:00", NYC)   # (time, lat, lon)
flag = client.load("PrecipFlag", "2024-03-23 18:00", "2024-03-23 19:00", NYC, freq="10min")
total = event_accumulation("2024-03-23", "2024-03-24", NYC)                                   # (lat, lon), mm
```

More products, other areas and event lists: [`src/fetch_data/mrms/mrms_pipeline.ipynb`](src/fetch_data/mrms/mrms_pipeline.ipynb).

## KOKX

```python
from fetch_data.nexrad import kokx
scan = kokx.read_scan("N0B", "2024-03-23 18:40")          # one raw scan: azimuth × gate, not cached
lon, lat, z = kokx.scan_lonlat(scan, max_km=150)          # cell edges for pcolormesh

kokx.fetch_window("2024-03-23", "2024-03-24", products=("N0B", "HHC"))   # samples, cached
df = kokx.load("2024-03-23", "2024-03-24", "N0B")         # (t, key, pt, value); key = cml_id or 'grid'
z = kokx.load_grid("2024-03-23", "2024-03-24", "N0B")     # (time, lat, lon) on the 0.01° grid
rain = kokx.hourly_rain("2024-03-23 01:00", "2024-03-24")  # mm, hour-ending, Z = 200 R^1.6
```

The KOKX files of the v2 record (`data/weather/radar/openmesh_radar_kokx_<kind>_<day>.nc`) are
rebuilt exactly by `kokx.sample_grid(times)`: HHC and N0B at the MRMS cell centres, for each stamp
the scan nearest it within ±5 min (HHC 255 / N0B NaN where there is none), with the scan times.

```python
mrms = xr.open_dataset(".../openmesh_radar_snow_2024-02-13.nc")
ds = kokx.sample_grid(mrms.time_10min.values, mrms.lat.values, mrms.lon.values)
```

Samples are taken at 5 points along each CML path of the active dataset (`analysis.datasets`,
v1 or v2; pass `dataset=` to choose) and at the cell centres of the MRMS NYC grid (the gate whose radial contains the point), so the
MRMS tools (`sample_points`, `path_average`) work on `load_grid` output unchanged.

HHC codes (kept as NOAA stores them): 0 below threshold (no echo, not missing data),
10 biological, 20 ground clutter, 30 ice crystals, 40 dry snow, 50 wet snow, 60 light/moderate
rain, 70 heavy rain, 80 big drops, 90 graupel, 100 hail (possibly with rain), 110 large hail,
120 giant hail, 140 unknown, 150 range folded. The class is that of the beam (~1–1.5 km up),
not necessarily of the precipitation at the ground.

## The event catalog

[`dataset/meta/radar_events.csv`](dataset/meta/radar_events.csv) lists the top 5 snow, rain and
mixed-precipitation storms of 2023-10 → 2026-04 (UTC start / end), built by
`analysis.radar_utils.build_event_catalog` from ASOS present-weather codes and GHCN daily
totals. [`src/fetch_data/radar_events.py`](src/fetch_data/radar_events.py) fills the radar
caches for it:

```bash
python src/fetch_data/radar_events.py list                                  # the events
python src/fetch_data/radar_events.py fetch mrms                            # MRMS, every event
python src/fetch_data/radar_events.py fetch kokx --event 2024-03-23_rain    # KOKX, one event
python src/fetch_data/radar_events.py fetch mrms --day 2024-01-19           # any UTC day
python src/fetch_data/radar_events.py select --dataset v2                   # a catalog from v2's own sensors
```

`select` writes `dataset/raw/radar/radar_events_<dataset>.csv` (or `--outfile`). It ranks with
the GHCN stations of the chosen dataset, so its picks can differ from the repository's catalog.

## Dependencies

`eccodes` (MRMS GRIB2) and `metpy` (NEXRAD Level-3), both in `requirements.txt` and
`environment.yml`; see [SETUP.md](SETUP.md).
