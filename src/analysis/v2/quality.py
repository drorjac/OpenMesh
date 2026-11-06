"""Data quality of the links, from the hourly summary (`om.hourly()`): coverage, outages, levels, anomalies, and the
signatures of rain and of the day."""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from . import io
from .plots import _order
from .style import BAND_COLOR, BANDS

ERA_END = io.ERA_END


def _band(meta):
    return meta.set_index("cml_id").band


def _level(H, sub="sublink_1"):
    return H["median"].sel(sublink_id=sub).to_pandas().T             # time x cml_id


def _rain_hourly():
    return io.asos().rainfall_amount.resample(time="1h").sum(min_count=50).to_pandas().T


def _nearest(meta):
    st = io.asos_stations()
    from .analysis import nearest
    return {r.cml_id: nearest(st, (r.site_0_lat + r.site_1_lat) / 2, (r.site_0_lon + r.site_1_lon) / 2).index[0]
            for r in meta.itertuples()}


def coverage(H, meta):
    """Share of hours with a value, per path and day (V60 on top)."""
    band = _band(meta)
    D = (H["n"].sel(sublink_id="sublink_1") > 0).to_pandas().T.resample("1D").mean()[_order(meta)]
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.imshow(D.T.values, aspect="auto", cmap="Blues", vmin=0, vmax=1, interpolation="nearest")
    ticks = np.arange(0, len(D), 60)
    ax.set_xticks(ticks); ax.set_xticklabels([f"{D.index[i]:%Y-%m}" for i in ticks], rotation=90)
    pos = np.cumsum([0] + [int((band == b).sum()) for b in ["V60", "K24", "C5"]])
    ax.set_yticks((pos[:-1] + pos[1:]) / 2); ax.set_yticklabels(["V60", "K24", "C5"])
    for y in pos[1:-1]:
        ax.axhline(y - 0.5, color="k", lw=1)
    ax.set_title("Share of hours with a value, per path and day"); ax.grid(False)
    plt.tight_layout(); plt.show()


def outages(H, top=8):
    """Network-wide outages: runs of days on which fewer than 10 % of the paths report."""
    n = H["n"].sel(sublink_id="sublink_1") > 0
    rep = int(n.any("time").sum())
    day = n.to_pandas().T.resample("1D").max().sum(axis=1)
    low = day < 0.1 * rep
    runs = (low != low.shift()).cumsum()[low]
    out = pd.DataFrame([dict(start=g.index[0].date(), end=g.index[-1].date(), days=len(g))
                        for _, g in low[low].groupby(runs)])
    return out.sort_values("days", ascending=False).head(top).reset_index(drop=True)


def levels(H, meta):
    """Hourly median level per band: histogram and a summary row per band."""
    band, L1, L2 = _band(meta), _level(H, "sublink_1"), _level(H, "sublink_2")
    fig, axes = plt.subplots(1, 3, figsize=(15, 3.2))
    rows = []
    for ax, b in zip(axes, ["V60", "K24", "C5"]):
        c = list(band[band == b].index)
        v = pd.concat([L1[c], L2[c]]).values.ravel(); v = v[np.isfinite(v)]
        ax.hist(v, bins=np.arange(-100, -15, 1), color=BAND_COLOR[b])
        ax.set_title(f"{b}: hourly median level"); ax.set_xlabel("dBm")
        rows.append(dict(band=b, hours=len(v), p01=np.percentile(v, 1), median=np.median(v), p99=np.percentile(v, 99)))
    plt.tight_layout(); plt.show()
    return pd.DataFrame(rows).set_index("band").round(1)


SPARSE = (pd.Timestamp("2024-07-15"), ERA_END.normalize())               # about one hour a day kept by the network


