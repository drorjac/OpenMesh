"""
metadata_utils.py
-----------------
Pure utility functions for mesh_metadata processing.
No config, no main, no argparse — import and call from a notebook or script.

Public API
----------
  load_mesh(path)                          -> pd.DataFrame
  build_groups(df, thr)                    -> dict
  convert(df, groups, ...)                 -> (pd.DataFrame, dict)
  main(input_path, output_csv, ...)        -> (pd.DataFrame, dict)
  lookup_by_coords(links_df, lat, lon, ...) -> pd.DataFrame
"""

import json
import math
import pandas as pd
from pathlib import Path


# ── geo helpers ───────────────────────────────────────────────────────────────

def haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in metres between two lat/lon points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _close(lat1, lon1, lat2, lon2, thr) -> bool:
    try:
        return haversine_m(float(lat1), float(lon1), float(lat2), float(lon2)) <= thr
    except (TypeError, ValueError):
        return False


def _links_match(a0lat, a0lon, a1lat, a1lon,
                 b0lat, b0lon, b1lat, b1lon, thr) -> bool:
    """True if two rows describe the same physical link (either direction)."""
    fwd = _close(a0lat, a0lon, b0lat, b0lon, thr) and _close(a1lat, a1lon, b1lat, b1lon, thr)
    rev = _close(a0lat, a0lon, b1lat, b1lon, thr) and _close(a1lat, a1lon, b0lat, b0lon, thr)
    return fwd or rev


# ── coordinate validation & fix ───────────────────────────────────────────────

def fix_coords(df: pd.DataFrame,
               lat_min=40.4, lat_max=41.0,
               lon_min=-74.4, lon_max=-73.5) -> pd.DataFrame:
    """
    1. Auto-flip positive longitudes (missing minus sign, e.g. 73.95 -> -73.95).
    2. Drop rows whose endpoints still fall outside the bounding box.
    """
    df = df.copy()
    fixed = 0
    for col in ["site_0_lon", "site_1_lon"]:
        mask = df[col] > 0
        if mask.any():
            df.loc[mask, col] = -df.loc[mask, col]
            fixed += int(mask.sum())
    if fixed:
        print(f"  [coord fix] flipped sign on {fixed} longitude value(s)")

    valid = (
        df["site_0_lat"].between(lat_min, lat_max) &
        df["site_0_lon"].between(lon_min, lon_max) &
        df["site_1_lat"].between(lat_min, lat_max) &
        df["site_1_lon"].between(lon_min, lon_max)
    )
    bad = int((~valid).sum())
    if bad:
        print(f"  [coord fix] dropped {bad} row(s) outside bbox "
              f"lat[{lat_min},{lat_max}] lon[{lon_min},{lon_max}]:")
        print(df[~valid][["cml_id", "tx_name", "rx_name",
                           "site_0_lat", "site_0_lon",
                           "site_1_lat", "site_1_lon"]].to_string())
    return df[valid].reset_index(drop=True)


# ── load ──────────────────────────────────────────────────────────────────────

def load_mesh(path,
              lat_min=40.4, lat_max=41.0,
              lon_min=-74.4, lon_max=-73.5) -> pd.DataFrame:
    """Load mesh_metadata CSV, fix coordinates, return clean DataFrame."""
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    df = fix_coords(df, lat_min, lat_max, lon_min, lon_max)
    return df


# ── grouping ──────────────────────────────────────────────────────────────────

def build_groups(df: pd.DataFrame, thr: float = 10.0) -> dict[int, list[int]]:
    """
    Group rows into CMLs.

    Two rows → same CML if:
      - They share the same sorted (tx_id, rx_id) pair  [fast path]
      - OR both endpoints are within `thr` metres        [proximity fallback]

    Returns {group_id: [df_row_indices]}.
    """
    groups:  list[list[int]] = []
    reps:    list[tuple]     = []      # (lat0, lon0, lat1, lon1) per group
    id_to_g: dict[tuple, int] = {}

    for idx, row in df.iterrows():
        id_key = tuple(sorted([str(row["tx_id"]), str(row["rx_id"])]))
        lat0, lon0 = row["site_0_lat"], row["site_0_lon"]
        lat1, lon1 = row["site_1_lat"], row["site_1_lon"]

        gid = id_to_g.get(id_key)

        if gid is None:
            for g, (rl0, ro0, rl1, ro1) in enumerate(reps):
                if _links_match(lat0, lon0, lat1, lon1, rl0, ro0, rl1, ro1, thr):
                    gid = g
                    break

        if gid is None:
            gid = len(groups)
            groups.append([])
            reps.append((lat0, lon0, lat1, lon1))

        groups[gid].append(idx)
        id_to_g.setdefault(id_key, gid)

    return {i: v for i, v in enumerate(groups)}


