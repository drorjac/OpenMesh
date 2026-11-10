"""Write 03_showcase.ipynb, then run it (from tutorials/v2/):

    python make_showcase.py
    jupyter nbconvert --to notebook --execute --inplace 03_showcase.ipynb

The plotting and processing live in showcase.py, so each cell stays a line or two.
"""
import nbformat as nbf

cells = []


def md(s):
    cells.append(nbf.v4.new_markdown_cell(s.strip()))


def code(s):
    cells.append(nbf.v4.new_code_cell(s.strip()))


md("""
# 03 · Showcase: OpenMesh v2 from metadata to rain

A walk through the OpenMesh v2 record (NYC Mesh links, 2023-10-29 → 2026-11-01) with the weather references around it,
ending with rain rate estimated from the links themselves.

| | |
|---|---|
| **Record** | OpenMesh 2.0.0, Zenodo [10.5281/zenodo.23283445](https://doi.org/10.5281/zenodo.23283445): links, ASOS, METAR, GHCN-Daily, radar |
| **Paper** | Jacoby et al. (2026), ESSD 18, 5817–5836, [10.5194/essd-18-5817-2026](https://doi.org/10.5194/essd-18-5817-2026) |
| **Code** | [`showcase.py`](showcase.py) (all plots and the rain chain) · [`make_showcase.py`](make_showcase.py) (writes this notebook) |
| **Run** | from `tutorials/v2/`; the record is downloaded from Zenodo on the first run (~600 MB) into `dataset/raw/openmesh_v2/` (or set `OPENMESH_V2_DIR`). Needs pycomlink and poligrain; cartopy for the land on the maps (optional). |

Every number here comes from the public record. The gauge next to a path is the nearest ASOS station, often
5–15 km away: a coarse reference for one path, used here to show the method rather than to score it.

**Contents**
- **A · The record:** files, variables, metadata, which signal exists when
- **B · Three years at a glance:** sensors on the map, bands, coverage, growth, the raw level over three years
- **C · What rain does to the links:** a rain week, two rain days, 60 vs 5 GHz on one path
- **D · Rain rate from the links:** the processing chain step by step, then every link against ASOS and the radar
- **E · The reference sensors:** GHCN-Daily vs ASOS, METAR weather, the radar days
""")

code("""
import showcase as S
from IPython.display import display
S.style()
R = S.load()          # the v2 record (analysis.datasets, v2); downloaded from Zenodo when missing
""")

# ------------------------------------------------------------------------------------------------ A
md("""
---
# A · The record
## A1 · Sensors and files
One row per sensor type in the record.
""")
code("S.sensor_table(R)")
code("S.file_inventory(R)")

md("""
## A2 · The link file
`openmesh_links.nc` follows the [OpenSense CML convention](https://github.com/OpenSenseAction/OS_data_format_conventions/blob/main/netCDF_CML.adoc):
one `cml_id` per path between two NYC Mesh sites, four `sublink_id` slots per path (one per radio and direction),
and one time axis for all of them.
""")
code("""
print(dict(R.links.sizes), f'· time axis {len(R.links.time):,} stamps, {S.span(R.links.time)}')
S.variables_table(R.links)
""")
code("R.links.attrs")

md("""
## A3 · Sublinks
`links_metadata.csv` has one row per sublink. `sublink_1` / `sublink_2` carry the path's highest frequency in the two
directions (A: site_0 → site_1, B: back); on the 8 dual-frequency paths `sublink_3` / `sublink_4` carry the second
radio over the same path. Path 4 is one of them: 69.1 GHz and 5.8 GHz between the same two buildings.
""")
code("""
display(R.smeta[R.smeta.cml_id == '4'])
R.smeta[['frequency', 'length']].describe().round(0).T
""")
code("""
bands = R.paths.band.value_counts().rename(S.BAND_NAME).rename('paths').to_frame()
bands['sublinks'] = R.smeta.frequency.map(S.D.band_of).value_counts().rename(S.BAND_NAME)
display(bands)
R.paths.bands[R.paths.bands.str.contains('[+]')].value_counts().rename('dual-frequency paths').to_frame()
""")

