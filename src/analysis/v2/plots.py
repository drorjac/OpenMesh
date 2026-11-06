"""Figures for the OpenMesh notebooks: maps, frequencies, availability, rain and snow examples, radar days."""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import patheffects as mpe
from matplotlib.collections import LineCollection
from matplotlib.patches import Patch

from . import io
from .analysis import link_level, radar_along_link
from .style import BAND_COLOR, BANDS, MUTED, SLOT, SPLIT, SPLIT_COLOR, SPLIT_LABEL

EXTENT = (-74.10, -73.80, 40.56, 40.86)
ASPECT = 1 / np.cos(np.radians(40.7))
CAT_COLOR = {"rain": "tab:blue", "snow": "tab:purple", "mix": "tab:orange", "ice": "tab:red"}


def map_axes(ax=None, figsize=(8, 8), basemap=True, extent=EXTENT):
    """An axes over New York City with a light basemap (if contextily is installed)."""
    if ax is None:
        _, ax = plt.subplots(figsize=figsize)
    ax.set_xlim(extent[:2]); ax.set_ylim(extent[2:]); ax.set_aspect(ASPECT); ax.grid(False)
    if basemap:
        try:
            import contextily as cx
            cx.add_basemap(ax, crs="EPSG:4326", source=cx.providers.Esri.WorldGrayCanvas, attribution_size=6)
        except Exception:
            pass
    return ax


def draw_links(ax, meta, lw=None, label=True):
    """Draw every path, coloured by band (5 GHz thin, 24 / 60 GHz thick)."""
    for b in ["C5", "K24", "V60"]:
        s = meta[meta.band == b]
        for r in s.itertuples():
            ax.plot([r.site_0_lon, r.site_1_lon], [r.site_0_lat, r.site_1_lat], color=BAND_COLOR[b],
                    lw=lw or (0.9 if b == "C5" else 2.4), alpha=0.7 if b == "C5" else 1, zorder=2 if b == "C5" else 3)
        if label:
            ax.plot([], [], color=BAND_COLOR[b], lw=2, label=f"{b} ({len(s)})")


def scale_bar(ax, km=2, loc="lower right"):
    """A black and white km bar on a lon / lat map axes."""
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    w = km / (111.32 * np.cos(np.radians((y0 + y1) / 2)))
    x = x1 - 0.05 * (x1 - x0) - w if "right" in loc else x0 + 0.05 * (x1 - x0)
    y, h = y0 + 0.04 * (y1 - y0), 0.008 * (y1 - y0)
    for i, fc in enumerate(["k", "w"]):
        ax.add_patch(plt.Rectangle((x + i * w / 2, y), w / 2, h, fc=fc, ec="k", lw=0.6, zorder=20))
    for xx, t in [(x, "0"), (x + w, f"{km:g} km")]:
        ax.text(xx, y + 1.8 * h, t, ha="center", va="bottom", fontsize=7, zorder=21)


def links_extent(meta, pad=0.012):
    """The box around every path, padded by `pad` degrees, wide enough to show the Central Park and LaGuardia gauges."""
    lon = np.r_[meta.site_0_lon, meta.site_1_lon, -73.87]
    lat = np.r_[meta.site_0_lat, meta.site_1_lat]
    return lon.min() - pad * ASPECT, lon.max() + pad * ASPECT, lat.min() - pad, lat.max() + pad


def stations(ax, label=True):
    """The ASOS gauges inside the map as triangles, the others named in the corner."""
    s = io.asos_stations()
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    inside = s.lon.between(x0, x1) & s.lat.between(y0, y1)
    ax.scatter(s.lon[inside], s.lat[inside], marker="^", s=90, c="k", edgecolor="w", lw=1, zorder=12,
               label=f"ASOS gauge ({len(s)})" if label else None)
    for i, r in s[inside].iterrows():
        ax.annotate(i, (r.lon, r.lat), xytext=(6, -3), textcoords="offset points", fontsize=8, weight="bold",
                    zorder=12, path_effects=[mpe.withStroke(linewidth=2.5, foreground="w")])
    if (~inside).any():
        ax.text(0.99, 0.99, "off the map: " + ", ".join(s.index[~inside]), transform=ax.transAxes, ha="right",
                va="top", fontsize=7, color="0.35", zorder=21)


def _sublinks(meta):
    """The sublinks of the paths in `meta` that have a frequency, with their band split."""
    s = io.sublink_meta().dropna(subset=["frequency"])
    s = s[s.cml_id.isin(meta.cml_id)]
    return s.assign(split=s.frequency.map(io.split_of))


