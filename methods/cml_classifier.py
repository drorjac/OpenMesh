"""
methods/cml_classifier.py
=========================
Part 3 helpers: classify precipitation phase from CML attenuation patterns into
**rain / wet snow / dry snow**, using the per-bin phase index as ground truth.

GROUND TRUTH
------------
The hourly phase label (`cml_attenuation_baselines.nc`) gives rain vs snow.
Snow is split into a wet/dry superclass by a working **temperature** definition:

    dry snow : phase == 'snow' AND ASOS temp <  WET_DRY_C   (cold, fluffy, dry)
    wet snow : phase == 'snow' AND ASOS temp >= WET_DRY_C   (near-melting, wet)

WET_DRY_C = -2 C. This is a proxy: wet snow forms near the melting layer where
partially-melted flakes have a water coating (high microwave attenuation), dry
snow is colder with little liquid (near-transparent at microwave). Temperature
defines the *label*; the classifier's job is to recover it from the CML signal.

THE "CML-ALONE" CLAIM
---------------------
Because temperature *defines* the label, feeding temperature back in as a
predictor is partly circular. Every experiment is therefore run twice:
`with_temp=True` (CML features + ASOS temp) and `with_temp=False` (CML features
only). A good without-temp score supports "CML alone distinguishes wet vs dry
snow".

FEATURES (per link, per hour) — all from the attenuation signal
---------------------------------------------------------------
att, |att|; rolling mean/std/max over 3 h and 6 h; 1 h derivative and its
magnitude; a post-event-tail proxy (att relative to the event's running max);
and RSL short-term variability (scintillation). Temperature is appended only
when with_temp=True.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import xarray as xr

_REPO = Path(__file__).resolve().parents[1]
OUT_NC = _REPO / "dataset/raw/full/outputs/cml_attenuation_baselines.nc"

WET_DRY_C = -2.0
CLASSES = ("rain", "wet_snow", "dry_snow")

# Five hand-picked well-behaved V-high links (distinct paths). Chosen for:
# high frequency (66-68 GHz, strongest precip response), low dry-hour RSL drift
# (stable baseline), and good event coverage with >=80 snow hours split across
# both wet and dry subclasses. See pick_snow_links() for the data-driven ranking.
HANDPICKED = [
    "37::sublink_2",    # 68.0 GHz, 1086 m  — lowest baseline drift, 537 snow hrs
    "99::sublink_4",    # 65.9 GHz, 2699 m  — low drift, balanced snow subclasses
    "212::sublink_2",   # 67.0 GHz, 2397 m  — best coverage (1660 rain hrs)
    "216::sublink_1",   # 68.0 GHz, 2964 m  — long path, stable
    "132::sublink_2",   # 67.0 GHz, 3450 m  — longest, good snow coverage
]


# ============================================================================
# Link selection (data-driven, documents why the 5 were picked)
# ============================================================================
def pick_snow_links(nc_path=OUT_NC, n: int = 5, att_var: str = "att_ewma",
                    min_snow: int = 80, min_subclass: int = 20) -> pd.DataFrame:
    """Rank V-high links by baseline stability + coverage among links with
    enough snow (and both wet/dry subclasses). Returns the ranking table; the
    top `n` distinct CMLs are the hand-pick candidates."""
    d = xr.open_dataset(nc_path)
    ph = pd.Series(d["phase"].values)
    temp = d["temp_c"].values
    bt = d["band_tier"].values
    att = d[att_var].values
    rsl = d["rsl"].values
    snow = (ph == "snow").values
    rain = (ph == "rain").values
    dry = (ph == "dry").values
    dry_snow = snow & (temp < WET_DRY_C)
    wet_snow = snow & (temp >= WET_DRY_C)
    rows = []
    for i in np.where(bt == "V-high")[0]:
        a, r = att[i], rsl[i]
        rows.append(dict(
            sublink=str(d["sublink"].values[i]), cml_id=str(d["cml_id"].values[i]),
            freq_GHz=round(float(d["freq_MHz"][i]) / 1000, 1),
            length_m=round(float(d["length_m"][i]), 0),
            coverage=round(float(np.isfinite(r).mean()), 3),
            dry_rsl_std=round(float(np.nanstd(r[dry])), 3),
            n_rain=int(np.isfinite(a[rain]).sum()), n_snow=int(np.isfinite(a[snow]).sum()),
            n_drysnow=int(np.isfinite(a[dry_snow]).sum()),
            n_wetsnow=int(np.isfinite(a[wet_snow]).sum()),
        ))
    df = pd.DataFrame(rows)
    ok = df[(df.n_snow >= min_snow) & (df.n_drysnow >= min_subclass)
            & (df.n_wetsnow >= min_subclass)]
    return ok.sort_values(["dry_rsl_std", "coverage"], ascending=[True, False]).reset_index(drop=True)


# ============================================================================
# Feature engineering
# ============================================================================
def _link_series(d: xr.Dataset, sublink: str, att_var: str):
    i = list(d["sublink"].values).index(sublink)
    time = pd.to_datetime(d["time"].values)
    att = pd.Series(d[att_var].values[i], index=time)
    rsl = pd.Series(d["rsl"].values[i], index=time)
    length_km = float(d["length_m"][i]) / 1000.0
    return att / length_km, rsl, length_km   # att_per_km, rsl


def link_features(nc_path, sublink: str, att_var: str = "att_ewma") -> pd.DataFrame:
    """Per-hour CML attenuation features for one sublink (no label)."""
    d = xr.open_dataset(nc_path)
    a, rsl, _ = _link_series(d, sublink, att_var)
    f = pd.DataFrame(index=a.index)
    f["att"] = a
    f["att_abs"] = a.abs()
    f["att_mean_3h"] = a.rolling("3h", min_periods=1).mean()
    f["att_std_3h"] = a.rolling("3h", min_periods=2).std()
    f["att_max_6h"] = a.rolling("6h", min_periods=1).max()
    f["att_deriv"] = a.diff()
    f["att_deriv_abs"] = a.diff().abs()
    # post-event tail proxy: how far below the recent 6h max we sit (decay)
    f["att_below_max6h"] = a.rolling("6h", min_periods=1).max() - a
    # RSL short-term variability (scintillation differs rain vs snow)
    f["rsl_std_3h"] = rsl.rolling("3h", min_periods=2).std()
    return f


def label_frame(nc_path) -> pd.DataFrame:
    """Hourly ground-truth 3-class label + temp (rain / wet_snow / dry_snow);
    other hours are NaN and dropped downstream."""
    d = xr.open_dataset(nc_path)
    ph = pd.Series(d["phase"].values, index=pd.to_datetime(d["time"].values))
    temp = pd.Series(d["temp_c"].values, index=ph.index)
    lab = pd.Series(index=ph.index, dtype=object)
    lab[ph == "rain"] = "rain"
    lab[(ph == "snow") & (temp >= WET_DRY_C)] = "wet_snow"
    lab[(ph == "snow") & (temp < WET_DRY_C)] = "dry_snow"
    return pd.DataFrame({"label": lab, "temp_c": temp})


# ============================================================================
# Datasets
# ============================================================================
def single_link_dataset(nc_path, sublink: str, *, with_temp: bool,
                        att_var: str = "att_ewma"):
    """(X, y, feature_names) for one link: its features at hours labeled
    rain/wet_snow/dry_snow with finite attenuation."""
    feats = link_features(nc_path, sublink, att_var)
    lab = label_frame(nc_path)
    df = feats.join(lab).dropna(subset=["label", "att"])
    if with_temp:
        df = df.dropna(subset=["temp_c"])
    cols = list(feats.columns) + (["temp_c"] if with_temp else [])
    df = df.dropna(subset=cols)
    return df[cols].values, df["label"].values, cols


def multi_link_dataset(nc_path, sublinks: Sequence[str], *, with_temp: bool,
                       att_var: str = "att_ewma"):
    """Joint feature vector across links, aligned on hours where ALL links have
    finite attenuation and the hour is labeled. Per-link feature columns are
    prefixed with the sublink id; temperature (shared) is appended once."""
    lab = label_frame(nc_path)
    parts = []
    for sl in sublinks:
        f = link_features(nc_path, sl, att_var).add_prefix(f"{sl}|")
        parts.append(f)
    X = pd.concat(parts, axis=1)
    df = X.join(lab).dropna()                 # require all links + label + temp
    feat_cols = list(X.columns)
    if with_temp:
        feat_cols = feat_cols + ["temp_c"]
    df = df.dropna(subset=feat_cols + ["label"])
    return df[feat_cols].values, df["label"].values, feat_cols


# ============================================================================
# Train / evaluate
# ============================================================================
def train_eval(X, y, *, seed: int = 0, test_size: float = 0.3,
               n_estimators: int = 300):
    """Stratified train/test split + balanced RandomForest. Returns dict with
    confusion matrix, per-class precision/recall/F1, macro-F1 and the model."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import classification_report, confusion_matrix, f1_score
    from sklearn.model_selection import train_test_split

    classes = [c for c in CLASSES if c in set(y)]
    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=test_size, random_state=seed, stratify=y)
    clf = RandomForestClassifier(n_estimators=n_estimators, class_weight="balanced",
                                 random_state=seed, n_jobs=-1)
    clf.fit(Xtr, ytr)
    yp = clf.predict(Xte)
    return dict(
        model=clf, classes=classes, y_test=yte, y_pred=yp,
        confusion=confusion_matrix(yte, yp, labels=classes),
        report=classification_report(yte, yp, labels=classes, output_dict=True, zero_division=0),
        report_txt=classification_report(yte, yp, labels=classes, zero_division=0),
        macro_f1=f1_score(yte, yp, labels=classes, average="macro", zero_division=0),
        n_train=len(ytr), n_test=len(yte),
    )


