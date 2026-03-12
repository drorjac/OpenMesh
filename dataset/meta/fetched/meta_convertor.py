"""
mesh_to_links_converter.py
──────────────────────────
Converts mesh_metadata CSV → links_metadata format.

Grouping logic
--------------
Two rows belong to the same CML when BOTH endpoints match within
SAME_LOCATION_M metres (default 10 m) — direction-agnostic, so
A→B and B→A are merged into one CML.

Pipeline (configurable)
-----------------------
1. Coord validation -- auto-fix missing minus signs on longitudes;
                       drop rows still outside the bounding box.
2. Deduplication  – rows identical across coords + frequency + polarization
                    are collapsed; only the first is kept.
3. Length filter  – sublinks shorter than MIN_LENGTH_M are dropped.
                    Option: drop entire CML if ALL sublinks missing length.
4. Frequency filter – sublinks below MIN_FREQ_MHZ are dropped.
                    Option: drop entire CML if ALL sublinks missing frequency.
   Both filters have two modes (set in config or via CLI):
     drop_sublink  – remove only the offending sublink
     drop_cml      – remove the entire CML if ALL sublinks fail the field

Outputs
-------
1. links_metadata_output.csv  – links_metadata-compatible table
                                 (includes device_name column)
2. links_mapping.json         – full mapping: cml_id → all original
                                 API keys & fields per sublink
"""

import json
import math
import argparse
import pandas as pd
from pathlib import Path

# ── pipeline config (edit here or pass CLI args) ──────────────────────────────
INPUT_FILE      = "mesh_metadata_2026-01-07.csv"
OUTPUT_CSV      = "links_metadata_output.csv"
OUTPUT_JSON     = "links_mapping.json"
MIN_LENGTH_M    = 10.0    # drop sublinks shorter than this; 0 = keep all
MIN_FREQ_MHZ    = 0.0     # drop sublinks below this freq (MHz); 0 = keep all
SAME_LOCATION_M = 10.0    # metres threshold for "same endpoint"

# What to do when ALL sublinks in a CML are missing a field:
#   "keep"        – keep the CML anyway (NaN values stay)
#   "drop_cml"    – drop the entire CML
DROP_IF_ALL_LENGTH_MISSING  = "keep"      # options: "keep" | "drop_cml"
DROP_IF_ALL_FREQ_MISSING    = "keep"      # options: "keep" | "drop_cml"

# Bounding box — rows outside this after coord fix are dropped.
# Adjust if used outside NYC area.
LAT_MIN, LAT_MAX =  40.4,  41.0
LON_MIN, LON_MAX = -74.4, -73.5

# ── geo helpers ───────────────────────────────────────────────────────────────

def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def close(lat1, lon1, lat2, lon2, thr) -> bool:
    try:
        return haversine_m(float(lat1), float(lon1), float(lat2), float(lon2)) <= thr
    except (TypeError, ValueError):
        return False


def links_match(a0lat, a0lon, a1lat, a1lon,
                b0lat, b0lon, b1lat, b1lon, thr) -> bool:
    """Same physical link in either direction."""
    fwd = close(a0lat, a0lon, b0lat, b0lon, thr) and close(a1lat, a1lon, b1lat, b1lon, thr)
    rev = close(a0lat, a0lon, b1lat, b1lon, thr) and close(a1lat, a1lon, b0lat, b0lon, thr)
    return fwd or rev


# ── coordinate validation & fix ───────────────────────────────────────────────