def network_map(meta, highlight=None, ax=None, gauges=True, pws="all", pws_metadata=None):
    """Every path on a basemap, coloured by its highest band (V60 split at 63 GHz, high bands on top), the radio sites
    as dots, the ASOS gauges as triangles, and the path `highlight` (a cml_id) in black.

    pws: "all" (default), a station ID / list of IDs, or False to hide personal
    weather stations. pws_metadata accepts a CSV path or DataFrame with Station ID,
    Latitude and Longitude columns (or station_id, lat, lon). By default, use
    OPENMESH_PWS_METADATA, else the repo's dataset/meta/pws_metadata.csv (the WU
    stations of v1, Zenodo 17508286). The v2 record has no PWS data.
    """
    import os
    from pathlib import Path

    selected = pd.DataFrame(columns=["Station ID", "Latitude", "Longitude"])
    if pws is not False and pws is not None:
        source = pws_metadata
        if source is None:
            configured = os.environ.get("OPENMESH_PWS_METADATA")
            if configured:
                source = Path(configured).expanduser()
            else:
                from analysis.datasets import REPO_ROOT
                csv = REPO_ROOT / "dataset" / "meta" / "pws_metadata.csv"     # the v1 WU stations
                source = csv if csv.exists() else None
        if source is not None:
            selected = source.copy() if isinstance(source, pd.DataFrame) else pd.read_csv(source)
            if "network" in selected:
                selected = selected[selected.network.str.startswith("PWS", na=False)]
            selected = selected.rename(columns={"station_id": "Station ID", "lat": "Latitude",
                                                "lon": "Longitude"})
            if not (isinstance(pws, str) and pws == "all"):
                ids = [pws] if isinstance(pws, str) else list(pws)
                missing = set(ids) - set(selected["Station ID"])
                if missing:
                    raise ValueError(f"Unknown PWS station IDs: {sorted(missing)}")
                selected = selected[selected["Station ID"].isin(ids)]
            selected = selected.dropna(subset=["Longitude", "Latitude"])
        elif not (isinstance(pws, str) and pws == "all"):
            raise FileNotFoundError("Provide pws_metadata or set OPENMESH_PWS_METADATA to select PWS stations")
    show = ax is None
    box = links_extent(meta)
    if not selected.empty:
        box = (min(box[0], selected.Longitude.min() - .012 * ASPECT),
               max(box[1], selected.Longitude.max() + .012 * ASPECT),
               min(box[2], selected.Latitude.min() - .012),
               max(box[3], selected.Latitude.max() + .012))
    ax = map_axes(ax, figsize=(8, 10), extent=box)
    n_sub = _sublinks(meta).split.value_counts()
    sites = np.vstack([meta[["site_0_lon", "site_0_lat"]].values, meta[["site_1_lon", "site_1_lat"]].values])
    sites = np.unique(sites.round(5), axis=0)
    ax.scatter(sites[:, 0], sites[:, 1], s=5, c="0.25", lw=0, zorder=4, label=f"radio site ({len(sites)})")
    for z, b in enumerate(SPLIT[::-1]):
        q, lw = meta[meta.split == b], 0.8 if b == "C5" else 2.6
        seg = np.stack([q[["site_0_lon", "site_0_lat"]].values, q[["site_1_lon", "site_1_lat"]].values], axis=1)
        ax.add_collection(LineCollection(seg, colors=SPLIT_COLOR[b], lw=lw, alpha=0.75 if b == "C5" else 1,
                                         zorder=2 + z, capstyle="round",
                                         path_effects=None if b == "C5" else [mpe.withStroke(linewidth=lw + 1.4,
                                                                                             foreground="w")]))
    for b in SPLIT:
        ax.plot([], [], color=SPLIT_COLOR[b], lw=2.5,
                label=f"{SPLIT_LABEL[b]}: {(meta.split == b).sum()} paths, {n_sub.get(b, 0)} directional links")
    if highlight is not None:
        p = meta.set_index("cml_id").loc[str(highlight)]
        ax.plot([p.site_0_lon, p.site_1_lon], [p.site_0_lat, p.site_1_lat], color="k", lw=3.5, zorder=10,
                solid_capstyle="round", path_effects=[mpe.withStroke(linewidth=7, foreground="w")],
                label=f"cml {highlight} ({p.length / 1000:.2f} km, {p.frequency / 1000:.2f} GHz)")
    if gauges:
        stations(ax)
    if not selected.empty:
        ax.scatter(selected.Longitude, selected.Latitude, marker="o", s=32,
                   c="tab:orange", edgecolor="w", lw=.6, zorder=11,
                   label=f"PWS ({len(selected)})")
    scale_bar(ax)
    ax.set_xlabel("longitude (°E)"); ax.set_ylabel("latitude (°N)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.07), ncol=2)
    ax.set_title("The NYC Mesh paths in the record")
    if show:
        plt.show()
    return ax


def _cells(meta, cell_km, extent=EXTENT):
    """Count sublinks per grid cell: each path adds its number of sublinks to every cell it crosses."""
    lon0, lon1, lat0, lat1 = extent
    dlat = cell_km / 111.32
    dlon = dlat * ASPECT
    nx, ny = int(np.ceil((lon1 - lon0) / dlon)), int(np.ceil((lat1 - lat0) / dlat))
    grid = np.zeros((ny, nx))
    for r in meta.itertuples():
        t = np.linspace(0, 1, max(2, int(r.length / (cell_km * 250)) + 2))
        ix = ((r.site_0_lon + t * (r.site_1_lon - r.site_0_lon) - lon0) / dlon).astype(int)
        iy = ((r.site_0_lat + t * (r.site_1_lat - r.site_0_lat) - lat0) / dlat).astype(int)
        ok = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny)
        for j, i in set(zip(iy[ok], ix[ok])):
            grid[j, i] += 2 * r.n_radios
    return grid, (lon0, lon0 + nx * dlon, lat0, lat0 + ny * dlat)