# ── pipeline helpers ──────────────────────────────────────────────────────────

_DEDUP_COLS = ["site_0_lat", "site_0_lon", "site_1_lat", "site_1_lon",
               "frequency", "polarization"]


def _dedup(sub: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in _DEDUP_COLS if c in sub.columns]
    return sub.drop_duplicates(subset=cols, keep="first")


def _length_filter(sub, min_m, drop_cml_if_all_missing):
    if min_m <= 0:
        return sub, False
    lengths = pd.to_numeric(sub["length"], errors="coerce")
    if lengths.isna().all() and drop_cml_if_all_missing:
        return sub.iloc[0:0], True
    return sub[lengths.fillna(0) >= min_m], False


def _freq_filter(sub, min_freq_mhz, drop_cml_if_all_missing):
    freqs = pd.to_numeric(sub["frequency"], errors="coerce")
    if freqs.isna().all() and drop_cml_if_all_missing:
        return sub.iloc[0:0], True
    if min_freq_mhz <= 0:
        return sub, False
    return sub[freqs.fillna(0) >= min_freq_mhz], False


def _norm_freq_mhz(val, units: str):
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    u = str(units).strip().lower()
    if u == "ghz":
        return round(f * 1_000, 2)
    if u == "khz":
        return round(f / 1_000, 2)
    return round(f, 2)


def _device_name(tx, rx) -> str:
    parts = [str(n).strip() for n in [tx, rx] if pd.notna(n) and str(n).strip()]
    return " <-> ".join(parts) if parts else "unknown"


# ── conversion ────────────────────────────────────────────────────────────────