md("""
## A4 · Which signal exists when
The network changed what it stores three times, so the file has three signals:
`rsl` (one instantaneous value per minute) to 2025-04-21, then `rsl_avg` and `rsl_max` over each polling window
(1 h, later 6 min). From 2024-07-15 to 2025-04-21 only the hour 00–01 UTC of each day was kept.
Table: million values per signal, band and year.
""")
code("S.values_per_year(R).rename(columns=str)")
code("S.stamps_per_day(R);")

md("## A5 · The reference files")
code("""
display(R.asos_st)
display(S.variables_table(R.asos).loc[list(R.asos.data_vars)])
display(R.ghcn_st)
print('METAR columns:', ', '.join(R.metar.columns))
R.radar_ev[['day', 'kind', 'asos_median_mm', 'radar_mean_mm', 'radar_max_mm']]
""")

# ------------------------------------------------------------------------------------------------ B
md("""
---
# B · Three years at a glance
## B1 · Every sensor on the map
5 GHz paths (grey) are the bulk of the network; the 24 GHz (orange) and 60 GHz (magenta) paths are the rain-sensitive ones.
""")
code("S.sensor_map(R);")

md("## B2 · Bands, carriers and lengths")
code("S.band_figure(R);")
code("""
R.paths[R.paths.band != 'C5'].sort_values('frequency', ascending=False)[
    ['frequency', 'length', 'bands', 'site_0_lat', 'site_0_lon', 'site_1_lat', 'site_1_lon']].round(4)
""")

md("""
## B3 · Coverage over time
Paths with any value per day, and gauges with rain data per day. The shading marks the three sampling periods of A4.
The first call reads the whole link file (about a minute); the result is cached in `cache/`.
""")
code("""
daily = S.paths_reporting_daily(R)
S.coverage_plot(R, daily);
""")
code("""
growth = daily.resample('QS').mean().round(0).astype(int)
growth.index = growth.index.to_period('Q').astype(str)
growth.rename(columns=S.BAND_NAME).T
""")

md("""
## B4 · Three years of received level
Daily median and range of `sublink_1` for one path per band (`rsl`, then `rsl_avg`). Steps in the level are
hardware or alignment changes; the deep daily minima of the 60 GHz path are rain.
""")
code("S.three_year_levels(R, {'V60': '7', 'K24': '36', 'C5': '92'});")

md("## B5 · Rain at the ASOS gauges per year")
code("""
ok = R.asos.rainfall_amount.where(R.asos.rainfall_flag == 0)
display(ok.groupby('time.year').sum(min_count=1).to_pandas().T.round(0).rename_axis('mm per year'))
ok.notnull().groupby('time.year').mean().to_pandas().T.round(2).rename_axis('share of usable minutes')
""")

# ------------------------------------------------------------------------------------------------ C
md("""
---
# C · What rain does to the links
## C1 · A rain week at 1-minute resolution
Path 7 (68 GHz, 2 km) in March 2024, both directions, with the nearest ASOS gauge.
""")
code("S.rsl_week(R, '7', '2024-03-19', '2024-03-25');")

md("""
## C2 · The 6-minute era: average and maximum
From 2025-04 each stamp carries the average (`rsl_avg`) and the maximum (`rsl_max`) over the window that ends at it.
In rain the two separate.
""")
code("S.avg_max_example(R, '5', '2026-03-05', '2026-03-07');")

md("""
## C3 · Rain day 2024-03-23 (1-minute data)
The heaviest day of the record (about 86 mm at the ASOS median). Quick look: attenuation is the median level of the
3 days before minus the level. Each panel is one 60 or 24 GHz path; shaded is the 5-min rain rate of the ASOS gauge
nearest its midpoint (named in the title, with its distance).
""")
code("""
att1 = S.attenuation_vs_prior(R, '2024-03-23')
cids1 = S.mmwave_paths_on(R, att1)
S.event_panels(R, '2024-03-23', att1, cids1);
""")
code("S.event_map(R, '2024-03-23', att1, cids1);")

md("""
## C4 · Rain day 2026-03-06 (6-minute averages)
Two years later many more 60 GHz paths report.
""")
code("""
att2 = S.attenuation_vs_prior(R, '2026-03-06')
cids2 = S.mmwave_paths_on(R, att2)
S.event_panels(R, '2026-03-06', att2, cids2);
""")
code("S.event_map(R, '2026-03-06', att2, cids2, radar=False);")