def network_density(meta, cell_km=0.25, smooth=2.0, ax=None):
    """Sublinks crossing each cell of a `cell_km` grid, smoothed by `smooth` cells; empty cells are transparent."""
    from scipy.ndimage import gaussian_filter
    show = ax is None
    box = links_extent(meta)
    ax = map_axes(ax, figsize=(8, 10), extent=box)
    grid, ext = _cells(meta, cell_km, box)
    z = gaussian_filter(grid, smooth) if smooth else grid
    z = np.ma.masked_less(z, 0.05 * z.max())
    im = ax.imshow(z, origin="lower", extent=ext, cmap="inferno_r", alpha=0.8, zorder=3, interpolation="bilinear",
                   aspect=ASPECT)
    ax.set_xlim(box[:2]); ax.set_ylim(box[2:])
    stations(ax, label=False)
    scale_bar(ax)
    plt.colorbar(im, ax=ax, shrink=0.6, pad=0.02, label=f"directional links per {cell_km:g} km cell")
    ax.set_xlabel("longitude (°E)"); ax.set_ylabel("latitude (°N)")
    ax.set_title(f"Where the network is dense ({cell_km:g} km cells)")
    if show:
        plt.show()
    return ax


def network_table(meta):
    """Per band (V60 split at 63 GHz): paths, directional links, sites and the length range. A path with radios in
    two bands counts in both."""
    s = _sublinks(meta)
    per_path = s.groupby("cml_id").split.agg(set)
    rows = {}
    for b in SPLIT:
        qs = s[s.split == b]
        q = meta[meta.cml_id.isin(qs.cml_id)]
        ends = pd.concat([q[["site_0_lat", "site_0_lon"]].set_axis(["lat", "lon"], axis=1),
                          q[["site_1_lat", "site_1_lon"]].set_axis(["lat", "lon"], axis=1)]).round(5)
        rows[SPLIT_LABEL[b]] = {
            "directional links": len(qs), "paths": len(q),
            "f min (GHz)": qs.frequency.min() / 1000, "f max (GHz)": qs.frequency.max() / 1000,
            "sites": len(ends.drop_duplicates()), "median length (m)": q.length.median(),
            "shortest (m)": q.length.min(), "longest (m)": q.length.max(),
            "paths with another band": int((per_path[q.cml_id].map(len) > 1).sum())}
    out = pd.DataFrame(rows).T
    return out.round({"f min (GHz)": 2, "f max (GHz)": 2}).astype({k: int for k in out if "GHz" not in k})


