# PROGRESS — Wet-bulb temperature support for phase analysis

Task: add wet-bulb temperature (Stull 2011) as a selectable temperature for the
precipitation-phase plots, plumbed via a `temp_type` ('air' | 'bulb') knob.

## Data check (done)
- ASOS netCDF (`asos_2023-10-01_2026-04-23.nc`) is grouped per station
  (EWR/JFK/LGA/NYC/TEB); each has `temperature` AND `dewpoint`. ✓
- WU PWS: 80 stations, `temperature` only, **no dewpoint**.
- Mesonet: empty in this build.
- ⇒ Wet-bulb is an ASOS quantity. Demo uses `phase_ref='ASOS'`, so the ASOS
  wet-bulb drives the temp axis / phase band / temp_guard for every panel.

## Plan
1. nycmesh_utils.py: `wet_bulb_stull(T_c, RH_pct)`, `rh_from_dewpoint(T_c, Td_c)`,
   `_network_temp_frame(net, freq, temp_type=...)` helper.
2. Plumb `temp_type='air'` through `_build_code_phase`, `_phase_temp_frame`,
   `plot_phase_temp_scatter`, `plot_precip_agreement_scatter` (backward compatible).
3. Notebook `weather_data_analysis.ipynb`: TEMP_TYPE knob in phase cells + one
   `bulb` demo cell + a markdown cell (Stull LaTeX, Jennings et al. 2018 cite).
4. Sanity: assert T_wb <= T_air everywhere.

## Log
- [start] data check complete; code read; beginning implementation.
- [1] Added to src/analysis/nycmesh_utils.py:
      - `rh_from_dewpoint(T_c, Td_c)`  — Magnus (Alduchov & Eskridge 1996), clipped [0,100]%.
      - `wet_bulb_stull(T_c, RH_pct)`  — Stull (2011); clamped to Tw<=T (see sanity).
      - `_network_temp_frame(net, freq, temp_type=...)` — per-station air or wet-bulb frame.
- [2] Plumbed `temp_type='air'` (default, backward-compatible) through
      `_build_code_phase`, `_phase_temp_frame`, `plot_phase_temp_scatter`,
      `plot_precip_agreement_scatter`. 'bulb' drives temp axis, temp-band fallback,
      and temp_guard; axis label → "Wet-bulb temperature (°C)".
      Existing callers (cml_baseline.build_hourly_context) unaffected — verified.
- [3] Notebook dataset/raw/full/paper/weather_data_analysis.ipynb:
      - TEMP_TYPE knob added to the phase-scatter cell and the precip-agreement cell.
      - New markdown cell (Stull LaTeX + Jennings et al. 2018 citation) + one demo
        cell repeating the scatter with temp_type='bulb'. nbformat validated (43 cells).
- [4] SANITY — Tw <= T_air:
      - Stull worked example T=20,RH=50 → Tw=13.7 ✓ ; sat T=15,RH=100 → 14.97 ✓ ;
        Magnus T=20,Td=9.3 → 50.1% ✓.
      - Raw Stull overshot T on 43/79,605 ASOS hourly cells by ≤0.042°C near
        saturation (RH≈100%). DEBUGGED by clamping `Tw=min(Tw,T)` inside
        wet_bulb_stull → 0 violations, max(Tw−T)=0.0. Mean depression T−Tw≈4.0°C.
- [done] End-to-end run: air + bulb phase scatters and bulb agreement render on
      the full window (2023-10-29 … 2026-03-04). Agreement (bulb) snow catch-ratio
      0.25 / rain 0.97 — PWS under-catches snow, as expected.

## Follow-up — wet-bulb in the CML CDF temperature splits
- `methods/cml_analysis.py`: added `add_wet_bulb(df)` (adds `temp_wb_c`) + `_pooled_rh`.
  Wet-bulb uses the stored air `temp_c` depressed by pooled RH ⇒ Tw <= temp_c by
  construction (verified True on all valid rows; mean depression 2.67 °C).
- RH backfill: ASOS RH (Magnus from dewpoint) is primary; where missing, the
  **WU PWS `relative_humidity`** (present on ~all 80 stations; `dew_point` on the
  KJFK/KLGA/KNYC airport stations) fills the gap. Result: **0 rows lack wet-bulb
  due to RH** (was 15,856 ASOS-only). The remaining 2.3 % NaN are hours with no
  air `temp_c` at all — not an RH problem, so ASOS 1-min wouldn't recover them.
- `temp_col` knob added to plot_cdf_by_phase_band / plot_cdf_band_by_phase /
  plot_cdf_temp_sweep; all three notebook temp-split cells (§2.2/2.2b/2.2c) now
  carry a `TEMP_COL` knob ('temp_c' | 'temp_wb_c') with a one-time add_wet_bulb.

## Result / next
Wet-bulb is an ASOS-only quantity (no PWS dewpoint), so phase_ref='ASOS' is required
for 'bulb'. Next experiment: quantify how many bins flip snow↔rain between air and
wet-bulb classification, and whether the wet-bulb temp_guard ceiling should drop from
6°C (air) toward ~1-2°C (Jennings 50% threshold is near 1°C wet-bulb).
