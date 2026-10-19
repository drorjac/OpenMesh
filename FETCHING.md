# Radar Data Fetching

OpenMesh provides two complementary radar sources:

## MRMS (Multi-Radar/Multi-Sensor)

**Source:** NOAA MRMS, AWS `noaa-mrms-pds` bucket (fallback: IEM mtarchive)  
**Coverage:** NYC metropolitan area (40.48–40.93 N, 74.27–73.68 W)  
**Products:** 
- Quantitative precipitation estimate (QPE): 1H gauge-corrected, 15-min radar-only
- Precipitation rate: 2-min instantaneous
- Precipitation type (PrecipFlag): rain, snow, rain+hail, etc.
- Radar quality index

**Code:** `src/fetch_data/mrms/`  
**API:** `from fetch_data.mrms import MRMSClient, NYC; client.load("MultiSensor_QPE_01H_Pass2", start, end, NYC)`

### Cache
- **Location:** `dataset/raw/radar/mrms/cache/`
- **Structure:** Per-product / per-domain / per-day NetCDF files (~kB each)
- **Integrity:** Files confirmed absent (HTTP 404) are cached to avoid re-requests

---

## KOKX NEXRAD Level III

**Source:** AWS `unidata-nexrad-level3` bucket (NOAA Weather and Radar Center)  
**Radar:** Upton, NY (OKX), ~100 km from NYC; beam centre ~1.5 km AGL over the links  
**Products:**
- HHC: Hydrometeor class (dry snow, wet snow, rain, hail, graupel, ice crystals, etc.)
- N0B: Base reflectivity (dBZ), 0.25 km range gates
- N0X: Differential reflectivity (ZDR dB)
- N0C: Correlation coefficient

**Code:** `src/fetch_data/nexrad/kokx.py`  
**API:** `from fetch_data.nexrad import kokx; kokx.fetch_window(start, end); kokx.load(start, end, "HHC")`

### Sampling
- **Links:** 5 sample points along each microwave link path
- **Grid:** 0.01° regular grid over NYC (40.55–40.92 N, 74.10–73.70 W)
- **Cache:** `dataset/raw/radar/nexrad/cache/`
- **Format:** Per-product-hour parquet (one scan per 10-min STEP)

### Product Details

**HHC Hydrometeor Classes:**
```
40 = dry snow    50 = wet snow    60 = rain    70 = heavy rain
80 = big drops   90 = graupel    100 = hail    30 = ice crystals
```

Wet snow at KOKX (1.5 km AGL) indicates melting layer is at beam height; does not necessarily mean precipitation was wet on the ground.

---

## Event Fetching

### Select significant events
```bash
python src/fetch_data/radar_events.py select
```
→ `dataset/meta/radar_events.csv` (top 5 rain + top 5 snow + top 5 mixed-precip days)

### Fetch radar for all events
```bash
python src/fetch_data/radar_events.py fetch mrms      # MRMS for all events
python src/fetch_data/radar_events.py fetch kokx       # KOKX for all events
```

### Fetch for a single day
```bash
python src/fetch_data/radar_events.py fetch mrms --day 2024-01-19 --kind snow
python src/fetch_data/radar_events.py fetch kokx --day 2024-01-19 --kind rain
```

---

## Region & Coverage Validation

### NYC Bounding Boxes

| Domain | Lat Min | Lat Max | Lon Min | Lon Max | Purpose |
|--------|---------|---------|---------|---------|---------|
| **NYC** | 40.48 | 40.93 | -74.27 | -73.68 | MRMS: five boroughs + margin |
| **OpenMesh links** | 40.5719 | 40.8604 | -74.0437 | -73.8764 | KOKX: link locations ± 3 km |
| **KOKX grid** | 40.55 | 40.92 | -74.10 | -73.70 | KOKX: city-scale grid sampling |

Both radars cover the OpenMesh link domain with 0.3–0.5° margin.

### Distance from NYC
- **MRMS:** Composite multi-radar (nearest ~200 km away)
- **KOKX:** Single radar in Upton, NY (~100 km, beam 1.5 km AGL)

---

## Comparison with Other Sensors

### When to use which radar
- **MRMS QPE:** Model-corrected surface precipitation; best for hydrologic applications
- **KOKX HHC:** Hydrometeor classification; best for microphysics (snow vs. rain phase)
- **KOKX reflectivity:** Radar backscatter; best for storm structure
- **CML attenuation:** Fine-scale rain paths along link; best for validation

### Time conventions
- **MRMS:** Hourly accumulations labelled by END of period (12:00 = 11:00–12:00 UTC)
- **KOKX:** One scan per product (HHC, N0B, etc.) every 5–10 min, timestamped by valid time

---

## Code Structure

```
src/fetch_data/
├── radar_events.py          # Event selection and multi-radar fetching
├── mrms/                    # MRMS module (client, domain, products, maps)
│   ├── client.py           # Download & cache
│   ├── domain.py           # Bounding boxes & spatial tools
│   ├── products.py         # Product registry
│   └── maps.py             # Plotting & sample extraction
└── nexrad/                  # KOKX NEXRAD module
    ├── kokx.py             # Fetch & cache HHC, N0B, N0X, N0C
    └── __init__.py         # API exports

src/analysis/
├── radar_utils.py          # Event catalog, merging, comparison with sensors
└── rain_maps.py            # MRMS rainfall map tools
```

---

## Dependencies

**Required:** `eccodes` (MRMS GRIB2 decoding), `metpy` (KOKX Level-3 parsing), `xarray`, `pandas`, `requests`

```bash
pip install eccodes metpy xarray pandas requests
```

**Optional:** `pyproj` (advanced projections), `cartopy` (mapping)