def _steps(L1, band, db=6):
    """The largest step per path between the 7-day medians before and after a day, at least `db`. The windows stay
    inside one sampling period, so a change of sampling or of variable (rsl -> rsl_avg) is not taken for a step."""
    dm = L1.resample("1D").median()
    edges = [dm.index[0], *SPARSE, dm.index[-1] + pd.Timedelta("1D")]
    step = []
    for a, b in zip(edges[:-1], edges[1:]):
        d = dm[(dm.index >= a) & (dm.index < b)]
        before = d.rolling(7, min_periods=4).median()
        after = d[::-1].rolling(7, min_periods=4).median()[::-1].shift(-1)
        step.append(after - before)
    step = pd.concat(step)
    ev = step.abs().stack().rename("db").reset_index()
    ev.columns = ["day", "cml_id", "db"]
    ev = ev[ev.db >= db].sort_values("db", ascending=False).drop_duplicates("cml_id")
    ev["band"] = ev.cml_id.map(band)
    ev["signed_db"] = [step.loc[d, c] for d, c in zip(ev.day, ev.cml_id)]
    return ev


def anomalies(H, meta):
    """One row per check: what is checked, why it matters, and how much of it the record has (paths and count).
    Also returns the level steps, one row per path."""
    band, L1, L2 = _band(meta), _level(H, "sublink_1"), _level(H, "sublink_2")
    rain, near = _rain_hourly(), _nearest(meta)
    mn, mx = H["min"].sel(sublink_id="sublink_1").to_pandas().T, H["max"].sel(sublink_id="sublink_1").to_pandas().T
    stuck, stuck_paths = 0, set()
    for c in L1.columns:                                       # one value for 48 h or more
        s = L1[c].dropna()
        flat = (mn[c].reindex(s.index) == mx[c].reindex(s.index)) & (s.diff() == 0)
        g = (flat != flat.shift()).cumsum()[flat]
        n = sum(len(r) >= 48 for _, r in flat[flat].groupby(g))
        stuck += n
        if n:
            stuck_paths.add(c)
    steps = _steps(L1, band)
    rng = (mx - mn).loc[:ERA_END]
    big = rng >= 20
    wet = pd.DataFrame({c: rain[near[c]].reindex(rng.index).fillna(0) >= 0.5 for c in rng.columns})
    n_big = int(big.values.sum())
    asym = (L1.median() - L2.median()).abs()
    below = int(H["n_max_below"].sum()); nmax = int(H["n_max"].sum())
    rows = [
        ("frozen value", "sublink_1 repeats one value for 48 h or more",
         "a radio that stopped measuring looks like a perfectly steady dry signal",
         len(stuck_paths), f"{stuck} runs", "flat in both directions, so kept; proven ones are already removed"),
        ("level step", "the 7-day median jumps by 6 dB or more",
         "the dry baseline changes (re-aligned or swapped radio, new obstruction)",
         len(steps), f"{len(steps)} steps", "reset the baseline at the step; see the figure below"),
        ("fast swing", "20 dB or more between min and max within one hour (minute data)",
         "rain at 60 GHz, interference at 5 GHz",
         int(big.any().sum()), f"{n_big} hours", "in rain: " + ", ".join(
             f"{b} {(big & wet)[ids].values.sum() / max(1, big[ids].values.sum()):.0%} of {int(big[ids].values.sum())} h"
             for b in BANDS for ids in [[c for c in big.columns if band.get(c) == b]])),
        ("directions differ", "the two directions' medians are 10 dB or more apart",
         "one direction cannot stand in for the other", int((asym >= 10).sum()), "", "use each direction on its own"),
        ("rsl_max below level", "the maximum is lower than the level at the same stamp",
         "a consistency check of the file", "", f"{below:,} minutes", f"{below / max(1, nmax):.4%} of all rsl_max"),
    ]
    out = pd.DataFrame(rows, columns=["check", "what is checked", "why it matters", "paths", "count", "note"])
    return out.set_index("check"), steps


def step_examples(H, meta, steps, n=4):
    """The largest level steps: daily median of both directions, the step marked; grey: about one hour a day kept."""
    L1, L2 = _level(H, "sublink_1"), _level(H, "sublink_2")
    fig, axes = plt.subplots(2, 2, figsize=(15, 5.5), sharex=True)
    for ax, r in zip(axes.ravel(), steps.head(n).itertuples()):
        ax.plot(L1[r.cml_id].resample("1D").median(), lw=0.8, label="sublink_1")
        ax.plot(L2[r.cml_id].resample("1D").median(), lw=0.8, label="sublink_2")
        ax.axvspan(*SPARSE, color="0.85", lw=0, zorder=0)
        ax.axvline(r.day, color="r", ls="--", lw=1)
        ax.set_title(f"cml {r.cml_id} ({r.band}): {r.signed_db:+.0f} dB on {r.day:%Y-%m-%d}", fontsize=9)
    axes[0, 0].legend(fontsize=8); plt.tight_layout(); plt.show()


