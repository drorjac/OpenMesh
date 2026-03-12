"""Helper utilities for loading experiment data."""

import pickle
import numpy as np
import pandas as pd
from pathlib import Path

EXPERIMENTS_DIR = Path(__file__).resolve().parents[2] / "dataset" / "raw" / "experiments"


def load_pkl(filename, experiments_dir=None, save_csv=True):
    """
    Load a pickle file from the experiments directory, return as DataFrame,
    and optionally save a CSV copy alongside it.

    Parameters
    ----------
    filename : str
        Pickle filename (e.g. 'data_6GHz.pkl') or full path.
    experiments_dir : str or Path, optional
        Override the default experiments directory.
    save_csv : bool
        If True (default), write a .csv next to the .pkl file.

    Returns
    -------
    pd.DataFrame
    """
    exp_dir = Path(experiments_dir) if experiments_dir else EXPERIMENTS_DIR
    path = Path(filename) if Path(filename).is_absolute() else exp_dir / filename

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, "rb") as f:
        data = pickle.load(f)

    if isinstance(data, dict):
        max_len = max(len(v) for v in data.values())
        aligned = {}
        for k, v in data.items():
            if len(v) < max_len:
                v = list(v) + [None] * (max_len - len(v))
            aligned[k] = v
        df = pd.DataFrame(aligned)
    elif isinstance(data, pd.DataFrame):
        df = data
    else:
        raise TypeError(f"Unsupported pickle content type: {type(data).__name__}")

    if save_csv:
        csv_path = path.with_suffix(".csv")
        df.to_csv(csv_path, index=False)
        print(f"  Saved CSV: {csv_path.name} ({len(df)} rows)")

    print(f"  Loaded: {path.name} → {df.shape[0]} rows, {df.shape[1]} cols")
    return df


def _normalize_time(t):
    """Convert H-MM (e.g. '9-20') or HH:MM:SS to uniform HH:MM:SS."""
    t = str(t).strip()
    if "-" in t:
        parts = t.split("-")
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}:00"
    return t


def load_experiments(date, experiments_dir=None, save_csv=True):
    """
    Load experiment pkl files and return a dict of uniform DataFrames.

    Each DataFrame has columns: [date, time, rx_power, datetime]
    The 60 GHz file is split into two (rx1, rx2).

    Parameters
    ----------
    date : str
        Experiment date, e.g. '2026-01-19'.
    experiments_dir : str or Path, optional
        Override the default experiments directory.
    save_csv : bool
        If True (default), also save each DataFrame as CSV.

    Returns
    -------
    dict  {'6ghz': DataFrame, '60ghz_rx1': DataFrame, '60ghz_rx2': DataFrame}
    """
    exp_dir = Path(experiments_dir) if experiments_dir else EXPERIMENTS_DIR

    # ── 6 GHz ──────────────────────────────────────────────
    raw_6 = load_pkl("data_6GHz.pkl", experiments_dir=exp_dir, save_csv=False)
    df_6ghz = pd.DataFrame({
        "rx_power": raw_6["rx_power"],
        "time":     raw_6["time"].apply(_normalize_time),
    })

    # ── 60 GHz → split into rx1 / rx2 ─────────────────────
    raw_60 = load_pkl("data_60GHz.pkl", experiments_dir=exp_dir, save_csv=False)
    df_60ghz_rx1 = pd.DataFrame({
        "rx_power": raw_60["rx_power1"],
        "time":     raw_60["time1"].apply(_normalize_time),
    })
    df_60ghz_rx2 = pd.DataFrame({
        "rx_power": raw_60["rx_power2"],
        "time":     raw_60["time2"].apply(_normalize_time),
    })

    # ── add date + datetime ────────────────────────────────
    for df in [df_6ghz, df_60ghz_rx1, df_60ghz_rx2]:
        df.insert(0, "date", date)
        df["datetime"] = pd.to_datetime(date + " " + df["time"])
        df.sort_values("datetime", inplace=True)
        df.reset_index(drop=True, inplace=True)

    data = {
        "6ghz":      df_6ghz,
        "60ghz_rx1": df_60ghz_rx1,
        "60ghz_rx2": df_60ghz_rx2,
    }

    if save_csv:
        for name, df in data.items():
            csv_path = exp_dir / f"{name}.csv"
            df.to_csv(csv_path, index=False)

    for name, df in data.items():
        print(f"  {name:12s} → {df.shape[0]:>4d} rows  |  "
              f"{df['datetime'].min().strftime('%H:%M:%S')} → "
              f"{df['datetime'].max().strftime('%H:%M:%S')}")

    return data