def convert(df: pd.DataFrame,
            groups: dict,
            min_length_m: float = 10.0,
            min_freq_mhz: float = 0.0,
            drop_cml_if_all_length_missing: bool = False,
            drop_cml_if_all_freq_missing:   bool = False,
            ) -> tuple[pd.DataFrame, dict]:
    """
    Convert grouped raw rows into links_metadata format.

    Parameters
    ----------
    df                             : raw mesh DataFrame (from load_mesh)
    groups                         : output of build_groups()
    min_length_m                   : drop sublinks shorter than this (0 = keep all)
    min_freq_mhz                   : drop sublinks below this freq  (0 = keep all)
    drop_cml_if_all_length_missing : drop entire CML if all sublinks have no length
    drop_cml_if_all_freq_missing   : drop entire CML if all sublinks have no frequency

    Returns
    -------
    links_df : pd.DataFrame  — links_metadata-compatible table
    mapping  : dict          — cml_id -> all original fields per sublink
    """
    links_rows, mapping = [], {}
    new_id = 0

    for _, idxs in groups.items():
        sub = df.loc[idxs]
        sub = _dedup(sub)

        sub, drop = _length_filter(sub, min_length_m, drop_cml_if_all_length_missing)
        if drop or sub.empty:
            continue

        sub, drop = _freq_filter(sub, min_freq_mhz, drop_cml_if_all_freq_missing)
        if drop or sub.empty:
            continue

        new_id += 1
        rep      = sub.iloc[0]
        dev_name = _device_name(rep.get("tx_name"), rep.get("rx_name"))

        sl_entries = []
        for sl_num, (_, sl) in enumerate(sub.iterrows(), start=1):
            sl_id = f"sublink_{sl_num}"
            freq  = _norm_freq_mhz(sl.get("frequency"), sl.get("frequency_units", ""))
            pol   = sl.get("polarization")
            pol   = str(pol).strip() if pd.notna(pol) and str(pol).strip() else None

            links_rows.append({
                "cml_id"          : new_id,
                "sublink_id"      : sl_id,
                "device_name"     : dev_name,
                "site_0_lat"      : sl.get("site_0_lat"),
                "site_0_lon"      : sl.get("site_0_lon"),
                "site_0_elevation": sl.get("site_0_elevation"),
                "site_0_altitude" : sl.get("site_0_altitude"),
                "site_1_lat"      : sl.get("site_1_lat"),
                "site_1_lon"      : sl.get("site_1_lon"),
                "site_1_elevation": sl.get("site_1_elevation"),
                "site_1_altitude" : sl.get("site_1_altitude"),
                "frequency"       : freq,
                "frequency_units" : "MHz",
                "length"          : sl.get("length"),
                "polarization"    : pol,
                "tsl"             : sl.get("tsl"),
                "rsl"             : sl.get("rsl"),
            })

            sl_entries.append({
                "sublink_id"         : sl_id,
                "original_cml_id"    : sl.get("cml_id"),
                "original_sublink_id": sl.get("sublink_id"),
                "tx_id"              : sl.get("tx_id"),
                "tx_name"            : sl.get("tx_name"),
                "rx_id"              : sl.get("rx_id"),
                "rx_name"            : sl.get("rx_name"),
                "time"               : sl.get("time"),
                "site_0_lat"         : sl.get("site_0_lat"),
                "site_0_lon"         : sl.get("site_0_lon"),
                "site_0_elevation"   : sl.get("site_0_elevation"),
                "site_0_altitude"    : sl.get("site_0_altitude"),
                "site_1_lat"         : sl.get("site_1_lat"),
                "site_1_lon"         : sl.get("site_1_lon"),
                "site_1_elevation"   : sl.get("site_1_elevation"),
                "site_1_altitude"    : sl.get("site_1_altitude"),
                "length"             : sl.get("length"),
                "frequency_raw"      : sl.get("frequency"),
                "frequency_units"    : sl.get("frequency_units"),
                "frequency_mhz"      : freq,
                "tsl"                : sl.get("tsl"),
                "rsl"                : sl.get("rsl"),
                "polarization"       : sl.get("polarization"),
            })

        mapping[new_id] = {
            "cml_id"      : new_id,
            "device_name" : dev_name,
            "tx_id"       : rep.get("tx_id"),
            "tx_name"     : rep.get("tx_name"),
            "rx_id"       : rep.get("rx_id"),
            "rx_name"     : rep.get("rx_name"),
            "num_sublinks": len(sl_entries),
            "sublinks"    : sl_entries,
        }

    return pd.DataFrame(links_rows), mapping


# ── main pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(
    input_path:                    str,
    output_csv:                    str   = "links_metadata_output.csv",
    output_json:                   str   = "links_mapping.json",
    # --- grouping ---
    same_loc_m:                    float = 10.0,
    # --- filters ---
    min_length_m:                  float = 10.0,
    min_freq_mhz:                  float = 0.0,
    drop_cml_if_all_length_missing: bool = False,
    drop_cml_if_all_freq_missing:   bool = False,
    # --- bounding box ---
    lat_min: float = 40.4,  lat_max: float = 41.0,
    lon_min: float = -74.4, lon_max: float = -73.5,
) -> tuple[pd.DataFrame, dict]:
    """
    Full pipeline: load -> fix coords -> group -> convert -> save.

    Returns (links_df, mapping) so you can keep working with them
    in the notebook without re-reading from disk.
    """
    print(f"Loading      : {input_path}")
    df = load_mesh(input_path, lat_min, lat_max, lon_min, lon_max)
    print(f"  Source rows: {len(df)}")

    print(f"Grouping     (same-location threshold = {same_loc_m} m) ...")
    groups = build_groups(df, thr=same_loc_m)
    print(f"  Raw groups : {len(groups)}")

    print(f"Converting   (length >= {min_length_m} m, freq >= {min_freq_mhz} MHz) ...")
    links_df, mapping = convert(
        df, groups,
        min_length_m=min_length_m,
        min_freq_mhz=min_freq_mhz,
        drop_cml_if_all_length_missing=drop_cml_if_all_length_missing,
        drop_cml_if_all_freq_missing=drop_cml_if_all_freq_missing,
    )

    n_cmls = links_df["cml_id"].nunique() if not links_df.empty else 0
    print(f"  CMLs       : {n_cmls}")
    print(f"  Sublinks   : {len(links_df)}")

    # Re-number cml_ids sorted by highest frequency first
    if not links_df.empty:
        max_freq = links_df.groupby("cml_id")["frequency"].max().reset_index()
        max_freq.columns = ["cml_id", "_max_freq"]
        max_freq = max_freq.sort_values("_max_freq", ascending=False, na_position="last")
        old_to_new = {old: new for new, old in enumerate(max_freq["cml_id"], start=1)}
        links_df["cml_id"] = links_df["cml_id"].map(old_to_new)
        links_df = links_df.sort_values(["cml_id", "sublink_id"]).reset_index(drop=True)
        mapping  = {old_to_new[k]: v for k, v in mapping.items()}
        for v in mapping.values():
            v["cml_id"] = old_to_new.get(v["cml_id"], v["cml_id"])

    links_df.to_csv(output_csv, index=False)
    print(f"Saved CSV    : {output_csv}")

    with open(output_json, "w") as f:
        json.dump(mapping, f, indent=2, default=str)
    print(f"Saved JSON   : {output_json}")

    return links_df, mapping


