"""Write the three OpenMesh notebooks, then run them:

    python make_notebooks.py [00 01 ...]          # all, or only those named
    jupyter nbconvert --to notebook --execute --inplace 0*.ipynb

They read the record through analysis.datasets (D.use('v2')); the helpers they call live in analysis.v2
(plots, quality, checks), so each cell stays short. On first run om.setup() downloads the
record from Zenodo (~600 MB, analysis.datasets.ensure('v2')) unless it is already installed.
"""
import sys

import nbformat as nbf

KERNEL = {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}}


def nb(cells, path):
    n = nbf.v4.new_notebook(metadata=KERNEL)
    n.cells = [nbf.v4.new_markdown_cell(c[3:].strip()) if c.startswith("md:") else nbf.v4.new_code_cell(c.strip())
               for c in cells]
    nbf.write(n, path)


SETUP = """
import sys
import numpy as np, pandas as pd, matplotlib.pyplot as plt, xarray as xr
from pathlib import Path
sys.path.insert(0, str(Path("../..").resolve() / "src"))   # the repo's src/
from analysis import v2 as om
DATA = om.setup()                              # D.use('v2'); downloads the record on first run (D.ensure)
meta = om.link_meta()                          # one row per path
"""

# ------------------------------------------------------------------------------------------- 00 quickstart
QUICK = [
    """md:# 00 · Quickstart

Open the files with plain xarray, choose an event and a link, and plot them next to the nearest rain gauge.
Everything is chosen on the netCDF itself, as in the OpenSense examples: `sel(time=slice(...))` for the event and
`sel(cml_id=...)` for a path; a condition such as `links.frequency > 50_000` picks a group of paths.
Only the network overview in section 2 uses the repo's `analysis.v2` helpers.
Set the next cell, then run all cells.""",
    """
# ---- choose ----
EVENT = "2024-03-23"        # a day (UTC); the table below lists the 10 radar days (5 rain, 5 snow)
DAYS_BEFORE = 1             # days shown before the event day
DAYS_AFTER = 2              # days shown after it
CML = "7"                   # a path (cml_id), "1" to "372"
""",
    """
import os, sys
from pathlib import Path
import numpy as np, pandas as pd, matplotlib.pyplot as plt, xarray as xr

# The record in dataset/raw/openmesh_v2/ (or OPENMESH_V2_DIR), downloaded from Zenodo on first run.
sys.path.insert(0, str(Path("../..").resolve() / "src"))
from analysis import v2 as om
DATA = om.setup()
links = xr.open_dataset(DATA / "data" / "links" / "openmesh_links.nc")

START = pd.Timestamp(EVENT) - pd.Timedelta(days=DAYS_BEFORE)
END = pd.Timestamp(EVENT) + pd.Timedelta(days=DAYS_AFTER)


n_sublinks = int(links.frequency.notnull().sum())        # sublinks in use have a frequency
first_day, last_day = str(links.time.values[0])[:10], str(links.time.values[-1])[:10]
print(f"{links.sizes['cml_id']} paths, {n_sublinks} sublinks, {links.sizes['time']:,} time stamps, "
      f"{first_day} to {last_day} UTC")

radar_days = pd.read_csv(DATA / "data" / "weather" / "radar" / "radar_events.csv")
radar_days[["kind", "day", "asos_median_mm", "radar_mean_mm"]]
""",
    """md:## 1. The links file

* `cml_id`: a path between two NYC Mesh buildings. `sublink_id`: a frequency and a direction on it, two per
  frequency; `sublink_1` is the path's highest frequency. Seven paths are dual-frequency (`sublink_3`, `sublink_4` at
  5 GHz). `frequency` (MHz) is given per path and sublink, `length` (m) per path.
* `time`: the stamps the network stored, one per minute to 2025-04-21 (only 00–01 UTC each day from 2024-07-15),
  then one per poll.
* `rsl` (instantaneous) up to 2025-04-21; after that `rsl_avg` and `rsl_max` over the window that ends at each stamp.
  `rsl.fillna(rsl_avg)` gives one level over the whole record.""",
    """
rows = []
for name in ["rsl", "rsl_avg", "rsl_max", "frequency", "length"]:
    var = links[name]
    rows.append({"variable": name, "long name": var.attrs.get("long_name", ""), "units": var.attrs.get("units", ""),
                 "dimensions": " x ".join(var.dims)})
pd.DataFrame(rows).set_index("variable")
""",
    """md:## 2. The network

Per band: paths, sublinks, channels and lengths.""",
    """om.plots.network_table(om.link_meta())""",
    """md:Where the paths are (the chosen one in black) and what they carry.""",
    """om.plots.network_map(om.link_meta(), highlight=CML)""",
    """om.plots.link_features(om.link_meta())""",
    """md:## 3. The chosen link around the event

`links.sel(cml_id=CML, time=slice(START, END))`: every sublink of the path; dots are the stored values, the line the
hourly mean. Grey: the event day.""",
    """
path = links.sel(cml_id=CML, time=slice(START, END))
level = path.rsl.fillna(path.rsl_avg)                   # one level: rsl to 2025-04-21, rsl_avg after

# The sublinks this path uses: the ones with a frequency (the others are empty slots)
used_sublinks = [s for s in path.sublink_id.values if np.isfinite(float(path.frequency.sel(sublink_id=s)))]

fig, ax = plt.subplots(figsize=(14, 4))
for sublink in used_sublinks:
    values = level.sel(sublink_id=sublink)
    hourly_mean = values.resample(time="1h").mean()
    ghz = float(path.frequency.sel(sublink_id=sublink)) / 1000
    dots, = ax.plot(values.time, values, ".", markersize=2, alpha=0.4)
    ax.plot(hourly_mean.time, hourly_mean, color=dots.get_color(), label=f"{sublink}, {ghz:.2f} GHz")

event_start = pd.Timestamp(EVENT)
ax.axvspan(event_start, event_start + pd.Timedelta("1D"), color="0.9", zorder=0)   # the event day in grey
ax.set_ylabel("received level (dBm)")
ax.set_title(f"cml {CML}, {float(path.length):,.0f} m, {START:%Y-%m-%d} to {END:%Y-%m-%d}")
ax.legend()
plt.show()
""",
    """md:## 4. Any path, sublink by sublink

Set `ONE` to any `cml_id`: one panel per sublink (frequency and direction), with every signal the file holds there.""",
    """
ONE = CML                       # any path, e.g. "8" (dual-frequency: 60 and 5 GHz)

one_path = links.sel(cml_id=ONE, time=slice(START, END))
sublinks = [s for s in one_path.sublink_id.values if np.isfinite(float(one_path.frequency.sel(sublink_id=s)))]

fig, axes = plt.subplots(len(sublinks), 1, figsize=(14, 2.4 * len(sublinks)), sharex=True, squeeze=False)
for ax, sublink in zip(axes[:, 0], sublinks):
    one = one_path.sel(sublink_id=sublink)
    for signal in ["rsl", "rsl_avg", "rsl_max"]:            # every signal the file holds for this sublink
        n_values = int(one[signal].notnull().sum())
        if n_values > 0:
            ax.plot(one.time, one[signal], ".", markersize=2, label=f"{signal} ({n_values} values)")
    ghz = float(one.frequency) / 1000
    ax.set_title(f"cml {ONE}, {sublink}, {ghz:.2f} GHz, {one.polarization.values}", loc="left", fontsize=9)
    ax.set_ylabel("dBm")
    ax.legend(fontsize=8, loc="lower left")
ax.set_xlim(START, END)
plt.tight_layout(); plt.show()
""",
    """md:## 5. Rain at the nearest ASOS gauge

`rainfall_amount` where `rainfall_flag == 0`. The gauges are often several km from a link.""",
    """
# The ASOS gauge nearest to the middle of the chosen path
asos = xr.open_dataset(DATA / "data" / "weather" / "asos" / "openmesh_asos.nc")
path_lat = float(path.site_0_lat + path.site_1_lat) / 2
path_lon = float(path.site_0_lon + path.site_1_lon) / 2
km_per_degree = 111.0                                   # one degree of latitude; longitude shrinks with cos(latitude)
distance_km = km_per_degree * np.hypot(asos.lat - path_lat, (asos.lon - path_lon) * np.cos(np.radians(path_lat)))
station = str(distance_km.idxmin("id").values)
gauge = asos.sel(id=station, time=slice(START, END))

# Rain rate in mm/h: only the usable minutes (rainfall_flag == 0), summed per 10 minutes.
# A 10-minute step with fewer than 5 usable minutes stays empty instead of counting as 0.
# Each step is labelled by its end, as the minutes are (closed and labelled on the right).
rain_mm = gauge.rainfall_amount.where(gauge.rainfall_flag == 0)
rain_per_10min = rain_mm.resample(time="10min", closed="right", label="right").sum(min_count=5)
rain_rate = rain_per_10min * 6                          # six 10-minute steps per hour

# Plot: the link's received level on top, the gauge's rain below
fig, (ax_link, ax_rain) = plt.subplots(2, 1, figsize=(14, 5), sharex=True, gridspec_kw=dict(height_ratios=[3, 2]))
for sublink in used_sublinks:
    ax_link.plot(level.time, level.sel(sublink_id=sublink), ".", markersize=2, label=sublink)
ax_link.set_ylabel("received level (dBm)")
ax_link.set_title(f"cml {CML} and ASOS {station}, {float(distance_km.min()):.1f} km away")
ax_link.legend()
ax_rain.bar(rain_rate.time, rain_rate, width=-pd.Timedelta("10min"), align="edge")   # bar spans the 10 minutes before its end
ax_rain.set_ylabel("rain (mm/h)")
plt.tight_layout(); plt.show()
""",
]