md("""
## C5 · Same path, two frequencies
On the dual-frequency paths the 60 GHz and the 5 GHz radios see the same rain over the same path.
""")
code("""
fig, dual = S.dual_frequency(R, '2026-03-06', att2)
print('60 GHz + 5 GHz paths:', dual)
""")

# ------------------------------------------------------------------------------------------------ D
md("""
---
# D · Rain rate from the links
## D1 · The processing chain
The standard OpenSense chain, with the [pycomlink](https://github.com/pycomlink/pycomlink) functions for every step
(`S.rain_chain`):

| step | what | function |
|---|---|---|
| 0 | blackout gaps: missing values bounded by levels near the floor are set to the floor (signal lost in heavy rain) | `pycomlink.processing.blackout_gap_detection` |
| 1 | TRSL = −RSL: the record has no transmitted level, so a constant TSL drops out with the baseline | |
| 2 | wet/dry: rolling standard deviation of TRSL over 60 min above 0.8 dB (Schleiss & Berne 2010) | `xarray.rolling().std()` |
| 3 | baseline: the dry level, held constant through each wet period | `pycomlink.processing.baseline.baseline_constant` |
| 4 | observed attenuation A_obs = TRSL − baseline | |
| 5 | wet-antenna attenuation removed: Schleiss et al. 2013 (default), Leijnse et al. 2008, Pastorek et al. 2021 | `pycomlink.processing.wet_antenna` |
| 6 | rain rate R from A with the ITU-R P.838 power law A = k·R^α·L | `pycomlink.processing.k_R_relation.calc_R_from_A` |

The same code runs on 1-min `rsl` and on 6-min `rsl_avg` (windows are set in minutes).
The radar along each path comes from `poligrain` (`GridAtLines`).
""")

md("## D2 · Step by step on one path: cml 19, 67 GHz, 2.8 km, 2024-03-23")
code("""
ch = S.rain_chain(R, '19', '2024-03-23')
g19, st19, d19 = S.gauge_day(R, '2024-03-23', '19')
S.chain_panel(ch, g19, 'cml 19 on 2024-03-23: from received level to rain rate', gauge_label=f'ASOS {st19}, {d19:.0f} km away, 5 min');
print(f"link day total {float(ch.R.mean('sublink_id').sum())/60:.1f} mm · ASOS {st19} ({d19:.0f} km) {g19.sum()/12:.1f} mm")
""")

md("""
## D3 · Blackouts
In the heaviest rain the 60 GHz signal drops below what the radio reports and the value is missing. Left out, those
minutes count as no rain; filled with the floor they give a lower bound. Minutes filled per path on 2024-03-23:
""")
code("""
bo = {c: int(S.rain_chain(R, c, '2024-03-23', sublinks=S.top_sublinks(R, att1, c)).blackout.sum('time').max()) for c in cids1}
S.pd.Series(bo, name='blackout minutes (max over sublinks)').to_frame().T
""")

md("""
## D4 · Settings against the references
Day totals of every mm-wave path, under six chain settings (wet/dry from the link alone, or from the nearest ASOS
gauge; no wet-antenna correction, Schleiss, Leijnse). `ASOS` is the nearest gauge (`gauge`, `gauge_km`);
`radar` is MRMS averaged along the path (2024-03-23 only). The heatmap and the summary use the radar where there is
one, else ASOS.
""")
code("""
SETTINGS = {
    'rsd · no WAA':   dict(wet_method='rsd', waa=None),
    'rsd · Schleiss': dict(wet_method='rsd', waa='schleiss'),
    'rsd · Leijnse':  dict(wet_method='rsd', waa='leijnse'),
    'gauge · no WAA':   dict(wet_method='gauge', waa=None),
    'gauge · Schleiss': dict(wet_method='gauge', waa='schleiss'),
    'gauge · Leijnse':  dict(wet_method='gauge', waa='leijnse'),
}
tables = {d: S.chain_day_totals(R, d, SETTINGS) for d in ['2024-03-23', '2026-03-06']}
display(tables['2024-03-23'])
tables['2026-03-06']
""")
code("""
S.ratio_heatmap({'2024-03-23 vs radar': tables['2024-03-23'].assign(ref=tables['2024-03-23'].radar),
                 '2026-03-06 vs ASOS': tables['2026-03-06'].assign(ref=tables['2026-03-06'].ASOS)}, SETTINGS, ref='ref');
summary = S.pd.DataFrame({'2024-03-23 / radar': tables['2024-03-23'][list(SETTINGS)].div(tables['2024-03-23'].radar, axis=0).median(),
                          '2026-03-06 / ASOS': tables['2026-03-06'][list(SETTINGS)].div(tables['2026-03-06'].ASOS, axis=0).median()}).round(2)
summary.rename_axis('median of link / reference')
""")