def plot_confusion(res: dict, *, title: str = "", normalize: bool = True,
                   ax=None, save_path=None):
    """Confusion-matrix heatmap (row-normalized = per-class recall)."""
    import matplotlib.pyplot as plt
    cm = res["confusion"].astype(float)
    classes = res["classes"]
    if normalize:
        cm = cm / cm.sum(axis=1, keepdims=True).clip(min=1)
    if ax is None:
        _, ax = plt.subplots(figsize=(4.6, 4))
    ax.imshow(cm, cmap="Blues", vmin=0, vmax=1 if normalize else None)
    ax.set_xticks(range(len(classes))); ax.set_yticks(range(len(classes)))
    ax.set_xticklabels(classes, rotation=30, ha="right"); ax.set_yticklabels(classes)
    ax.set_xlabel("Predicted"); ax.set_ylabel("True")
    for r in range(len(classes)):
        for c in range(len(classes)):
            ax.text(c, r, f"{cm[r, c]:.2f}" if normalize else int(cm[r, c]),
                    ha="center", va="center",
                    color="white" if cm[r, c] > 0.5 else "black", fontsize=10)
    ax.set_title(f"{title}\nmacro-F1={res['macro_f1']:.2f}  (n_test={res['n_test']})",
                 fontsize=11, fontweight="bold")
    if save_path:
        ax.figure.savefig(save_path, dpi=140, bbox_inches="tight")
    return ax