def fix_coords(df: pd.DataFrame) -> pd.DataFrame:
    """
    1. Auto-fix longitude columns where the minus sign is missing
       (positive value that should be negative, e.g. 73.95 -> -73.95).
    2. Drop rows where either endpoint still falls outside the bounding
       box after the fix (truly bad data with no safe correction).
    Prints a summary of what was changed / dropped.
    """
    df = df.copy()
    lon_cols = ["site_0_lon", "site_1_lon"]

    # Step 1: flip obviously wrong positive longitudes
    fixed_count = 0
    for col in lon_cols:
        mask = df[col] > 0
        if mask.any():
            df.loc[mask, col] = -df.loc[mask, col]
            fixed_count += int(mask.sum())
    if fixed_count:
        print(f"  [coord fix] flipped sign on {fixed_count} longitude value(s)")

    # Step 2: drop rows still outside bounding box
    valid = (
        df["site_0_lat"].between(LAT_MIN, LAT_MAX) &
        df["site_0_lon"].between(LON_MIN, LON_MAX) &
        df["site_1_lat"].between(LAT_MIN, LAT_MAX) &
        df["site_1_lon"].between(LON_MIN, LON_MAX)
    )
    bad = int((~valid).sum())
    if bad:
        print(f"  [coord fix] dropped {bad} row(s) outside bbox "
              f"lat[{LAT_MIN},{LAT_MAX}] lon[{LON_MIN},{LON_MAX}]:")
        print(df[~valid][["cml_id", "tx_name", "rx_name",
                           "site_0_lat", "site_0_lon",
                           "site_1_lat", "site_1_lon"]].to_string())
    return df[valid].reset_index(drop=True)


# ── load ──────────────────────────────────────────────────────────────────────