def link_features(meta, fontsize=18):
    """Two separate figures: directional link counts and path lengths per band.

    fontsize controls tick and annotation sizes; headings are slightly larger.
    Returns (count_figure, length_figure) for saving separately.
    """
    s = _sublinks(meta)
    order = SPLIT[::-1]
    labels = [SPLIT_LABEL[b].replace(" (", "\n(") for b in order]
    count_fig, ax = plt.subplots(figsize=(14, 6), layout="constrained")
    counts = s.split.value_counts().reindex(order, fill_value=0)
    bars = ax.bar(range(len(order)), counts.values, width=.65,
                  color=[SPLIT_COLOR[b] for b in order], zorder=3)
    ax.bar_label(bars, padding=8, fontsize=fontsize + 2, weight="bold")
    ax.set_xticks(range(len(order)), labels, fontsize=fontsize)
    ax.tick_params(axis="y", labelsize=fontsize)
    ax.set_ylabel("Directional links", fontsize=fontsize + 2)
    ax.set_ylim(0, max(counts.max(), 1) * 1.20)
    ax.set_title(f"{len(s):,} directional links across {meta.cml_id.nunique():,} paths",
                 fontsize=fontsize + 4, pad=20)
    ax.grid(axis="x", visible=False)

    length_fig, ax = plt.subplots(figsize=(15, 7), layout="constrained")
    rng = np.random.default_rng(0)
    for k, b in enumerate(order):
        q = meta[meta.cml_id.isin(s[s.split == b].cml_id)].length.dropna()
        if q.empty:
            continue
        c = SPLIT_COLOR[b]
        ax.boxplot(q, positions=[k], vert=False, widths=0.6, showfliers=False,
                   medianprops=dict(color="k", lw=2.5), boxprops=dict(color=c, lw=2),
                   whiskerprops=dict(color=c, lw=2), capprops=dict(color=c, lw=2))
        ax.scatter(q, k + rng.uniform(-0.25, 0.25, len(q)), s=28, color=c, alpha=0.7, lw=0, zorder=3)
        ax.text(1.02, k, f"{len(q)} paths\nMedian: {q.median():,.0f} m",
                transform=ax.get_yaxis_transform(), va="center", fontsize=fontsize,
                color=c, weight="bold", clip_on=False)
    ax.set_yticks(range(len(order)), labels, fontsize=fontsize)
    ax.set_xscale("log")
    lengths = meta.length.dropna()
    positive = lengths[lengths > 0]
    ax.set_xlim(min(25, positive.min() * .8) if len(positive) else 25,
                max(4000, positive.max() * 1.15) if len(positive) else 4000)
    ax.set_xticks([30, 100, 300, 1000, 3000], ["30 m", "100 m", "300 m", "1 km", "3 km"])
    ax.tick_params(axis="x", which="major", labelsize=fontsize)
    ax.set_xlabel("Path length (log scale)", fontsize=fontsize + 2, labelpad=12)
    ax.grid(axis="y", visible=False)
    ax.set_title("Path length by frequency band", fontsize=fontsize + 4, pad=20)
    length_fig.text(.5, -.025, "Paths with radios in two bands appear in both rows.",
                    ha="center", fontsize=fontsize - 2, color=MUTED)
    plt.show()
    return count_fig, length_fig


def valid_periods():
    """First and last valid time of every variable, drawn as bars; returns the table."""
    rows = []
    for src, ds, dims in [("links", io.open_links(), ("cml_id", "sublink_id")), ("asos", io.asos(only_ok=False), ("id",))]:
        for v in [v for v in ds.data_vars if ds[v].dims[-1] == "time" and ds[v].dtype.kind == "f"]:
            t = ds[v].notnull().any(dims).to_series()
            t = t[t].index
            rows.append(dict(source=src, variable=v, first=t.min(), last=t.max()))
    cov = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(13, 3.4))
    for i, r in cov.iterrows():
        ax.plot([r["first"], r["last"]], [i, i], lw=6, solid_capstyle="butt",
                color="tab:blue" if r.source == "links" else "tab:green")
    for d in io.radar_events().day:
        ax.axvline(d, color="tab:purple", lw=1, alpha=0.6)
    ax.set_yticks(range(len(cov))); ax.set_yticklabels(cov.source + " · " + cov.variable, fontsize=8)
    ax.invert_yaxis(); ax.set_title("Valid data per variable (purple: the 10 radar days)")
    plt.tight_layout(); plt.show()
    return cov


def windows():
    """The averaging window of rsl_avg / rsl_max over time, and the stamps per period."""
    w = io.aggregation_window()
    t = w.index
    periods = pd.cut(t, pd.to_datetime(["2023-10-28 00:00", "2024-07-15 00:00", "2025-04-21 01:01", "2025-08-01 00:00",
                                        "2026-06-01 00:00"]),
                     labels=["2023-10 → 2024-07", "2024-07 → 2025-04 (1 h a day)", "2025-04 → 2025-08", "2025-08 →"])
    late = w[w != 60]
    fig, ax = plt.subplots(figsize=(13, 2.6))
    ax.scatter(late.index, late.values / 60, s=2, color="tab:orange"); ax.set_yscale("log")
    ax.set_ylabel("window (min)"); ax.set_title("Averaging window of rsl_avg / rsl_max (stamps that are not a plain minute)")
    plt.tight_layout(); plt.show()
    step = pd.Series(t.to_series().diff().dt.total_seconds().div(60).values, index=t)
    return pd.DataFrame({"stamps": step.groupby(periods, observed=True).size(),
                         "usual step (min)": step.groupby(periods, observed=True).agg(lambda s: s.round().mode().iloc[0])})