# ------------------------------------------------------------------------------------- 01 files and links
FILES_LINKS = [
    """md:# 01 · Data overview: files, network, availability and quality

What is in the record, whether the tables agree with the files and the OpenSense conventions, where the links are,
how complete they are, and the quality of their data.""",
    SETUP,
    """md:## 1. Files and dates""",
    """
pd.DataFrame([(str(f.relative_to(DATA)), round(f.stat().st_size / 1e6, 2)) for f in sorted(DATA.rglob("*"))
              if f.is_file()], columns=["file", "MB"])
""",
    """cov = om.plots.valid_periods()""",
    """md:## 2. What each file holds, and how to open it

Every file opens with plain xarray (netCDF) or pandas (CSV); the repo's code is not needed for this.

**Links** (`data/links/openmesh_links.nc`, OpenSense CML): one `cml_id` per path, one `sublink_id` per frequency and
direction. Signals: `rsl` (instantaneous, one per minute, to 2025-04-21), `rsl_avg` and `rsl_max` (over the window
that ends at each stamp; `rsl_max` also in the hour-a-day months). Per sublink: `frequency`, `polarization`; per path:
the two ends, `length`.""",
    """
links = xr.open_dataset(DATA / "data" / "links" / "openmesh_links.nc")
links
""",
    """
rows = []
for name in list(links.data_vars) + ["frequency", "length", "polarization"]:
    var = links[name]
    rows.append({"variable": name, "long name": var.attrs.get("long_name", ""), "units": var.attrs.get("units", ""),
                 "dimensions": " x ".join(var.dims)})
pd.DataFrame(rows).set_index("variable")
""",
    """md:**Rain gauges** (`data/weather/asos/openmesh_asos.nc`, OpenSense PWS): five airport stations, one row per minute. Use
`rainfall_amount` where `rainfall_flag == 0`; `precip_category` is the station's present-weather type.""",
    """
asos = xr.open_dataset(DATA / "data" / "weather" / "asos" / "openmesh_asos.nc")
rows = []
for name in asos.data_vars:
    var = asos[name]
    rows.append({"variable": name, "long name": var.attrs.get("long_name", ""), "units": var.attrs.get("units", "")})
pd.DataFrame(rows).set_index("variable")
""",
    """md:**Radar** (`data/weather/radar/openmesh_radar_<kind>_<day>.nc`, one file per day, MRMS on a 0.01° grid): hourly and
15-min rain, and the 10-min precipitation type. `data/weather/radar/radar_events.csv` lists the days.
**Daily gauges** (`data/weather/ghcn/ghcn_daily.csv`): one row per station and day, with the day's window in UTC.""",
    """
first_radar_file = sorted((DATA / "data" / "weather" / "radar").glob("*.nc"))[0]
radar = xr.open_dataset(first_radar_file)
print(radar)

ghcn = pd.read_csv(DATA / "data" / "weather" / "ghcn" / "ghcn_daily.csv")
ghcn.head(3)
""",
    """md:## 3. The raw series of a few days

Every value the file holds for one path and a few days, without any processing: each sublink, each signal. Below,
the rain and the temperature at the nearest airport gauge. Set the path and the days, then run the next cells.""",
    """
# ---- choose ----
CML = "7"                                  # a path, "1" to "372"
START, END = "2024-03-22", "2024-03-25"    # UTC
""",
    """
path = links.sel(cml_id=CML, time=slice(START, END))
used_sublinks = [s for s in path.sublink_id.values if np.isfinite(float(path.frequency.sel(sublink_id=s)))]

# The ASOS gauge nearest to the middle of the path
path_lat = float(path.site_0_lat + path.site_1_lat) / 2
path_lon = float(path.site_0_lon + path.site_1_lon) / 2
km_per_degree = 111.0                                   # one degree of latitude; longitude shrinks with cos(latitude)
distance_km = km_per_degree * np.hypot(asos.lat - path_lat, (asos.lon - path_lon) * np.cos(np.radians(path_lat)))
station = str(distance_km.idxmin("id").values)
gauge = asos.sel(id=station, time=slice(START, END))
rain_mm = gauge.rainfall_amount.where(gauge.rainfall_flag == 0)    # usable minutes only

# One panel per sublink with every signal it holds, then the gauge's rain and temperature
n_panels = len(used_sublinks) + 2
fig, axes = plt.subplots(n_panels, 1, figsize=(14, 2.2 * n_panels), sharex=True)
for ax, sublink in zip(axes, used_sublinks):
    one = path.sel(sublink_id=sublink)
    for signal in ["rsl", "rsl_avg", "rsl_max"]:
        n_values = int(one[signal].notnull().sum())
        if n_values > 0:
            ax.plot(one.time, one[signal], ".", markersize=2, label=f"{signal} ({n_values} values)")
    ghz = float(one.frequency) / 1000
    ax.set_title(f"cml {CML}, {sublink}, {ghz:.2f} GHz", fontsize=9, loc="left")
    ax.set_ylabel("dBm")
    ax.legend(fontsize=8, loc="lower left")

ax_rain, ax_temp = axes[-2], axes[-1]
ax_rain.bar(rain_mm.time, rain_mm, width=pd.Timedelta("1min"), color="tab:blue")
ax_rain.set_ylabel("mm per minute")
ax_rain.set_title(f"ASOS {station} ({float(distance_km.min()):.1f} km away): rain", fontsize=9, loc="left")
ax_temp.plot(gauge.time, gauge.temperature, color="tab:red")
ax_temp.set_ylabel("°C")
ax_temp.set_title("temperature", fontsize=9, loc="left")
plt.tight_layout(); plt.show()
""",
    """md:## 4. Sampling

One row per minute to 2025-04-21, then one per poll (hourly to 2025-07, hourly or 6 min from 2025-08, 6 min from 2026-02). `rsl_avg` and
`rsl_max` cover the window from the previous row to this one, except on the hourly days from 2025-08-31 to
2026-01-17, where the values match the hour after the stamp (the record's README.md, "How the link data is sampled").""",
    """om.plots.windows()""",
    """md:## 5. The tables against the files, and the OpenSense conventions

`om.checks.convention("links")` and `om.checks.convention("asos")` give the variable-by-variable detail.""",
    """om.checks.record()""",
    """md:## 6. Directional links: counts, locations and lengths""",
    """from importlib import reload
reload(om.plots)
om.plots.network_table(meta)""",
    """# Reload the plotting helpers so edits are picked up in an already-running kernel.
from importlib import reload
reload(om.plots)

PWS = "all"  # "all", a list of station IDs, or False to hide PWS
om.plots.network_map(meta, pws=PWS)""",
    """om.plots.network_density(meta)""",
    """om.plots.link_features(meta)""",
    """md:## 7. Availability

From an hourly summary of the whole links file (`om.hourly()`, a few minutes).""",
    """
H = om.hourly()
om.plots.availability(meta, H)
""",
    """md:## 8. Data quality

**Coverage** per path and day, and the days on which most of the network was silent.""",
    """om.quality.coverage(H, meta)""",
    """om.quality.outages(H)""",
    """md:**Levels** per band.""",
    """om.quality.levels(H, meta)""",
    """md:**Anomalies**: five checks on the hourly summary of the whole record. Each row says what is checked, why it matters, how many paths show it and how often. Nothing here is removed from the data (proven frozen reports already are).""",
    """
anomalies, steps = om.quality.anomalies(H, meta)
anomalies.style.set_properties(**{"text-align": "left", "white-space": "normal"})
""",
]

