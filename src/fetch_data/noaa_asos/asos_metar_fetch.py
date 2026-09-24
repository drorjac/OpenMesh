"""
ASOS METAR Archive Functions
============================

Fetch the transmitted METAR/SPECI archive (observer/algorithm-augmented airport
reports) from IEM, as opposed to the raw 1-minute sensor stream handled by
`asos_fetch.py`.

Source: https://mesonet.agron.iastate.edu/request/download.phtml (asos.py backend)

Key differences vs. the 1-minute feed (`asos_fetch.fetch_all_stations_1min`):
- Carries `wxcodes` (present-weather groups, e.g. -RA, SN, FZRA, PL, UP) and the
  raw METAR string itself, which the 1-min feed does not.
- One report per routine (~hourly, top-of-hour) or special (irregular,
  triggered by a significant change) observation, not one row per minute.
- `p01i` (1-hour precip) resets at each top-of-hour report; between-hour
  SPECI reports show the running total since that reset, so it is NOT safe
  to sum `p01i` across reports within an hour.

Note: `report_type=3` selects routine reports, `report_type=4` selects
specials; passing both returns the full archive (routine + special).
"""

import time
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

ASOS_METAR_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

DEFAULT_DATA_FIELDS = ["metar", "wxcodes", "tmpf", "dwpf", "relh", "p01i"]


# =============================================================================
# FETCH METAR ARCHIVE
# =============================================================================

def fetch_metar_chunk(station_ids, start_date, end_date, data_fields=None,
                       report_types=(3, 4), max_retries=3, timeout=300, verbose=True):
    """
    Fetch the METAR archive for one or more stations over a single time chunk.

    Parameters
    ----------
    station_ids : str or list of str
        Station id(s), e.g. 'LGA' or ['LGA', 'JFK'].
    start_date, end_date : datetime
        Inclusive UTC date range.
    data_fields : list of str, optional
        IEM `data=` fields to request. Default: DEFAULT_DATA_FIELDS.
    report_types : tuple of int
        3 = routine (~hourly), 4 = special. Both by default.
    max_retries : int
        Retry attempts on request failure/empty response.
    timeout : int
        Per-request timeout in seconds.

    Returns
    -------
    pd.DataFrame or None
        Raw response as a DataFrame (columns: station, valid, + data_fields),
        or None if the request failed after retries.
    """
    if isinstance(station_ids, str):
        station_ids = [station_ids]
    if data_fields is None:
        data_fields = DEFAULT_DATA_FIELDS

    params = []
    for sid in station_ids:
        params.append(("station", sid))
    for field in data_fields:
        params.append(("data", field))
    params += [
        ("year1", start_date.year), ("month1", start_date.month), ("day1", start_date.day),
        ("year2", end_date.year), ("month2", end_date.month), ("day2", end_date.day),
        ("tz", "UTC"),
        ("format", "onlycomma"),
        ("latlon", "no"),
        ("elev", "no"),
        ("missing", "M"),
        ("trace", "T"),
        ("direct", "no"),
    ]
    for rt in report_types:
        params.append(("report_type", rt))

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(ASOS_METAR_URL, params=params, timeout=timeout)
            if resp.status_code == 200 and len(resp.text) > 0:
                df = pd.read_csv(StringIO(resp.text))
                return df
            last_err = f"HTTP {resp.status_code}, {len(resp.text)} bytes"
        except Exception as e:
            last_err = str(e)
        if attempt < max_retries:
            time.sleep(2 * attempt)

    if verbose:
        print(f"  ✗ Error after {max_retries} attempts: {last_err}")
    return None


def fetch_metar_station(station_id, start_date, end_date, data_fields=None,
                         report_types=(3, 4), verbose=True):
    """
    Fetch METAR archive for a single station, chunked by year, then merge.

    Chunking by year keeps individual requests small (hourly-resolution data
    is far lighter than the 1-min feed) while still allowing partial
    progress/retry if one year's request fails.
    """
    if verbose:
        print(f"\n{station_id}:")

    chunks = []
    year_start = start_date
    while year_start <= end_date:
        year_end = min(pd.Timestamp(year=year_start.year, month=12, day=31), pd.Timestamp(end_date))
        year_end = year_end.to_pydatetime() if hasattr(year_end, "to_pydatetime") else year_end

        if verbose:
            print(f"  {year_start.year}... ", end="", flush=True)

        df = fetch_metar_chunk(station_id, year_start, year_end, data_fields=data_fields,
                                report_types=report_types, verbose=False)

        if df is not None and len(df) > 0:
            chunks.append(df)
            if verbose:
                print(f"✓ {len(df):,} rows")
        else:
            if verbose:
                print("✗ no data")

        year_start = pd.Timestamp(year=year_start.year + 1, month=1, day=1).to_pydatetime()

    if len(chunks) == 0:
        if verbose:
            print(f"  ✗ No data retrieved for {station_id}")
        return None

    df_combined = pd.concat(chunks, ignore_index=True)
    df_combined["valid"] = pd.to_datetime(df_combined["valid"])
    df_combined = df_combined.drop_duplicates(subset=["station", "valid"]).sort_values("valid")
    df_combined = df_combined.reset_index(drop=True)

    if verbose:
        print(f"  ✓ Total: {len(df_combined):,} rows")

    return df_combined