# ── coordinate-based lookup ───────────────────────────────────────────────────

def lookup_by_coords(
    links_df: pd.DataFrame,
    lat:      float,
    lon:      float,
    radius_m: float = 50.0,
    site:     str   = "any",    # "site_0" | "site_1" | "any"
) -> pd.DataFrame:
    """
    Given a lat/lon point, return all raw rows whose matching endpoint
    falls within radius_m metres. Sorted by distance ascending.

    Extra columns added to output:
      matched_site : "site_0" | "site_1" | "both"
      distance_m   : closest endpoint distance in metres
    """
    results = []

    for _, row in links_df.iterrows():
        d0 = d1 = None

        if site in ("site_0", "any"):
            try:
                d0 = haversine_m(lat, lon, float(row["site_0_lat"]), float(row["site_0_lon"]))
            except (TypeError, ValueError):
                pass

        if site in ("site_1", "any"):
            try:
                d1 = haversine_m(lat, lon, float(row["site_1_lat"]), float(row["site_1_lon"]))
            except (TypeError, ValueError):
                pass

        hit0 = d0 is not None and d0 <= radius_m
        hit1 = d1 is not None and d1 <= radius_m

        if not hit0 and not hit1:
            continue

        if   hit0 and hit1: matched, dist = "both",   min(d0, d1)
        elif hit0:          matched, dist = "site_0", d0
        else:               matched, dist = "site_1", d1

        entry = row.to_dict()
        entry["matched_site"] = matched
        entry["distance_m"]   = round(dist, 2)
        results.append(entry)

    if not results:
        return pd.DataFrame(columns=list(links_df.columns) + ["matched_site", "distance_m"])

    return pd.DataFrame(results).sort_values("distance_m").reset_index(drop=True)


# ── field-based filter ────────────────────────────────────────────────────────