def availability(meta, H):
    """Share of hours with a value per path and month (from the hourly summary), and its distribution per band."""
    n = (H["n"].sel(sublink_id="sublink_1") > 0).to_pandas().T
    A = n.resample("MS").mean().T
    order = _order(meta)
    A = A.loc[order]
    band = meta.set_index("cml_id").band
    fig, axes = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw=dict(width_ratios=[3, 1]))
    im = axes[0].imshow(A.values, aspect="auto", cmap="Blues", vmin=0, vmax=1, interpolation="nearest")
    axes[0].set_xticks(range(0, A.shape[1], 3)); axes[0].set_xticklabels([f"{c:%Y-%m}" for c in A.columns[::3]], rotation=90)
    pos = np.cumsum([0] + [int((band == b).sum()) for b in ["V60", "K24", "C5"]])
    axes[0].set_yticks((pos[:-1] + pos[1:]) / 2); axes[0].set_yticklabels(["V60", "K24", "C5"])
    for y in pos[1:-1]:
        axes[0].axhline(y - 0.5, color="k", lw=1)
    axes[0].grid(False); axes[0].set_title("Share of hours with a value, per path and month")
    plt.colorbar(im, ax=axes[0], fraction=0.02)
    tot = n.mean()
    for b in BANDS:
        axes[1].hist(tot[band[band == b].index], bins=np.linspace(0, 1, 21), alpha=0.6, color=BAND_COLOR[b], label=b)
    axes[1].set_xlabel("share of hours with a value, whole record"); axes[1].set_ylabel("paths"); axes[1].legend()
    axes[1].set_title("Distribution")
    plt.tight_layout(); plt.show()


def show_case(day, title="", hours=36):
    """One path per band around a day (the one with the most data): level minus its median; the airport gauges'
    precipitation by type; temperature."""
    ds, meta = io.open_links(), io.link_meta()
    t0 = pd.Timestamp(day) - pd.Timedelta("6h"); t1 = t0 + pd.Timedelta(hours=hours)
    x = ds[["rsl", "rsl_avg"]].sel(time=slice(t0, t1), sublink_id=["sublink_1"]).load()
    n = (x.rsl.notnull() | x.rsl_avg.notnull()).sum(["time", "sublink_id"]).to_series()
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(14, 6.5), sharex=True, gridspec_kw=dict(height_ratios=[3, 1.4, 1]))
    for b in ["V60", "K24", "C5"]:
        ids = [c for c in meta[meta.band == b].cml_id if n.get(c, 0) > 0]
        if not ids:
            continue
        c = max(ids, key=lambda i: n[i])
        lvl = link_level(x, c)
        a1.plot(lvl.index, lvl - lvl.median(), ".-", ms=2, lw=0.8, color=BAND_COLOR[b], label=f"{b} · cml {c}")
    a1.set_ylabel("level − median (dB)"); a1.legend(fontsize=8); a1.set_title(title or f"{pd.Timestamp(day):%Y-%m-%d}")
    a = io.asos(start=t0, end=t1, only_ok=False)
    r = a.rainfall_amount.median("id").to_series().resample("10min", closed="right", label="right").sum() * 6
    cat = a.precip_category.to_pandas().T.mode(axis=1)[0].reindex(r.index, method="nearest")
    for k, cc in CAT_COLOR.items():
        m = cat == k
        a2.bar(r.index[m], r[m], width=-pd.Timedelta("10min"), align="edge", color=cc, label=k)
    a2.set_ylabel("gauges (mm/h)"); a2.legend(fontsize=8, ncol=4)
    a3.plot(a.temperature.median("id").to_series().resample("10min").mean(), color="k")
    a3.axhline(0, color="0.6", ls="--", lw=1); a3.set_ylabel("°C")
    plt.tight_layout(); plt.show()


def radar_maps(meta):
    """The ten radar days: daily total (liquid equivalent) with the 24 / 60 GHz paths."""
    kv = meta[meta.band != "C5"]
    fig, axes = plt.subplots(2, 5, figsize=(16, 6.6))
    for ax, e in zip(axes.flat, io.radar_events().itertuples()):
        r = io.radar(e.kind, e.day)
        tot = r.rainfall_amount_1h.sum("time_1h")
        im = ax.pcolormesh(r.lon, r.lat, tot, cmap="Blues", vmin=0, vmax=max(20, float(tot.quantile(0.98))), shading="auto")
        for q in kv.itertuples():
            ax.plot([q.site_0_lon, q.site_1_lon], [q.site_0_lat, q.site_1_lat], color="k", lw=1.2)
        ax.set_title(f"{e.kind} {e.day:%Y-%m-%d} · {float(tot.mean()):.0f} mm", fontsize=9)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect(ASPECT); ax.grid(False)
        plt.colorbar(im, ax=ax, fraction=0.04)
    plt.suptitle("MRMS daily total (mm, liquid equivalent) with the 24 / 60 GHz paths", x=0.01, ha="left",
                 fontweight="bold")
    plt.tight_layout(); plt.show()