md("""
Reading the table:
- **2024-03-23 against the radar:** with no wet-antenna correction the median path matches MRMS (ratio about 1.0);
  with the Schleiss or Leijnse defaults it comes out about 0.6–0.7. Paths of 1.2–2.8 km (9, 18, 19) land within
  about 10 % of the radar under the Schleiss setting.
- **Short paths (under ~1.1 km, e.g. 20 and 32):** the wet-antenna term is a large share of the attenuation, so the
  choice of model changes the day total by a factor of 2–3.
- **Long paths in heavy rain:** cml 12 (4.4 km) sits at its floor for about 230 minutes (D3); the attenuation is
  capped and the total is low.
- **24 GHz:** the attenuation rises slowly, so the rolling-std flag misses most of it (cml 35: 2–4 mm against 66 mm of
  radar); the gauge-based flag recovers part of it, but only when the gauge itself has data (cml 36's nearest
  gauge, EWR, reports 0.3 mm that day, so its gauge flag stays dry).
- **2026-03-06 (6-min averages):** the only reference is ASOS NYC, about 10 km from most paths, so the spread is
  wide; the shortest paths drop to near zero once the wet antenna is removed.
""")

md("## D5 · Hour by hour: link, ASOS and radar")
code("S.hourly_comparison(R, '2024-03-23', ['19', '7', '9', '18']);")
code("S.hourly_comparison(R, '2026-03-06', ['5', '10', '25', '7']);")

md("""
## D6 · Attenuation per km against rain rate
Hourly, every 60 GHz path on both days: specific rain attenuation from the chain (after the wet-antenna correction)
against the nearest ASOS gauge, with the ITU-R P.838 curves. The gauge is kilometres from the path, so expect scatter.
""")
code("""
H = S.gamma_vs_rain(R, ['2024-03-23', '2026-03-06'])
print(f"{len(H)} path-hours · Spearman correlation {H[['R', 'gamma']].corr('spearman').iloc[0, 1]:.2f}")
""")

# ------------------------------------------------------------------------------------------------ E
md("""
---
# E · The reference sensors
## E1 · GHCN-Daily against ASOS
GHCN-Daily (CoCoRaHS volunteers and COOP gauges) reports days that end in the morning local time, ASOS here UTC
days: single days scatter, months agree.
""")
code("S.reference_monthly(R);")

md("## E2 · METAR: what the observers reported")
code("""
wx = R.metar.present_weather.fillna('').str.split().explode()
codes = wx.str.replace(r'^[+-]|VC', '', regex=True).replace('', S.np.nan).dropna()
codes.value_counts().head(12).rename('reports').to_frame().T
""")

md("## E3 · The 10 radar days")
code("S.radar_days_grid(R);")

md("""
---
**More:** [00_quickstart](00_quickstart.ipynb) (open the files with plain xarray) · [01_data_overview](01_data_overview.ipynb)
· [02_analysis](02_analysis.ipynb) (rain over all 10 radar days) · file formats in [`dataset/formats/`](../../dataset/formats/)
· every file in [`DETAILS.md`](../../DETAILS.md).
""")

nb = nbf.v4.new_notebook(metadata={'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
                                   'language_info': {'name': 'python'}})
nb.cells = cells
nbf.write(nb, '03_showcase.ipynb')
print('wrote 03_showcase.ipynb,', len(cells), 'cells')