def filter_by_fields(
    links_df: pd.DataFrame,
    filters:  dict,
) -> pd.DataFrame:
    """
    General row filter: keep rows where every key matches its value(s).

    Parameters
    ----------
    links_df : pd.DataFrame
        The converted links_metadata dataframe.

    filters : dict
        Keys   = column name (str) or tuple of column names.
        Values = a single value, a list of accepted values,
                 or a tuple of values that must correspond
                 to the matching tuple of columns.

        Examples
        --------
        # Single field, exact value
        {"polarization": "v"}

        # Single field, any of a list
        {"polarization": ["v", "h"]}

        # Single field, numeric range with a callable
        {"frequency": lambda f: f is not None and f >= 5000}

        # Two fields that must match together as a pair
        {("site_0_lat", "site_0_lon"): (40.696, -73.940)}

        # Multiple independent filters combined (AND logic)
        {
            "polarization": "v",
            "frequency":    lambda f: f and f >= 5000,
            ("site_0_lat", "site_0_lon"): (40.696, -73.940),
        }

    Returns
    -------
    pd.DataFrame
        Filtered rows, index reset. Empty DataFrame if nothing matched.

    Notes
    -----
    - All filters are combined with AND logic.
    - NaN values never match exact / list checks; they can match a callable
      that explicitly handles them.
    - Tuple-key filters do an exact equality check on the combined values.
    """
    mask = pd.Series(True, index=links_df.index)

    for key, value in filters.items():

        # ── tuple of columns → must match a corresponding tuple of values ──
        if isinstance(key, tuple):
            cols = list(key)
            for c in cols:
                if c not in links_df.columns:
                    raise KeyError(f"filter_by_fields: column '{c}' not found. "
                                   f"Available: {list(links_df.columns)}")
            if not isinstance(value, tuple) or len(value) != len(cols):
                raise ValueError(
                    f"filter_by_fields: tuple key {key} requires a matching "
                    f"tuple of {len(cols)} value(s), got: {value!r}"
                )
            row_mask = pd.Series(True, index=links_df.index)
            for c, v in zip(cols, value):
                row_mask &= links_df[c] == v
            mask &= row_mask

        # ── single column ──────────────────────────────────────────────────
        else:
            col = key
            if col not in links_df.columns:
                raise KeyError(f"filter_by_fields: column '{col}' not found. "
                               f"Available: {list(links_df.columns)}")

            # callable / lambda → apply row-by-row
            if callable(value):
                mask &= links_df[col].apply(value)

            # list of accepted values → isin
            elif isinstance(value, list):
                mask &= links_df[col].isin(value)

            # single exact value
            else:
                mask &= links_df[col] == value

    return links_df[mask].reset_index(drop=True)


# ── elevation from df ─────────────────────────────────────────────────────────

def get_elevation_from_df(
    links_df: pd.DataFrame,
    coords:   list[tuple[float, float]],
    radius_m: float = 50.0,
) -> pd.DataFrame:
    """
    For each (lat, lon) in coords, find the closest matching site in links_df
    and return its elevation fields directly from the dataframe.

    Parameters
    ----------
    links_df  : the converted links_metadata dataframe
    coords    : list of (lat, lon) tuples to look up
    radius_m  : search radius in metres (default 50 m)

    Returns
    -------
    pd.DataFrame, one row per input coord, with columns:
        query_lat, query_lon,
        matched_site, distance_m,
        cml_id, device_name, sublink_id,
        site_0_elevation, site_0_altitude,
        site_1_elevation, site_1_altitude,
        elevation        <- best available: elevation if present, else altitude
    """
    rows = []
    for lat, lon in coords:
        hit = lookup_by_coords(links_df, lat, lon, radius_m=radius_m)

        if hit.empty:
            rows.append({
                "query_lat": lat, "query_lon": lon,
                "matched_site": None, "distance_m": None,
                "cml_id": None, "device_name": None, "sublink_id": None,
                "site_0_elevation": None, "site_0_altitude": None,
                "site_1_elevation": None, "site_1_altitude": None,
                "elevation": None,
            })
            continue

        best = hit.iloc[0]   # closest match
        ms   = best["matched_site"]

        # pick the elevation/altitude of the matched site
        if ms in ("site_0", "both"):
            elev = best.get("site_0_elevation")
            alt  = best.get("site_0_altitude")
        else:
            elev = best.get("site_1_elevation")
            alt  = best.get("site_1_altitude")

        value = (None if pd.isna(elev) else float(elev)) or \
                (None if pd.isna(alt)  else float(alt))

        rows.append({
            "query_lat"       : lat,
            "query_lon"       : lon,
            "matched_site"    : ms,
            "distance_m"      : best["distance_m"],
            "cml_id"          : best.get("cml_id"),
            "device_name"     : best.get("device_name"),
            "sublink_id"      : best.get("sublink_id"),
            "site_0_elevation": best.get("site_0_elevation"),
            "site_0_altitude" : best.get("site_0_altitude"),
            "site_1_elevation": best.get("site_1_elevation"),
            "site_1_altitude" : best.get("site_1_altitude"),
            "elevation"       : value,
        })

    return pd.DataFrame(rows)


