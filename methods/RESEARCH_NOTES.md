# Research notes — ASOS QC and MRMS radar comparison (2026-09)

Covers the ASOS heated-gauge melt QC (`src/analysis/nycmesh_utils.py`) and the MRMS
radar track (`src/fetch_data/mrms/`, `src/analysis/radar_utils.py`,
`tutorials/radar_0*.ipynb`). Numbers are from the 15-event catalog in
`dataset/meta/radar_events.csv` unless stated otherwise.

## What worked

- **Gauge-melt QC.** Flagging 1-min ASOS rain with no wet present-weather code within
  ±30 min and (T ≤ 1 °C or frozen code in the prior 72 h) removes the heated-gauge
  snowmelt artefact (up to 234 mm/day on days NOAA recorded 0 mm). Station-level
  raw/GHCN precipitation ratios move from 0.98–1.77 to 0.96–1.10 (1,688 station-days).
- **MRMS fetch.** The pcpn_maps client (AWS `noaa-mrms-pds`, IEM fallback, ecCodes
  decode, per-day NYC crop cache) fetched all 8,712 fields for the 15 events with zero
  missing; the whole cache is 28 MB.
- **Event catalog.** Network-wide segmentation of ASOS codes + NOAA daily magnitudes
  gives 5 snow / 5 rain / 5 mix events without hand-picking; it recovers the known big
  storms (2026-02-22 blizzard, 55 cm; 2024-03-23 rain, 85 mm).
- **Hourly comparison.** Against MRMS Pass 2, gauges reach NRMSE 0.51 (Mesonet),
  0.77 (ASOS), 1.27 (WU PWS) in rain. Event totals of MRMS Pass 2 match NOAA daily
  within 2–5 % in every class.

- **Rainfall maps** (`src/analysis/rain_maps.py`, from pcpn_maps). IDW maps scored
  against MRMS Pass 2 within 2 km of sensors (median over the 15 events): PWS / all-gauge
  maps NRMSE ≈ 0.7 in rain, 1.1 in mix, event totals within ~5 %; CML maps +120 % in
  rain. In the peak hour CML is too low (lost signal), in light hours too high.

## Ambiguities and how they were decided

| Question | Decision | Why |
|---|---|---|
| "nrmse" in the request | Read as **MRMS** (the radar source), and NRMSE made the headline metric | both fit; the radar code in pcpn_maps / snow_paper is MRMS |
| Which radar code to port | pcpn_maps `radar/` (not snow_paper's two MRMS copies) | tested, AWS + IEM fallback, in-memory decode, cache; snow_paper duplicates it |
| NEXRAD HCA (snow_paper n8) | **Not ported** | needs vendored MetPy; beam is ~1.5 km above the links; a separate study |
| "Most precipitation / snow" | snow ranked by GHCN snowfall, rain and mix by GHCN precipitation | automated gauges under-catch snow (ASOS −46 %, PWS −86 %) |
| What "mix" means | cold (T_min ≤ 2 °C) events with both liquid and frozen codes | warm ASOS "P" codes are thunderstorms — the first draft picked an August storm |
| Blizzard split by a lull | same-class events < 12 h apart merged | otherwise 2026-02-22/23 counted twice |
| Reference for hourly scores | MRMS Pass 2, **plus** radar-only as an independent check | Pass 2 is corrected with gauges incl. ASOS → circular |
| Reference for snow totals | NOAA GHCN daily | manual QC and melted snow water; tipping buckets fail in snow |
| CML baseline | `att_drymed` default | best of the four on rain events (NRMSE 2.49 vs 2.62–3.15) |
| CML bands | ≥ 20 GHz only (120 of 290 sublinks) | sub-6 GHz rain attenuation is below the noise |
| ASOS hours during outages | NaN (< 90 % minutes) | the IEM 1-min archive has 30–40 % coverage at 4 of 5 airports in the 2026-02 blizzard |
| Which pcpn_maps map code to port | general IDW, accumulation, distances, map scores, retrieval QC, figures | its CML estimators need PyNNcml / pycomlink; OpenMesh already has the attenuation → rain step; the implementation_1/2 replicas only reproduce old results |
| Map scoring area | cells ≤ 2 km from a sensor | beyond that IDW extrapolates (one link painted the whole northern Bronx) |
| CML retrieval QC | flag, do not auto-drop; missing-data links not counted as dry neighbours | pcpn_maps' rule; OpenMesh has many inactive links that would fake "neighbours dry" |

## Caveats a reviewer will raise

- Map scores favour smooth maps: MRMS is smooth at 1 km, so IDW power 1 "wins"
  (gauge NRMSE 0.47 vs 0.69 at power 2) partly for that reason.
- Removing QC-flagged CML links raises map correlation (0.62 → 0.72) but also bias:
  the dead links were offsetting the over-estimating ones.

- ASOS vs GHCN agreement (NRMSE 0.00) is not validation: GHCN at the airports is the
  ASOS gauge. MRMS Pass 2 vs ASOS is partly circular too; radar-only shows the
  gauges' NRMSE rising to ~1.6–2.0 and a 20–30 % radar low bias.
- CML rain is inverted with the ITU power law and no wet-antenna correction; in snow
  and mix the result is attenuation-equivalent rain, not a precipitation estimate.
- 15 events, 5 per class: class-level scores rest on few storms; per-event variance
  is large (see `compare_sensors(by=('event', 'network'))`).
- MRMS PrecipFlag has no mixed class, so phase agreement for ASOS "mix" is undefined.

## Next experiment

1. **CML wet-antenna + snow model.** Fit a wet-antenna offset on the rain events
   against `radar_mm` path averages (`compare_links`-style), then test whether a
   separate attenuation–SWE relation for snow brings CML NRMSE in snow below the
   PWS level (1.6).
2. **Independent reference.** Repeat §2–3 of radar tutorial 3 with `radar_only_mm`
   bias-adjusted by leave-one-gauge-out Mesonet only, so no reference has seen the
   sensor it scores.
3. **Wire the melt QC into snow_paper**, which has its own copy of
   `paper_snow_utils.py` and still uses raw ASOS rain.