def radar_along_links(meta, kind="rain"):
    """The wettest day of a kind: the radar field, and every path coloured by the radar rain along it."""
    e = io.radar_events().query("kind == @kind").sort_values("radar_mean_mm").iloc[-1]
    r = io.radar(e.kind, e.day)
    tot = r.rainfall_amount_1h.sum("time_1h")
    path = {q.cml_id: float(radar_along_link(r.rainfall_amount_1h, q.site_0_lat, q.site_0_lon, q.site_1_lat,
                                             q.site_1_lon).sum()) for q in meta.itertuples()}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(15, 7))
    a1.pcolormesh(r.lon, r.lat, tot, cmap="Blues", shading="auto")
    draw_links(a1, meta, lw=1.2); a1.legend(loc="upper left")
    a1.set_xlim(EXTENT[:2]); a1.set_ylim(EXTENT[2:]); a1.set_aspect(ASPECT); a1.grid(False)
    a1.set_title(f"MRMS daily total, {e.day:%Y-%m-%d}")
    map_axes(a2)
    cmap, norm = plt.cm.viridis, plt.Normalize(min(path.values()), max(path.values()))
    for q in meta.itertuples():
        a2.plot([q.site_0_lon, q.site_1_lon], [q.site_0_lat, q.site_1_lat], color=cmap(norm(path[q.cml_id])),
                lw=1 if q.band == "C5" else 3)
    plt.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=a2, fraction=0.04, label="radar rain on the path (mm)")
    a2.set_title("Each path coloured by the radar rain along it")
    plt.tight_layout(); plt.show()


def _order(meta):
    """Path ids sorted by band (V60, K24, C5), then by number."""
    rank = {"V60": 0, "K24": 1, "C5": 2}
    return meta.assign(_b=meta.band.map(rank), _n=meta.cml_id.astype(int)).sort_values(["_b", "_n"]).cml_id.tolist()


def accumulation(res):
    """Per radar day from analysis.rain_accumulation: the accumulation over the UTC day, each picked path thin, their
    median bold, the radar along the same paths, the gauges and the GHCN day total. The y-axis ends a little above the
    highest of the median and the references, so a path far above them is cut."""
    fig, axes = plt.subplots(1, len(res), figsize=(5.2 * len(res), 4.2), squeeze=False)
    for ax, (day, r) in zip(axes[0], res.items()):
        cum = (r["R"] / 60).cumsum("time")
        med = cum.median("cml_id")
        rad = r["rad"].cumsum("time").median("cml_id")
        gau = r["asos"].fillna(0).cumsum("time").median("id")
        ax.plot(cum.time, cum.T, color=BAND_COLOR["V60"], lw=0.5, alpha=0.3)
        ax.plot(cum.time, med, color=BAND_COLOR["V60"], lw=2.5, label="links (median)")
        ax.step(rad.time, rad, where="post", color="tab:purple", lw=2, label="radar along the paths")
        ax.plot(gau.time, gau, color="k", lw=1.5, label=f"ASOS (median of {r['asos'].sizes['id']})")
        ax.axhline(r["ghcn"].median(), color="tab:green", ls="--", label="GHCN day total")
        top = max(float(med.max()), float(rad.max()), float(gau.max()), float(r["ghcn"].median()))
        ax.set_ylim(0, top * 1.15); ax.set_ylabel("accumulated rain [mm]")
        ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%H:%M"))
        ax.set_title(f"{day} (UTC)", loc="left", fontsize=10)
    axes[0, 0].legend(fontsize=8, loc="upper left")
    plt.tight_layout(); plt.show()


BLACKOUTS = [("17", "2024-07-13 05:30", "2024-07-13 14:30"), ("22", "2024-06-06 15:00", "2024-06-06 23:00"),
             ("39", "2024-05-23 10:00", "2024-05-23 18:00")]