def load_mesh(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    df = fix_coords(df)
    return df


# ── grouping ──────────────────────────────────────────────────────────────────

def build_groups(df: pd.DataFrame, thr: float) -> dict[int, list[int]]:
    """
    Returns {group_id: [df_row_indices]}.
    Fast path: exact sorted (tx_id, rx_id) match.
    Slow path: coordinate proximity scan for unmatched rows.
    """
    groups: list[list[int]] = []
    reps:   list[tuple]     = []   # (lat0, lon0, lat1, lon1) per group
    id_to_g: dict[tuple, int] = {}

    for idx, row in df.iterrows():
        id_key = tuple(sorted([str(row["tx_id"]), str(row["rx_id"])]))
        lat0, lon0 = row["site_0_lat"], row["site_0_lon"]
        lat1, lon1 = row["site_1_lat"], row["site_1_lon"]

        gid = id_to_g.get(id_key)

        if gid is None:
            for g, (rl0, ro0, rl1, ro1) in enumerate(reps):
                if links_match(lat0, lon0, lat1, lon1, rl0, ro0, rl1, ro1, thr):
                    gid = g
                    break

        if gid is None:
            gid = len(groups)
            groups.append([])
            reps.append((lat0, lon0, lat1, lon1))

        groups[gid].append(idx)
        id_to_g.setdefault(id_key, gid)

    return {i: v for i, v in enumerate(groups)}


# ── pipeline steps ────────────────────────────────────────────────────────────

DEDUP_COLS = ["site_0_lat", "site_0_lon", "site_1_lat", "site_1_lon",
              "frequency", "polarization"]


def dedup(sub: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in DEDUP_COLS if c in sub.columns]
    return sub.drop_duplicates(subset=cols, keep="first")


def length_filter(sub: pd.DataFrame, min_m: float, drop_cml_if_all_missing: bool):
    """
    Returns (filtered_df, drop_whole_cml).
    - Sublinks below min_m are always dropped.
    - If drop_cml_if_all_missing=True and every sublink has a missing/zero
      length, signals the caller to drop the entire CML.
    """
    if min_m <= 0:
        return sub, False

    lengths = pd.to_numeric(sub["length"], errors="coerce")
    all_missing = lengths.isna().all()

    if all_missing and drop_cml_if_all_missing:
        return sub.iloc[0:0], True   # empty → drop CML

    # Drop individual sublinks that are below threshold (treat NaN as 0)
    mask = lengths.fillna(0) >= min_m
    return sub[mask], False


def freq_filter(sub: pd.DataFrame, min_freq_mhz: float, drop_cml_if_all_missing: bool):
    """
    Returns (filtered_df, drop_whole_cml).
    - Sublinks below min_freq_mhz are always dropped.
    - If drop_cml_if_all_missing=True and every sublink has a missing
      frequency, signals the caller to drop the entire CML.
    """
    if min_freq_mhz <= 0:
        # Still check for all-missing if that option is on
        if drop_cml_if_all_missing:
            freqs = pd.to_numeric(sub["frequency"], errors="coerce")
            if freqs.isna().all():
                return sub.iloc[0:0], True
        return sub, False

    freqs = pd.to_numeric(sub["frequency"], errors="coerce")
    all_missing = freqs.isna().all()

    if all_missing and drop_cml_if_all_missing:
        return sub.iloc[0:0], True   # empty → drop CML

    # Drop individual sublinks below threshold (NaN treated as 0)
    mask = freqs.fillna(0) >= min_freq_mhz
    return sub[mask], False


# ── frequency normalisation ───────────────────────────────────────────────────

def norm_freq_mhz(val, units: str):
    """Normalise frequency to MHz."""
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


# ── device name ───────────────────────────────────────────────────────────────

def make_device_name(tx, rx) -> str:
    parts = [str(n).strip() for n in [tx, rx] if pd.notna(n) and str(n).strip()]
    return " ↔ ".join(parts) if parts else "unknown"


# ── conversion ────────────────────────────────────────────────────────────────

def convert(df, groups, min_m, min_freq_mhz,
            drop_cml_if_all_length_missing, drop_cml_if_all_freq_missing):
    links_rows, mapping = [], {}
    new_id = 0

    for _, idxs in groups.items():
        sub = df.loc[idxs]
        sub = dedup(sub)

        # Length filter
        sub, drop = length_filter(sub, min_m, drop_cml_if_all_length_missing)
        if drop or sub.empty:
            continue

        # Frequency filter
        sub, drop = freq_filter(sub, min_freq_mhz, drop_cml_if_all_freq_missing)
        if drop or sub.empty:
            continue

        new_id += 1
        rep      = sub.iloc[0]
        dev_name = make_device_name(rep.get("tx_name"), rep.get("rx_name"))

        sl_entries = []
        for sl_num, (_, sl) in enumerate(sub.iterrows(), start=1):
            sl_id = f"sublink_{sl_num}"
            freq  = norm_freq_mhz(sl.get("frequency"), sl.get("frequency_units", ""))
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



# ── coordinate-based lookup ──────────────────────────────────────────────────

def lookup_by_coords(
    links_df: pd.DataFrame,
    lat: float,
    lon: float,
    radius_m: float = 50.0,
    site: str = "any",          # "site_0" | "site_1" | "any"
) -> pd.DataFrame:
    """
    General lookup: given a lat/lon point, return all raw rows from
    links_df whose matching site endpoint falls within radius_m metres.

    Parameters
    ----------
    links_df : pd.DataFrame
        The converted links_metadata dataframe (or CSV loaded into one).
    lat, lon : float
        Query coordinates.
    radius_m : float
        Match radius in metres (default 50 m).
    site : str
        Which endpoint to search against:
          "site_0"  – only check site_0 coords
          "site_1"  – only check site_1 coords
          "any"     – match if EITHER site is within radius (default)

    Returns
    -------
    pd.DataFrame
        All matching rows, with an extra column `matched_site` ("site_0",
        "site_1", or "both") and `distance_m` (closest match distance).
        Empty DataFrame if nothing found.

    Examples
    --------
        df = pd.read_csv("links_metadata_output.csv")

        # All rows near a point, any site
        rows = lookup_by_coords(df, lat=40.696, lon=-73.940)

        # Only rows where site_0 is within 20 m
        rows = lookup_by_coords(df, lat=40.696, lon=-73.940, radius_m=20, site="site_0")

        # Get elevation of whatever is at these coords
        rows = lookup_by_coords(df, lat=40.696, lon=-73.940)
        print(rows[["cml_id", "device_name", "site_0_elevation", "site_0_altitude",
                     "site_1_elevation", "site_1_altitude", "matched_site", "distance_m"]])
    """
    results = []

    for _, row in links_df.iterrows():
        d0, d1 = None, None

        if site in ("site_0", "any"):
            try:
                d0 = haversine_m(lat, lon,
                                 float(row["site_0_lat"]), float(row["site_0_lon"]))
            except (TypeError, ValueError):
                d0 = None

        if site in ("site_1", "any"):
            try:
                d1 = haversine_m(lat, lon,
                                 float(row["site_1_lat"]), float(row["site_1_lon"]))
            except (TypeError, ValueError):
                d1 = None

        hit0 = d0 is not None and d0 <= radius_m
        hit1 = d1 is not None and d1 <= radius_m

        if not hit0 and not hit1:
            continue

        if hit0 and hit1:
            matched = "both"
            dist    = min(d0, d1)
        elif hit0:
            matched = "site_0"
            dist    = d0
        else:
            matched = "site_1"
            dist    = d1

        entry = row.to_dict()
        entry["matched_site"] = matched
        entry["distance_m"]   = round(dist, 2)
        results.append(entry)

    if not results:
        return pd.DataFrame(columns=list(links_df.columns) + ["matched_site", "distance_m"])

    out = pd.DataFrame(results)
    out = out.sort_values("distance_m").reset_index(drop=True)
    return out


# ── main ──────────────────────────────────────────────────────────────────────

def main(input_path=INPUT_FILE, output_csv=OUTPUT_CSV, output_json=OUTPUT_JSON,
         min_length_m=MIN_LENGTH_M, min_freq_mhz=MIN_FREQ_MHZ,
         same_loc_m=SAME_LOCATION_M,
         drop_if_all_length_missing=DROP_IF_ALL_LENGTH_MISSING,
         drop_if_all_freq_missing=DROP_IF_ALL_FREQ_MISSING):

    script_dir  = Path(__file__).resolve().parent
    input_path  = script_dir / input_path  if not Path(input_path).is_absolute()  else Path(input_path)
    output_csv  = script_dir / output_csv  if not Path(output_csv).is_absolute()  else Path(output_csv)
    output_json = script_dir / output_json if not Path(output_json).is_absolute() else Path(output_json)

    drop_len_cml  = drop_if_all_length_missing == "drop_cml"
    drop_freq_cml = drop_if_all_freq_missing   == "drop_cml"

    print(f"Loading      : {input_path}")
    df = load_mesh(input_path)
    print(f"  Source rows: {len(df)}")

    print(f"Grouping     (same-location threshold = {same_loc_m} m) …")
    groups = build_groups(df, thr=same_loc_m)
    print(f"  Raw groups : {len(groups)}")

    print(f"Converting   (dedup + length >= {min_length_m} m [{drop_if_all_length_missing}]"
          f" + freq >= {min_freq_mhz} MHz [{drop_if_all_freq_missing}]) …")
    links_df, mapping = convert(
        df, groups,
        min_m=min_length_m,
        min_freq_mhz=min_freq_mhz,
        drop_cml_if_all_length_missing=drop_len_cml,
        drop_cml_if_all_freq_missing=drop_freq_cml,
    )

    n_cmls = links_df["cml_id"].nunique() if not links_df.empty else 0
    print(f"  CMLs       : {n_cmls}")
    print(f"  Sublinks   : {len(links_df)}")

    # Sort CMLs so highest frequency comes first, re-number cml_ids
    if not links_df.empty:
        max_freq = links_df.groupby("cml_id")["frequency"].max().reset_index()
        max_freq.columns = ["cml_id", "_max_freq"]
        max_freq = max_freq.sort_values("_max_freq", ascending=False, na_position="last")
        old_to_new = {old: new for new, old in enumerate(max_freq["cml_id"], start=1)}
        links_df["cml_id"] = links_df["cml_id"].map(old_to_new)
        links_df = links_df.sort_values(["cml_id", "sublink_id"]).reset_index(drop=True)
        mapping = {old_to_new[k]: v for k, v in mapping.items()}
        for v in mapping.values():
            v["cml_id"] = old_to_new.get(v["cml_id"], v["cml_id"])

    links_df.to_csv(output_csv, index=False)
    print(f"Saved CSV    : {output_csv}")

    with open(output_json, "w") as f:
        json.dump(mapping, f, indent=2, default=str)
    print(f"Saved JSON   : {output_json}")

    return links_df, mapping



# ── run() for direct execution — edit config constants at the top ─────────────

def run():
    """Call this directly when running the file without CLI args."""
    main(
        input_path                 = INPUT_FILE,
        output_csv                 = OUTPUT_CSV,
        output_json                = OUTPUT_JSON,
        min_length_m               = MIN_LENGTH_M,
        min_freq_mhz               = MIN_FREQ_MHZ,
        same_loc_m                 = SAME_LOCATION_M,
        drop_if_all_length_missing = DROP_IF_ALL_LENGTH_MISSING,
        drop_if_all_freq_missing   = DROP_IF_ALL_FREQ_MISSING,
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        # ── CLI mode ──────────────────────────────────────────────────────────
        parser = argparse.ArgumentParser(
            description="Convert mesh_metadata CSV → links_metadata format"
        )
        parser.add_argument("input",       nargs="?", default=INPUT_FILE)
        parser.add_argument("output_csv",  nargs="?", default=OUTPUT_CSV)
        parser.add_argument("output_json", nargs="?", default=OUTPUT_JSON)
        parser.add_argument(
            "--min-length", type=float, default=MIN_LENGTH_M,
            help=f"Drop sublinks shorter than N metres (default {MIN_LENGTH_M}). "
                 "Pass 0 to keep all."
        )
        parser.add_argument(
            "--min-freq", type=float, default=MIN_FREQ_MHZ,
            help=f"Drop sublinks below this frequency in MHz (default {MIN_FREQ_MHZ}). "
                 "Pass 0 to keep all."
        )
        parser.add_argument(
            "--same-loc", type=float, default=SAME_LOCATION_M,
            help=f"Metres threshold for two endpoints to be considered the same "
                 f"location (default {SAME_LOCATION_M})."
        )
        parser.add_argument(
            "--drop-if-all-length-missing", choices=["keep", "drop_cml"],
            default=DROP_IF_ALL_LENGTH_MISSING,
            help="What to do when ALL sublinks in a CML have missing length. "
                 "'keep' = keep CML with NaN lengths. "
                 "'drop_cml' = remove the entire CML. "
                 f"(default: {DROP_IF_ALL_LENGTH_MISSING})"
        )
        parser.add_argument(
            "--drop-if-all-freq-missing", choices=["keep", "drop_cml"],
            default=DROP_IF_ALL_FREQ_MISSING,
            help="What to do when ALL sublinks in a CML have missing frequency. "
                 "'keep' = keep CML with NaN frequencies. "
                 "'drop_cml' = remove the entire CML. "
                 f"(default: {DROP_IF_ALL_FREQ_MISSING})"
        )
        parser.add_argument(
            "--lat-range", nargs=2, type=float, metavar=("MIN", "MAX"),
            default=[LAT_MIN, LAT_MAX],
            help=f"Valid latitude range (default {LAT_MIN} {LAT_MAX})"
        )
        parser.add_argument(
            "--lon-range", nargs=2, type=float, metavar=("MIN", "MAX"),
            default=[LON_MIN, LON_MAX],
            help=f"Valid longitude range (default {LON_MIN} {LON_MAX})"
        )
        a = parser.parse_args()
        LAT_MIN, LAT_MAX = a.lat_range
        LON_MIN, LON_MAX = a.lon_range
        main(
            input_path=a.input,
            output_csv=a.output_csv,
            output_json=a.output_json,
            min_length_m=a.min_length,
            min_freq_mhz=a.min_freq,
            same_loc_m=a.same_loc,
            drop_if_all_length_missing=a.drop_if_all_length_missing,
            drop_if_all_freq_missing=a.drop_if_all_freq_missing,
        )
    else:
        # ── direct run: edit the config constants at the top of the file ──────
        run()