# --------------------------------------------------------------------------------------------- 02 analysis
ANALYSIS = [
    """md:# 02 · Analysis: links, gauges and radar in rain and snow

All the sensors of the record on the same days: the links (NYC Mesh), the 1-minute airport gauges (ASOS), the daily
gauges (GHCN) and the radar (MRMS). First three examples, then rain from the links, blackouts and how paths
recover after rain and snow; at the end the ten radar days (5 rain, 5 snow) and the radar along the links.""",
    SETUP,
    """md:## 1. Three examples

For one path per band (the one with the most data that day): the level relative to its median; below, the
precipitation type and amount at the five airport gauges, and the temperature.

**Rain.** The drops follow the rain rate: here up to about 10 dB at 60 GHz, 3 to 4 dB at 24 and 5 GHz.""",
    """om.plots.show_case("2024-03-23", "Heavy rain, 2024-03-23")""",
    """md:**Dry snow.** Cold, dry snow hardly attenuates (here 1 to 3 dB at most): little liquid water in the path. The
heated gauges report the amount late, as the snow melts.""",
    """om.plots.show_case("2026-01-25", "Dry snow at about −10 °C, 2026-01-25")""",
    """md:**Wet snow.** Melting snow carries liquid water and wets the antennas: here the 24 GHz path drops about 4 to 5 dB
and the 5 GHz path up to 10 to 15 dB while the gauges see 1 to 3 mm/h; this 60 GHz path moves less.""",
    """om.plots.show_case("2024-02-13", "Wet snow near 0 °C, 2024-02-13")""",
    """md:Any other day: `om.plots.show_case("2023-12-18")`.""",
    """md:## 2. Rain accumulation: links against radar and gauges

Three rain days with one value per minute. Rain from the links follows the OpenSense processing chain (as in the
pycomlink examples), in plain xarray:

1. **wet / dry**: wet when a gauge records rain within one hour (the gauge network as reference);
2. **baseline**: the median level of the dry minutes over the past 6 hours, held through the wet spells;
3. **attenuation** `A = baseline − level` (no wet-antenna correction, so wet antennas add to the estimate);
4. **rain rate** from the ITU-R P.838-3 power law `A = a R^b L` (`analysis.itu_rainrate.rain_rate`).

Only 60 GHz paths of at least 800 m with 90 % of the day's minutes and at most 1.5 dB of noise when dry are used:
at 5 GHz one dB is already about 100 mm/h, so the stored whole-dB levels give no usable rain there. The radar is the
MRMS hourly rain averaged along the same paths (`poligrain.spatial.GridAtLines`); the metrics come from
`poligrain.validation`. Set `PICK` to a list of `cml_id` to choose the paths yourself; `om.analysis.link_rain(day, cml_ids)` gives the minute series of any path.""",
    """
EVENTS = ["2023-11-22", "2023-12-18", "2024-03-23"]   # rain days with one value per minute
PICK = None                                            # or a list of cml_id, e.g. ["7", "19", "33"]
table, acc = om.analysis.rain_accumulation(EVENTS, pick=PICK)
table
""",
    """md:The accumulation over each UTC day: every picked path (thin), their median (bold), the radar along the same
paths, the gauges and the GHCN day total.""",
    """om.plots.accumulation(acc)""",
    """md:## 3. Blackouts: links that drop out in rain

When rain attenuates a path below what its receiver can hear, the network stores no value: the path goes dark.
Below, the share of minutes without a value (`sublink_1` of the paths alive that day) in dry minutes, light rain and
heavy rain at the gauges; then three examples.""",
    """om.analysis.outages(EVENTS)""",
    """md:Three paths that go dark in heavy rain: a steady level before, a fall of 10 to 15 dB as the rain arrives,
no value while the rain is heaviest, and the same level again afterwards. The gauge is several km away, so its rain
is not exactly the rain on the path. Path 33 is dual-frequency: its 5 GHz sublinks keep working while the 60 GHz
ones are dark. `om.plots.blackouts([(cml_id, start, end), ...])` shows any other path.""",
    """om.plots.blackouts()""",
    """md:## 4. After the rain or snow: how fast a path recovers

Water, wet snow and ice on an antenna or its radome attenuate a link too, not only the precipitation along the path.
Six examples, each from 24 h before the end of the event to 48 h after it (shaded: the event; dashed: the dry level
of the 24 h before it). Without precipitation a 60 GHz level holds within about 1 dB. After rain the level is back
almost at once. After wet snow it takes a few hours; after cold snow a path can stay several dB down for a day or
more, while snow or ice stays on the antenna. These effects are studied over all the events of the record in
Jacoby et al. (ACM SenSys 2027). `om.plots.antenna_examples([(title, cml_id, sublink, start, end), ...])` shows any
other path and event.""",
    """om.plots.antenna_examples()""",
    """md:**The dry baseline.** Attenuation is the drop below the level the path would have without precipitation,
A = baseline − level. Two simple baselines on the 2026-08-20 rain (path 16, 68 GHz): a constant, the median of
the 24 h before the event (red), and a rolling median over 24 h (green; `om.analysis.attenuation`). During the
rain both give the same A, up to 40 dB. After it this path settles about 2 dB higher than before, so the constant
baseline turns slightly negative while the rolling median follows; over a long event a rolling median sinks
towards the attenuated level instead. A retrieval also needs a wet/dry classification and a wet-antenna term.
`om.plots.baseline_methods(cml_id, sublink, start, end, event=(start, end))` for any other path and event.""",
    """om.plots.baseline_methods()""",
    """md:## 5. The ten radar days

NOAA MRMS over New York City on five rain and five snow days, with the ASOS median and the radar mean and maximum.""",
    """
ev = om.radar_events()
ev[["kind", "day", "asos_median_mm", "radar_mean_mm", "radar_max_mm", "rain_share", "snow_share"]]
""",
    """om.plots.radar_maps(meta)""",
    """md:**The daily gauges (GHCN) on the same days.** Each station's day is its own observing window (e.g. 07:00 to
07:00 local for CoCoRaHS); shown is the window that covers most of the UTC day. Snowfall is the depth of new snow,
not its water.""",
    """
g = pd.read_csv(DATA / "data" / "weather" / "ghcn" / "ghcn_daily.csv", parse_dates=["day_start_utc", "day_end_utc"])
rows = []
for e in ev.itertuples():
    d = e.day
    q = g[(g.day_end_utc > d) & (g.day_start_utc < d + pd.Timedelta("1D"))].copy()
    q["overlap"] = q.day_end_utc.clip(upper=d + pd.Timedelta("1D")) - q.day_start_utc.clip(lower=d)
    q = q.sort_values("overlap").groupby("ghcn_id").tail(1)
    rows.append(dict(kind=e.kind, day=d.date(), stations=len(q), precipitation_mm=q.precipitation_mm.median(),
                     snowfall_mm=q.snowfall_mm.median(), asos_median_mm=e.asos_median_mm, radar_mean_mm=e.radar_mean_mm))
pd.DataFrame(rows).round(1)
""",
    """md:## 6. Radar along the links

The wettest rain day: the radar field, and every path coloured by the radar rain along it.""",
    """om.plots.radar_along_links(meta)""",
    """md:## 7. Use the radar and the links yourself

Three short cells in plain xarray, without the helper functions. **From signal to rain** on one 60 GHz path: the dry
level is the median of the day before, the attenuation is `A = dry level − level` (negative values set to 0), and
the ITU-R P.838 power law turns `A` into a rain rate (`analysis.itu_rainrate.rain_rate`, from the path's length,
frequency and polarization). No wet/dry classification and no wet-antenna correction: a first look only.""",
    """
from analysis.itu_rainrate import rain_rate
DAY, CML, SUB = "2024-03-23", "19", "sublink_1"
links = xr.open_dataset(DATA / "data" / "links" / "openmesh_links.nc")
x = links.sel(cml_id=CML, sublink_id=SUB)
level = x.rsl.sel(time=slice("2024-03-22", f"{DAY} 23:59")).to_series()     # one value per minute in 2024
dry = level["2024-03-22"].median()                                         # the dry day before
A = (dry - level[DAY]).clip(lower=0)                                       # attenuation, dB
R = pd.Series(rain_rate(A.values, float(x.length), float(x.frequency), str(x.polarization.values)), index=A.index)
print(f"cml {CML}: {float(x.frequency) / 1000:.1f} GHz, {float(x.length):.0f} m; dry level {dry:.0f} dBm; "
      f"max A {A.max():.0f} dB, max R {R.max():.0f} mm/h")
""",
    """md:**The radar along the same path**: the MRMS hourly rain at 20 points from one end of the path to the other
(the nearest grid cell of each), averaged, next to the link's rain and the nearest gauge, hour by hour. All three are
labelled by the end of the hour.""",
    """
radar = xr.open_dataset(DATA / "data" / "weather" / "radar" / f"openmesh_radar_rain_{DAY}.nc")
lat = xr.DataArray(np.linspace(float(x.site_0_lat), float(x.site_1_lat), 20), dims="p")
lon = xr.DataArray(np.linspace(float(x.site_0_lon), float(x.site_1_lon), 20), dims="p")
radar_1h = radar.rainfall_amount_1h.sel(lat=lat, lon=lon, method="nearest").mean("p").to_series()
link_1h = R.resample("1h", closed="right", label="right").mean()          # mean mm/h over the hour = mm
asos = xr.open_dataset(DATA / "data" / "weather" / "asos" / "openmesh_asos.nc")
near = om.analysis.nearest(om.asos_stations(), float(x.site_0_lat + x.site_1_lat) / 2, float(x.site_0_lon + x.site_1_lon) / 2)
g = asos.rainfall_amount.where(asos.rainfall_flag == 0).sel(id=near.index[0], time=slice(DAY, f"{DAY} 23:59"))
gauge_1h = g.to_series().resample("1h", closed="right", label="right").sum(min_count=30)
fig, ax = plt.subplots(figsize=(12, 3.5))
ax.step(link_1h.index, link_1h.values, where="pre", label=f"link {CML}")
ax.step(radar_1h.index, radar_1h.values, where="pre", label="MRMS along the link")
ax.step(gauge_1h.index, gauge_1h.values, where="pre", label=f"ASOS {near.index[0]} ({near.distance_m.iloc[0] / 1000:.1f} km)")
ax.set_ylabel("rain in the hour [mm]"); ax.set_title(f"{DAY}, hourly rain", loc="left"); ax.legend(); plt.show()
print(f"day totals: link {link_1h.sum():.0f} mm, radar {radar_1h.sum():.0f} mm, gauge {gauge_1h.sum():.0f} mm")
""",
    """md:**Precipitation type**: KOKX `hydrometeor_class` is the type aloft (about 1 to 2 km above the city), MRMS
`precip_flag` the type at the ground; both are codes (see the variables' attributes and the record's README.md). On 2024-02-13
at 12:00 KOKX sees dry snow aloft while MRMS calls most of the area cold stratiform rain at the ground.""",
    """
T = "2024-02-13 12:00"
kokx = xr.open_dataset(DATA / "data" / "weather" / "radar" / "openmesh_radar_kokx_snow_2024-02-13.nc")
mrms = xr.open_dataset(DATA / "data" / "weather" / "radar" / "openmesh_radar_snow_2024-02-13.nc")
KOKX = {0: "no echo", 30: "ice crystals", 40: "dry snow", 50: "wet snow", 60: "light/moderate rain",
        70: "heavy rain", 80: "big drops", 90: "graupel"}
MRMS = {0: "none", 1: "warm stratiform rain", 3: "snow", 6: "convective rain", 10: "cold stratiform rain"}

def type_map(ax, da, names, title):
    codes = [c for c in names if bool((da == c).any())]
    idx = sum(xr.where(da == c, i, 0) for i, c in enumerate(codes)).where(da.isin(codes))
    m = ax.pcolormesh(da.lon, da.lat, idx, cmap=plt.get_cmap("tab10", len(codes)), vmin=-0.5,
                      vmax=len(codes) - 0.5, shading="auto")
    cb = plt.colorbar(m, ax=ax, ticks=range(len(codes))); cb.ax.set_yticklabels([names[c] for c in codes])
    ax.set_title(title, loc="left"); ax.set_aspect(1 / np.cos(np.radians(40.7)))

fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5))
type_map(a1, kokx.hydrometeor_class.sel(time_10min=T), KOKX, f"KOKX hydrometeor class (aloft), {T}")
type_map(a2, mrms.precip_flag.sel(time_10min=T), MRMS, f"MRMS precip_flag (at the ground), {T}")
plt.show()
""",
]

if __name__ == "__main__":
    only = sys.argv[1:]
    for name, cells in [("00_quickstart", QUICK), ("01_data_overview", FILES_LINKS),
                        ("02_analysis", ANALYSIS)]:
        if not only or name[:2] in only:
            nb(cells, f"{name}.ipynb")