def blackouts(cases=BLACKOUTS):
    """Paths that go dark in heavy rain: for each (cml_id, start, end), every sublink's level (steady before, falling
    as the rain arrives), the blackout of the path's highest radio shaded grey, its lowest level heard (about the
    receiver's floor) dashed; below, the 10-min rain rate at the nearest gauge."""
    ds, st, a = io.open_links(), io.asos_stations(), io.asos()
    from .analysis import nearest
    fig, axes = plt.subplots(2 * len(cases), 1, figsize=(14, 3.6 * len(cases)),
                             gridspec_kw=dict(height_ratios=[2.2, 1] * len(cases)))
    for k, (c, t0, t1) in enumerate(cases):
        a1, a2 = axes[2 * k], axes[2 * k + 1]
        x = ds.sel(cml_id=c, time=slice(t0, t1))
        q = x.isel(sublink_id=0)
        near = nearest(st, float(q.site_0_lat + q.site_1_lat) / 2, float(q.site_0_lon + q.site_1_lon) / 2)
        lvl = x.rsl.fillna(x.rsl_avg)
        subs = [s for s in x.sublink_id.values if int(lvl.sel(sublink_id=s).notnull().sum())]
        for s in subs:
            a1.plot(lvl.time, lvl.sel(sublink_id=s), ".", ms=2.5,
                    label=f"{s} ({float(x.frequency.sel(sublink_id=s)) / 1000:.1f} GHz)")
        top = [s for s in ("sublink_1", "sublink_2") if s in subs]           # the path's highest radio
        dark = lvl.sel(sublink_id=top).isnull().all("sublink_id").to_series()
        run = (dark != dark.shift()).cumsum()
        for _, r in dark[dark].groupby(run[dark]):
            if len(r) >= 5:
                a1.axvspan(r.index[0], r.index[-1], color="0.8", lw=0, zorder=0)
        low = float(lvl.sel(sublink_id=top).min())
        a1.axhline(low, color="k", ls="--", lw=0.8, label=f"lowest heard {low:.0f} dBm")
        a1.set_ylabel("level [dBm]"); a1.legend(fontsize=7, loc="lower left", ncol=3)
        a1.set_title(f"cml {c}: {float(q.frequency) / 1000:.1f} GHz, {float(q.length) / 1000:.1f} km "
                     f"(grey: no value from the {float(q.frequency) / 1000:.0f} GHz radio)", loc="left", fontsize=10)
        r = a.rainfall_amount.sel(id=near.index[0], time=slice(t0, t1)).to_series().rolling(10, min_periods=5).sum() * 6
        a2.fill_between(r.index, r.values, color="tab:blue", step="mid")
        a2.set_ylabel("rain [mm/h]")
        a2.set_title(f"ASOS {near.index[0]} ({near.distance_m.iloc[0] / 1000:.1f} km away), 10-min rate", loc="left", fontsize=9)
        for ax in (a1, a2):
            ax.set_xlim(pd.Timestamp(t0), pd.Timestamp(t1))
            ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%m-%d %H:%M"))
    plt.tight_layout(); plt.show()



# Examples of how a path recovers after rain and snow (Jacoby et al., ACM SenSys 2027): (title, cml_id, sublink,
# event start, event end), UTC. start == end: no event (a dry stretch, the baseline). Event windows from the
# gauges and the wet-bulb temperature, as in the paper.
ANTENNA = [("dry baseline (no precipitation)", "38", "sublink_1", "2026-06-03 12:00", "2026-06-03 12:00"),
           ("rain: recovers at once", "14", "sublink_1", "2026-08-20 18:00", "2026-08-21 03:00"),
           ("warm (wet) snow: slow recovery", "16", "sublink_1", "2024-02-13 05:00", "2024-02-13 18:00"),
           ("cold snow: stays attenuated", "16", "sublink_1", "2024-01-16 02:00", "2024-01-16 23:00"),
           ("cold snow: stays attenuated for a day after", "26", "sublink_1", "2026-01-25 11:00", "2026-01-26 18:00"),
           ("warm snow: persistent, 5 GHz", "200", "sublink_2", "2026-02-22 12:00", "2026-02-23 21:00")]