def rain_signature(H, meta):
    """Median attenuation (7-day running median minus the hourly level) against the hourly rain at the nearest gauge,
    per band; and one storm in the three bands."""
    band, L1 = _band(meta), _level(H, "sublink_1")
    rain, near = _rain_hourly(), _nearest(meta)
    att = L1.rolling(24 * 7, center=True, min_periods=48).median() - L1
    bins, labels = [-0.01, 0.0, 0.5, 2, 5, 10, 100], ["0", "0–0.5", "0.5–2", "2–5", "5–10", ">10"]
    rows = []
    for c in att.columns:
        k = pd.cut(rain[near[c]].reindex(att.index), bins, labels=labels)
        rows.append(att[c].groupby(k, observed=True).median().rename(c))
    A = pd.DataFrame(rows)
    curve = A.groupby(A.index.map(band))[labels].median().reindex(["V60", "K24", "C5"])
    lga = rain["LGA"].loc[:ERA_END]
    t = lga.idxmax(); w = slice(t - pd.Timedelta("18h"), t + pd.Timedelta("18h"))
    fig, (a0, a1) = plt.subplots(1, 2, figsize=(16, 4), gridspec_kw=dict(width_ratios=[1, 2]))
    for b, r in curve.iterrows():
        a0.plot(labels, r.values, marker="o", color=BAND_COLOR[b], label=b)
    a0.set_xlabel("rain in the hour at the nearest gauge (mm)"); a0.set_ylabel("median attenuation (dB)")
    a0.legend(); a0.set_title("Rain signature by band")
    order = _order(meta)
    for b in ["V60", "K24", "C5"]:
        c = [x for x in order if band[x] == b and near[x] == "LGA"] or [x for x in order if band[x] == b]
        best = max(c, key=lambda x: L1[x].loc[w].notna().sum())
        a1.plot(att[best].loc[w], color=BAND_COLOR[b], label=f"{b} · cml {best}")
    a2 = a1.twinx(); a2.bar(lga.loc[w].index, lga.loc[w].values, width=1 / 24, color="0.8", zorder=0)
    a2.set_ylabel("LaGuardia rain (mm/h)"); a1.set_zorder(a2.get_zorder() + 1); a1.patch.set_visible(False)
    a1.set_ylabel("attenuation (dB)"); a1.legend(fontsize=8); a1.set_title(f"The storm of {t:%Y-%m-%d} in three bands")
    plt.tight_layout(); plt.show()
    return curve.round(2)


def daily_cycle(H, meta):
    """Mean level by hour of day on dry days, relative to the day's mean, per band."""
    band, L1 = _band(meta), _level(H, "sublink_1")
    rain, near = _rain_hourly(), _nearest(meta)
    rows = []
    for c in L1.columns:
        s = L1[c].loc[:ERA_END].dropna()
        if len(s) < 24 * 30:
            continue
        dry = rain[near[c]].reindex(s.index).fillna(0).groupby(s.index.date).transform("sum") == 0
        s = s[dry.values]
        a = s - s.groupby(s.index.date).transform("mean")
        rows.append(a.groupby(a.index.hour).mean().rename(c))
    DC = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(8, 3.5))
    for b, r in DC.groupby(DC.index.map(band)).median().reindex(["V60", "K24", "C5"]).iterrows():
        ax.plot(r.index, r.values, marker="o", ms=3, color=BAND_COLOR[b], label=b)
    ax.set_xlabel("hour of day (UTC)"); ax.set_ylabel("dB"); ax.legend(); ax.set_title("Daily cycle on dry days")
    plt.tight_layout(); plt.show()