def find_nearest_stations(lat, lon, meta, max_distance_km=None, max_stations=None):
    """
    Find the nearest weather stations to a given location.

    Parameters
    ----------
    lat, lon : float
        Reference point coordinates (e.g. experiment site).
    meta : pd.DataFrame
        Station metadata. Accepts column names 'Latitude'/'Longitude'
        or 'lat'/'lon', and 'Station ID' or 'station_id'.
    max_distance_km : float, optional
        Keep only stations within this radius.
    max_stations : int, optional
        Return at most this many stations (closest first).

    Returns
    -------
    pd.DataFrame
        Copy of *meta* with an added ``distance_km`` column, sorted
        by distance (closest first), filtered by the given constraints.
    """
    meta = meta.copy()

    lat_col = "Latitude" if "Latitude" in meta.columns else "lat"
    lon_col = "Longitude" if "Longitude" in meta.columns else "lon"
    id_col = "Station ID" if "Station ID" in meta.columns else "station_id"

    R = 6371.0
    lat1, lon1 = np.radians(lat), np.radians(lon)
    lat2 = np.radians(meta[lat_col].astype(float).values)
    lon2 = np.radians(meta[lon_col].astype(float).values)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    meta["distance_km"] = 2 * R * np.arcsin(np.sqrt(a))

    meta.sort_values("distance_km", inplace=True)
    meta.reset_index(drop=True, inplace=True)

    if max_distance_km is not None:
        meta = meta[meta["distance_km"] <= max_distance_km]

    if max_stations is not None:
        meta = meta.head(max_stations)

    print(f"  Found {len(meta)} stations", end="")
    if max_distance_km is not None:
        print(f" within {max_distance_km} km", end="")
    print(f" of ({lat:.4f}, {lon:.4f})")

    if len(meta) > 0:
        preview = meta[[id_col, lat_col, lon_col, "distance_km"]].head(5)
        print(preview.to_string(index=False))

    return meta


def prepare_experiment_data(
    experiments,
    analysis_data,
    pws_station_ids=None,
    asos_station_ids=None,
    params=None,
):
    """
    Align experiment rx_power signals with weather data from analysis_data
    on the experiment time window.

    Parameters
    ----------
    experiments : dict
        Output of ``load_experiments`` – keys '6ghz', '60ghz_rx1', '60ghz_rx2'.
        Each value is a DataFrame with columns [date, time, rx_power, datetime].
    analysis_data : dict
        Output of ``prepare_analysis_data`` with structure::
            {'asos': {param: DataFrame}, 'pws': {param: DataFrame}, …}
        Each DataFrame has datetime index and station-ID columns.
    pws_station_ids : list, optional
        PWS station IDs to keep (e.g. from ``find_nearest_stations``).
        None = use all available.
    asos_station_ids : list, optional
        ASOS station IDs to keep.  None = use all available.
    params : list, optional
        Parameter names to include (must match keys in analysis_data['pws'] / ['asos']).
        None = use all available parameters.

    Returns
    -------
    dict::

        {
            'experiment': {'6ghz': Series, '60ghz_rx1': Series, …},
            'pws':  {param: DataFrame},   # station columns, datetime index
            'asos': {param: DataFrame},   # station columns, datetime index
            'info': { … },
        }
    """
    # ── experiment time range ──────────────────────────────
    all_dt = pd.concat([df["datetime"] for df in experiments.values()])
    t_start, t_end = all_dt.min(), all_dt.max()

    result = {
        "experiment": {},
        "pws": {},
        "asos": {},
        "info": {
            "time_range": (t_start, t_end),
            "pws_stations": pws_station_ids,
            "asos_stations": asos_station_ids,
        },
    }

    # ── experiment series (rx_power indexed by datetime) ───
    for name, df in experiments.items():
        s = df.set_index("datetime")["rx_power"].sort_index()
        result["experiment"][name] = s
    print(f"Experiment signals: {list(result['experiment'].keys())}  "
          f"({t_start.strftime('%H:%M')}–{t_end.strftime('%H:%M')})")

    # ── diagnostics ────────────────────────────────────────
    pws_data = analysis_data.get("pws", {})
    asos_data = analysis_data.get("asos", {})
    print(f"analysis_data has: pws={list(pws_data.keys())}, asos={list(asos_data.keys())}")

    # ── helper: clip a param DataFrame to experiment window + filter stations
    def _clip(param_df, station_ids):
        df = param_df.copy()
        # strip timezone from index if present (match naive experiment datetimes)
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df.index = df.index.tz_convert('UTC').tz_localize(None)
        df = df.loc[(df.index >= t_start) & (df.index <= t_end)]
        if station_ids is not None:
            cols = [c for c in df.columns if c in station_ids]
            df = df[cols]
        if df.empty or df.columns.empty:
            return pd.DataFrame()
        return df

    # ── PWS (from analysis_data['pws']) ────────────────────
    avail_pws_params = list(pws_data.keys()) if params is None else params
    for param in avail_pws_params:
        if param in pws_data:
            clipped = _clip(pws_data[param], pws_station_ids)
            if not clipped.empty:
                result["pws"][param] = clipped
    if result["pws"]:
        total_cols = sum(len(v.columns) for v in result["pws"].values())
        print(f"PWS:  {len(result['pws'])} params, {total_cols} station-columns  "
              f"| params: {list(result['pws'].keys())}")
    else:
        print("PWS:  empty (no data in experiment time window)")

    # ── ASOS (from analysis_data['asos']) ──────────────────
    avail_asos_params = list(asos_data.keys()) if params is None else params
    for param in avail_asos_params:
        if param in asos_data:
            clipped = _clip(asos_data[param], asos_station_ids)
            if not clipped.empty:
                result["asos"][param] = clipped
    if result["asos"]:
        total_cols = sum(len(v.columns) for v in result["asos"].values())
        print(f"ASOS: {len(result['asos'])} params, {total_cols} station-columns  "
              f"| params: {list(result['asos'].keys())}")
    else:
        print("ASOS: empty (no data in experiment time window)")

    result["info"]["pws_params"] = list(result["pws"].keys())
    result["info"]["asos_params"] = list(result["asos"].keys())
    return result