def antenna_examples(cases=ANTENNA, before=24, after=48):
    """For each (title, cml_id, sublink, start, end): the level from `before` hours before the event end to `after`
    hours after it, the event shaded, and the dry level dashed (the median of the 24 h before the event). Rain
    leaves the antenna quickly; wet snow and ice on the antenna or radome keep a path attenuated for hours or days."""
    from .analysis import link_level
    ds = io.open_links()
    fig, axes = plt.subplots(2, 3, figsize=(16, 7.5))
    for ax, (title, c, s, t0, t1) in zip(axes.ravel(), cases):
        t0, t1 = pd.Timestamp(t0), pd.Timestamp(t1)
        lv = link_level(ds, c, s)
        base = lv[t0 - pd.Timedelta("24h"):t0].median()
        w = lv[t1 - pd.Timedelta(f"{before}h"):t1 + pd.Timedelta(f"{after}h")]
        h = (w.index - t1) / pd.Timedelta("1h")
        col = "tab:gray" if t0 == t1 else ("tab:blue" if "rain" in title else
                                            "tab:green" if "cold" in title else "tab:orange")
        ax.plot(h, w.values, color=col, lw=0.9)
        if t1 > t0:
            ax.axvspan(-(t1 - t0) / pd.Timedelta("1h"), 0, color=col, alpha=0.12, lw=0)
        ax.axhline(base, color="k", ls="--", lw=0.8, label=f"dry level {base:.0f} dBm")
        ax.set_xlim(-before, after)
        f = float(ds.frequency.sel(cml_id=c, sublink_id=s))
        ax.set_title(f"{title}\ncml {c} {s}, {f / 1000:.1f} GHz, {t0:%Y-%m-%d}", loc="left", fontsize=9)
        ax.legend(fontsize=7, loc="lower right")
    for ax in axes[1]:
        ax.set_xlabel("hours from the end of the event")
    for ax in axes[:, 0]:
        ax.set_ylabel("level [dBm]")
    fig.text(0.5, -0.01, "shaded: the event; dashed: the level in the 24 h before it", ha="center", fontsize=9)
    plt.tight_layout(); plt.show()


def baseline_methods(cml_id="14", sublink="sublink_1", start="2026-08-19 12:00", end="2026-08-22 00:00",
                     event=("2026-08-20 18:00", "2026-08-21 03:00"), window="24h"):
    """Two simple dry baselines for one path and event, and the attenuation A = baseline - level from each:
    a constant baseline (the median of the 24 h before the event) and a rolling median (`analysis.attenuation`,
    centred `window`). Below, the 10-min rain rate at the nearest gauge. Examples only: a retrieval also needs
    wet/dry classification and a wet-antenna term."""
    from .analysis import attenuation, link_level, nearest
    ds, st, a = io.open_links(), io.asos_stations(), io.asos()
    t0, t1, e0, e1 = map(pd.Timestamp, (start, end, *event))
    lv = link_level(ds, cml_id, sublink)
    const = lv[e0 - pd.Timedelta("24h"):e0].median()
    roll = lv.rolling(window, center=True, min_periods=10).median()
    a_const, a_roll = const - lv, attenuation(lv, window)
    lv, roll, a_const, a_roll = (s[t0:t1] for s in (lv, roll, a_const, a_roll))
    x = ds.sel(cml_id=cml_id, sublink_id=sublink)
    near = nearest(st, float(x.site_0_lat + x.site_1_lat) / 2, float(x.site_0_lon + x.site_1_lon) / 2)
    r = a.rainfall_amount.where(a.rainfall_flag == 0).sel(id=near.index[0], time=slice(t0, t1)).to_series()
    r = r.resample("10min", closed="right", label="right").sum(min_count=5) * 6
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(14, 8.5), sharex=True, gridspec_kw=dict(height_ratios=[2, 1.6, 1]))
    for ax in (a1, a2, a3):
        ax.axvspan(e0, e1, color="tab:blue", alpha=0.08, lw=0)
    a1.plot(lv.index, lv.values, color="0.3", lw=0.8, label="level")
    a1.axhline(const, color="tab:red", ls="--", lw=1, label=f"constant: median of the 24 h before ({const:.0f} dBm)")
    a1.plot(roll.index, roll.values, color="tab:green", lw=1.2, label=f"rolling median ({window}, centred)")
    a1.set_ylabel("level [dBm]"); a1.legend(fontsize=8, loc="lower left")
    f = float(x.frequency)
    a1.set_title(f"cml {cml_id} {sublink}, {f / 1000:.1f} GHz, {float(x.length) / 1000:.1f} km: two dry baselines",
                 loc="left", fontsize=10)
    a2.plot(a_const.index, a_const.values, color="tab:red", lw=0.9, label="A from the constant baseline")
    a2.plot(a_roll.index, a_roll.values, color="tab:green", lw=0.9, label="A from the rolling median")
    a2.axhline(0, color="k", lw=0.6); a2.set_ylabel("A [dB]"); a2.legend(fontsize=8, loc="upper left")
    a3.fill_between(r.index, r.values, color="tab:blue", step="pre")
    a3.set_ylabel("rain [mm/h]")
    a3.set_title(f"ASOS {near.index[0]} ({near.distance_m.iloc[0] / 1000:.1f} km away), 10-min rate", loc="left", fontsize=9)
    a3.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%m-%d %H:%M"))
    plt.tight_layout(); plt.show()