def plot_event_example(nc_path, sublink, model, feat_cols, *, window,
                       att_var="att_ewma", with_temp=False, save_path=None):
    """Time-series of att/km over a window with the classifier's predicted class
    shaded, to show a snow event vs a rain event and the decision."""
    import matplotlib.pyplot as plt
    feats = link_features(nc_path, sublink, att_var)
    lab = label_frame(nc_path)
    df = feats.join(lab)
    seg = df.loc[window[0]:window[1]].copy()
    cols = list(feats.columns) + (["temp_c"] if with_temp else [])
    valid = seg.dropna(subset=cols)
    pred = pd.Series(index=seg.index, dtype=object)
    if len(valid):
        pred.loc[valid.index] = model.predict(valid[cols].values)
    fig, ax = plt.subplots(figsize=(13, 4))
    ax.plot(seg.index, seg["att"], color="0.2", lw=1.0, label="att (dB/km)")
    band = {"rain": "#2166ac", "wet_snow": "#e377c2", "dry_snow": "#00e5ff"}
    for cls, col in band.items():
        m = pred == cls
        ax.fill_between(seg.index, seg["att"].min(), seg["att"].max(),
                        where=m.values, color=col, alpha=0.25, step="mid", label=f"pred {cls}")
    ax.set_ylabel("Specific attenuation (dB/km)"); ax.set_xlabel("Time")
    ax.set_title(f"{sublink}: attenuation with predicted phase  ({window[0]} → {window[1]})",
                 fontsize=11, fontweight="bold")
    ax.legend(ncol=4, fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=140, bbox_inches="tight")
    return {"fig": fig, "axes": ax}