def fetch_all_metar_stations(station_ids, start_date, end_date, data_fields=None,
                              report_types=(3, 4), verbose=True):
    """Fetch the METAR archive for all stations. Returns {station_id: DataFrame}."""
    if verbose:
        print("=" * 60)
        print("FETCHING METAR ARCHIVE (routine + special)")
        print(f"Period: {start_date.date()} to {end_date.date()}")
        print("=" * 60)

    raw_data = {}
    for station_id in station_ids:
        df = fetch_metar_station(station_id, start_date, end_date, data_fields=data_fields,
                                  report_types=report_types, verbose=verbose)
        if df is not None:
            raw_data[station_id] = df

    if verbose:
        print(f"\n✓ Fetched {len(raw_data)}/{len(station_ids)} stations")

    return raw_data


# =============================================================================
# METAR STRING PARSING (AUTO / AO1 / AO2 / GHCNH backfill flag)
# =============================================================================

def parse_metar_flags(metar):
    """
    Extract station-augmentation flags from a raw METAR/SPECI string.

    Returns
    -------
    dict with keys:
        auto     : bool — 'AUTO' appears in the report body (fully automated
                   observation, no human augmentation at transmission time)
        ao1      : bool — 'AO1' in remarks (automated station, no precip
                   discriminator)
        ao2      : bool — 'AO2' in remarks (automated station, WITH precip
                   discriminator — can detect liquid vs. frozen precip)
        ghcnh_filled : bool — report was back-filled by IEM from GHCN-Hourly
                   rather than a genuine transmitted METAR (tagged
                   'IEM_GHCNH' in the remarks by IEM's archive)
    """
    if pd.isna(metar):
        return {"auto": False, "ao1": False, "ao2": False, "ghcnh_filled": False}
    s = str(metar)
    tokens = s.split()
    return {
        "auto": "AUTO" in tokens,
        "ao1": "AO1" in tokens,
        "ao2": "AO2" in tokens,
        "ghcnh_filled": "IEM_GHCNH" in s,
    }


def add_metar_flags(df, metar_col="metar"):
    """Add auto/ao1/ao2/ghcnh_filled boolean columns derived from the raw METAR string."""
    flags = df[metar_col].apply(parse_metar_flags).apply(pd.Series)
    return pd.concat([df, flags], axis=1)


# =============================================================================
# WXCODES → PHASE CLASSIFICATION
# =============================================================================

# Precedence when a single report (or an hour-level rollup) matches more than
# one class: freezing precip is the most operationally distinct signal (icing
# risk) so it wins outright; a true rain+snow mix is reported next; ice
# pellets and "unknown precip" (UP, algorithm couldn't classify) are distinct
# NWS-defined codes kept separate per spec rather than folded into mixed.
PHASE_PRECEDENCE = ["freezing", "mixed", "ice_pellets", "unknown", "rain", "snow", "dry"]

# Descriptor prefixes that can precede a phenomenon code (order matters: FZ
# must be checked before stripping other descriptors so freezing is caught).
_INTENSITY = ("-", "+")
_VICINITY = "VC"
_DESCRIPTORS = ("FZ", "SH", "TS", "BL", "DR", "MI", "BC", "PR")

# 2-letter present-weather phenomenon codes -> family. METAR concatenates
# multiple phenomena into a single token with no separator (e.g. 'RASN' =
# rain AND snow, 'FZRAPL' = freezing rain AND ice pellets), so a token must be
# decomposed into its 2-char chunks rather than matched as one substring —
# naive substring checks (e.g. "'SN' in token") silently swallow a trailing
# 'RA' in 'RASN' and undercount 'mixed'.
_PHENOMENON_FAMILY = {
    "RA": "rain", "DZ": "rain",
    "SN": "snow", "SG": "snow", "GR": "snow", "GS": "snow",
    "PL": "ice_pellets",
    "UP": "unknown",
}


