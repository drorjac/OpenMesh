"""
Analyze a fetched IEM METAR archive (see asos_metar_fetch.py) and write a
data-quality + phase-classification report.

Reads the most recent `ASOS_metar_*.csv` combined file from
config.OUTPUT_DIRS['asos_metar'] and produces dataset/raw/fetched/asos_metar/REPORT.md
covering: row counts/gaps per station-month, minute-of-hour distribution,
wxcodes frequency, AUTO/AO1/AO2 station-augmentation flags, a p01i
accumulation-monotonicity check, and wxcodes-derived phase-class counts
(report counts and distinct-hour counts) broken out by winter season.

Usage: python analyze_metar_report.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import OUTPUT_DIRS
from noaa_asos.asos_metar_fetch import add_metar_flags, add_phase_class

OUT_DIR = OUTPUT_DIRS["asos_metar"]
RAW_PATH = sorted(OUT_DIR.glob("ASOS_metar_*.csv"))[-1]
REPORT_PATH = OUT_DIR / "REPORT.md"

df = pd.read_csv(RAW_PATH)
df["valid"] = pd.to_datetime(df["valid"])
df["month"] = df["valid"].dt.to_period("M")
df["minute"] = df["valid"].dt.minute
df["hour"] = df["valid"].dt.floor("h")
df = add_metar_flags(df, metar_col="metar")
df = add_phase_class(df, wxcodes_col="wxcodes")

STATIONS = sorted(df["station"].unique())

out = []


def emit(line=""):
    out.append(line)
    print(line)


emit("# IEM METAR Archive — Data Quality & Phase Classification Report")
emit()
emit(f"Source file: `{RAW_PATH.name}` ({len(df):,} rows, stations: {STATIONS})")
emit("Endpoint: `mesonet.agron.iastate.edu/cgi-bin/request/asos.py` "
     "(report_type=3,4 — routine + special)")
emit()

# =============================================================================
# 1. Row counts per station per month + gaps
# =============================================================================
emit("## 1. Row counts per station per month")
emit()
counts = df.groupby(["station", "month"]).size().unstack("station", fill_value=0)
emit("```")
emit(counts.to_string())
emit("```")
emit()

emit("### Gaps (silent periods > 3 hours between consecutive reports, per station)")
emit()
gap_rows = []
for sid, g in df.groupby("station"):
    g = g.sort_values("valid")
    dt = g["valid"].diff()
    big = dt[dt > pd.Timedelta(hours=3)]
    for idx, gap in big.items():
        start = g.loc[:idx, "valid"].iloc[-2]
        end = g.loc[idx, "valid"]
        gap_rows.append({"station": sid, "gap_start": start, "gap_end": end,
                          "duration_hours": round(gap.total_seconds() / 3600, 1)})
gaps_df = pd.DataFrame(gap_rows)
if len(gaps_df) == 0:
    emit("No gaps > 3 hours found.")
else:
    emit("```")
    emit(gaps_df.to_string(index=False))
    emit("```")
emit()

# =============================================================================
# 2. Fraction of reports at :51 vs other minutes, by month
# =============================================================================
emit("## 2. Fraction of reports at minute :51 (routine top-of-hour) vs other, by month")
emit()
df["is_51"] = df["minute"] == 51
pct51 = (df.groupby(["station", "month"])["is_51"].mean() * 100).unstack("station").round(1)
emit("```")
emit(pct51.to_string())
emit("```")
overall51 = (df.groupby("station")["is_51"].mean() * 100).round(1)
emit()
emit("Overall % of reports at :51, per station:")
emit("```")
emit(overall51.to_string())
emit("```")
emit()

# =============================================================================
# 3. Distinct wxcodes values with frequencies
# =============================================================================
emit("## 3. Distinct `wxcodes` values and frequencies (all stations combined)")
emit()
wx_counts = df["wxcodes"].fillna("M").value_counts()
emit("```")
emit(wx_counts.to_string())
emit("```")
emit()

# =============================================================================
# 4. AUTO / AO1 / AO2 flags per station
# =============================================================================
emit("## 4. Station-augmentation flags per station")
emit()
flag_summary = df.groupby("station")[["auto", "ao1", "ao2", "ghcnh_filled"]].agg(["sum", "mean"])
flag_summary_fmt = pd.DataFrame(index=flag_summary.index)
for col in ["auto", "ao1", "ao2", "ghcnh_filled"]:
    flag_summary_fmt[f"{col}_count"] = flag_summary[(col, "sum")].astype(int)
    flag_summary_fmt[f"{col}_pct"] = (flag_summary[(col, "mean")] * 100).round(2)
emit("```")
emit(flag_summary_fmt.to_string())
emit("```")
emit()
emit("Interpretation: `AUTO` in the report body means the observation was produced "
     "without human augmentation at transmission time. `AO2` (vs `AO1`) in the remarks "
     "means the automated station has a precipitation discriminator (can tell liquid "
     "from frozen precip); `AO1` cannot. `ghcnh_filled` flags rows IEM back-filled from "
     "GHCN-Hourly rather than a genuine transmitted report (tagged `IEM_GHCNH`).")
emit()

# =============================================================================
# 5. p01i monotonicity within an accumulation window (multiple reports, nonzero p01i)
# =============================================================================
emit("## 5. `p01i` monotonicity check (windows with >1 report and nonzero p01i)")
emit()
emit("`p01i` is the 1-hour precip total, reset immediately after each top-of-hour "
     "(~:51) report. Reports are grouped into the accumulation window they fall "
     "into (a report after :51 belongs to the NEXT window, ending at the "
     "following hour's :51), and checked for a non-decreasing sequence ending "
     "at that window's closing report. It is not safe to sum p01i across "
     "reports within a window.")
emit()


def parse_p01i(v):
    if pd.isna(v) or v == "M":
        return np.nan
    if v == "T":
        return 0.005  # trace: nonzero but below the 0.01" reporting resolution
    try:
        return float(v)
    except ValueError:
        return np.nan


df["p01i_num"] = df["p01i"].apply(parse_p01i)

# p01i resets immediately AFTER the :51 report, so a report at e.g. :58 belongs
# to the NEXT accumulation window, not the one ending at this hour's :51.
# Bucket by the window each report accumulates INTO, not by clock hour.
df["accum_window"] = df["hour"].where(df["minute"] <= 51, df["hour"] + pd.Timedelta(hours=1))

n_checked = 0
n_monotonic = 0
violations = []
for (sid, hr), g in df.groupby(["station", "accum_window"]):
    if len(g) < 2:
        continue
    g = g.sort_values("valid")
    vals = g["p01i_num"].values
    if np.all(np.isnan(vals)) or np.nanmax(vals) <= 0:
        continue
    n_checked += 1
    valid_vals = vals[~np.isnan(vals)]
    is_mono = np.all(np.diff(valid_vals) >= -1e-9)
    if is_mono:
        n_monotonic += 1
    else:
        violations.append((sid, hr, list(zip(g["valid"].dt.strftime("%H:%M"), g["p01i"]))))

emit(f"Windows checked (station-windows with >1 report and max p01i > 0): {n_checked:,}")
if n_checked:
    emit(f"Monotonically non-decreasing to the closing report: {n_monotonic:,} "
         f"({100 * n_monotonic / n_checked:.1f}%)")
if violations:
    emit()
    emit(f"Violations ({len(violations)} total, up to 10 shown):")
    emit("```")
    for sid, hr, seq in violations[:10]:
        emit(f"  {sid} {hr}: {seq}")
    emit("```")
emit()

# =============================================================================
# 6. Phase classes from wxcodes, by winter season
# =============================================================================
emit("## 6. Phase classes derived from `wxcodes`, by winter season")
emit()
emit("Classes: rain, snow, mixed (rain+snow both reported, not freezing), freezing "
     "(FZRA/FZDZ), ice_pellets (PL), unknown (UP), dry (no precip code). "
     "Precedence when a report matches multiple families: freezing > mixed > "
     "ice_pellets > unknown > rain > snow (see PHASE_PRECEDENCE / classify_wxcodes "
     "docstring in asos_metar_fetch.py). Winter season labeled by the November "
     "it starts in (e.g. '2023-24' = Nov 2023 - Apr 2024); May-Oct is 'off-season'.")
emit()


def winter_season(ts):
    m, y = ts.month, ts.year
    if m in (11, 12):
        return f"{y}-{str(y + 1)[2:]}"
    if m in (1, 2, 3, 4):
        return f"{y - 1}-{str(y)[2:]}"
    return "off-season"


df["season"] = df["valid"].apply(winter_season)

CLASS_ORDER = ["rain", "snow", "mixed", "freezing", "ice_pellets", "unknown", "dry"]

emit("### Report counts (per observation)")
emit()
report_counts = (
    df.groupby(["station", "season", "phase_class"]).size()
    .unstack("phase_class", fill_value=0)
    .reindex(columns=CLASS_ORDER, fill_value=0)
)
emit("```")
emit(report_counts.to_string())
emit("```")
emit()

emit("### Hour counts (distinct station-hours in which the class occurred at least once; "
     "not mutually exclusive across classes within an hour)")
emit()
hour_counts = (
    df.groupby(["station", "season", "phase_class"])["hour"].nunique()
    .unstack("phase_class", fill_value=0)
    .reindex(columns=CLASS_ORDER, fill_value=0)
)
emit("```")
emit(hour_counts.to_string())
emit("```")
emit()

emit("### Winter-season-only totals, non-dry classes, report counts")
emit()
winter_only = report_counts[report_counts.index.get_level_values("season") != "off-season"]
emit("```")
emit(winter_only.drop(columns=["dry"]).to_string())
emit("```")

REPORT_PATH.write_text("\n".join(out) + "\n")
print(f"\n\nWrote report to {REPORT_PATH}")