# ── link lookup ───────────────────────────────────────────────────────────────

def find_link(
    links_df: pd.DataFrame,
    site_a:   tuple[float, float],
    site_b:   tuple[float, float] = None,
    radius_m: float = 50.0,
) -> pd.DataFrame:
    """
    Find links in links_df by one or two endpoint coordinates.

    Parameters
    ----------
    links_df : the converted links_metadata dataframe
    site_a   : (lat, lon) — first endpoint (required)
    site_b   : (lat, lon) — second endpoint (optional)
                 If given, both endpoints must match the same row
                 (direction-agnostic: A->B or B->A both match).
    radius_m : match tolerance in metres (default 50 m)

    Returns
    -------
    pd.DataFrame — matching rows, sorted by distance to site_a.
    Adds columns: matched_site_a, matched_site_b (if site_b given),
                  distance_a_m, distance_b_m (if site_b given).

    Examples
    --------
        # All links touching one site
        find_link(links_df, site_a=(40.720668, -73.988049))

        # The specific link between two sites
        find_link(links_df,
                  site_a=(40.720668, -73.988049),
                  site_b=(40.725903, -73.983635))
    """
    lat_a, lon_a = site_a

    results = []

    for _, row in links_df.iterrows():
        # distances from site_a to both endpoints of this row
        try:
            d_a0 = haversine_m(lat_a, lon_a, float(row["site_0_lat"]), float(row["site_0_lon"]))
        except (TypeError, ValueError):
            d_a0 = float("inf")
        try:
            d_a1 = haversine_m(lat_a, lon_a, float(row["site_1_lat"]), float(row["site_1_lon"]))
        except (TypeError, ValueError):
            d_a1 = float("inf")

        hit_a0 = d_a0 <= radius_m
        hit_a1 = d_a1 <= radius_m

        if not hit_a0 and not hit_a1:
            continue   # site_a doesn't touch this row at all

        # which end matched site_a
        if hit_a0 and hit_a1:
            matched_a = "both"
            dist_a    = min(d_a0, d_a1)
        elif hit_a0:
            matched_a = "site_0"
            dist_a    = d_a0
        else:
            matched_a = "site_1"
            dist_a    = d_a1

        entry = row.to_dict()
        entry["matched_site_a"] = matched_a
        entry["distance_a_m"]   = round(dist_a, 2)

        # ── if site_b given, the OTHER end must also match ────────────────
        if site_b is not None:
            lat_b, lon_b = site_b
            try:
                d_b0 = haversine_m(lat_b, lon_b, float(row["site_0_lat"]), float(row["site_0_lon"]))
            except (TypeError, ValueError):
                d_b0 = float("inf")
            try:
                d_b1 = haversine_m(lat_b, lon_b, float(row["site_1_lat"]), float(row["site_1_lon"]))
            except (TypeError, ValueError):
                d_b1 = float("inf")

            hit_b0 = d_b0 <= radius_m
            hit_b1 = d_b1 <= radius_m

            if not hit_b0 and not hit_b1:
                continue   # site_b doesn't match this row

            # make sure site_a and site_b matched DIFFERENT ends
            a_end = 0 if matched_a == "site_0" else 1
            if matched_a != "both":
                # site_b must hit the opposite end
                if a_end == 0 and not hit_b1:
                    continue
                if a_end == 1 and not hit_b0:
                    continue

            if hit_b0 and hit_b1:
                matched_b = "both"
                dist_b    = min(d_b0, d_b1)
            elif hit_b0:
                matched_b = "site_0"
                dist_b    = d_b0
            else:
                matched_b = "site_1"
                dist_b    = d_b1

            entry["matched_site_b"] = matched_b
            entry["distance_b_m"]   = round(dist_b, 2)

        results.append(entry)

    if not results:
        cols = list(links_df.columns) + ["matched_site_a", "distance_a_m"]
        if site_b is not None:
            cols += ["matched_site_b", "distance_b_m"]
        return pd.DataFrame(columns=cols)

    out = pd.DataFrame(results).sort_values("distance_a_m").reset_index(drop=True)
    return out

    