def _classify_token(token):
    """Classify a single space-separated wxcodes token. Returns a set of families found."""
    t = token.strip()
    if not t or t in ("M", "nan", "None"):
        return set()
    for c in _INTENSITY:
        t = t.lstrip(c)
    if t.startswith(_VICINITY):
        t = t[len(_VICINITY):]

    is_freezing = False
    remainder = t
    changed = True
    while changed:
        changed = False
        for d in _DESCRIPTORS:
            if remainder.startswith(d):
                if d == "FZ":
                    is_freezing = True
                remainder = remainder[len(d):]
                changed = True

    if len(remainder) % 2 != 0:
        # Malformed / unrecognized token (e.g. obstruction-to-vision code
        # like 'BR', 'FG', 'HZ' that slipped through as its own token) —
        # no precip phenomenon to extract.
        return set()

    found = set()
    for i in range(0, len(remainder), 2):
        chunk = remainder[i:i + 2]
        family = _PHENOMENON_FAMILY.get(chunk)
        if family is None:
            continue
        if is_freezing and family == "rain":
            found.add("freezing")
        else:
            found.add(family)
    return found


def classify_wxcodes(wxcodes):
    """
    Classify one report's `wxcodes` field into a single phase class.

    Classes (see PHASE_PRECEDENCE for tie-break order when a report contains
    tokens from more than one family):
        rain, snow, mixed (rain AND snow both present, neither freezing),
        freezing (FZRA / FZDZ), ice_pellets (PL), unknown (UP), dry (no
        recognized precip token, including fog/haze/thunder-only reports).

    Parameters
    ----------
    wxcodes : str
        Raw wxcodes field, e.g. '-RA', 'SN BR', 'FZRA', 'M' (IEM's missing
        sentinel — no present-weather group in the report).

    Returns
    -------
    str
        One of: 'rain', 'snow', 'mixed', 'freezing', 'ice_pellets', 'unknown', 'dry'
    """
    if pd.isna(wxcodes) or str(wxcodes).strip() in ("M", "", "nan", "None"):
        return "dry"

    found = set()
    for token in str(wxcodes).split():
        found |= _classify_token(token)

    if not found:
        return "dry"
    if "freezing" in found:
        return "freezing"
    if "rain" in found and "snow" in found:
        return "mixed"
    if "ice_pellets" in found:
        return "ice_pellets"
    if "unknown" in found:
        return "unknown"
    if "rain" in found:
        return "rain"
    if "snow" in found:
        return "snow"
    return "dry"


def add_phase_class(df, wxcodes_col="wxcodes"):
    """Add a `phase_class` column derived from `wxcodes` via classify_wxcodes()."""
    df = df.copy()
    df["phase_class"] = df[wxcodes_col].apply(classify_wxcodes)
    return df


# =============================================================================
# FILE I/O
# =============================================================================

def save_metar_raw(raw_data_dict, output_dir, start_date=None, end_date=None, verbose=True):
    """
    Save raw METAR archive data (one combined CSV, raw METAR string preserved)
    to `output_dir`. Individual per-station CSVs are also written.

    Parameters
    ----------
    raw_data_dict : dict
        {station_id: DataFrame} as returned by fetch_all_metar_stations().
    output_dir : str or Path
    start_date, end_date : datetime, optional
        Used only to build the filename date-range suffix.

    Returns
    -------
    dict {'individual': [paths], 'combined': path}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    date_suffix = ""
    if start_date and end_date:
        date_suffix = f"_{pd.to_datetime(start_date).date()}_{pd.to_datetime(end_date).date()}"

    saved = {"individual": [], "combined": None}

    for station_id, df in raw_data_dict.items():
        fname = f"{station_id}_metar{date_suffix}.csv"
        fpath = output_dir / fname
        df.to_csv(fpath, index=False)
        saved["individual"].append(fpath)
        if verbose:
            print(f"  ✓ {fname} ({len(df):,} rows)")

    combined = pd.concat(raw_data_dict.values(), ignore_index=True)
    combined = combined.sort_values(["station", "valid"]).reset_index(drop=True)
    fname = f"ASOS_metar{date_suffix}.csv"
    fpath = output_dir / fname
    combined.to_csv(fpath, index=False)
    saved["combined"] = fpath
    if verbose:
        print(f"  ✓ {fname} ({len(combined):,} rows)")

    return saved
