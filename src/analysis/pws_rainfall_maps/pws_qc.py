"""
pws_qc.py
=========
Quality control for PWS rainfall data using the pypwsqc OpenSense package.

Applies three filters from the PWSQC framework:
  - FZ (Faulty Zero) : station reports zero while neighbours report rain
  - HI (High Influx) : unrealistically large rainfall values
  - SO (Station Outlier) : station is uncorrelated with nearby stations

All three filters operate on an xr.Dataset with the structure required by
pypwsqc (variables: rainfall, reference, nbrs_not_nan, so_flag,
median_corr_nbrs). This module builds that structure from a stacked
(id, time) Dataset and returns a QC-applied copy.

Usage
-----
    from pws_qc import run_pws_qc

    ds_pws_qc = run_pws_qc(ds_pws_stacked, rain_var="rainfall_amount")
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr
import pypwsqc
from pyproj import Geod


# Default QC parameters (can be overridden via run_pws_qc kwargs)

DEFAULT_MAX_DIST_KM   = 10.0   # neighbour search radius
DEFAULT_NINT          = 10     # consecutive intervals for FZ filter
DEFAULT_HI_THRES_A    = 10.0   # reference median threshold (mm) for HI filter
DEFAULT_HI_THRES_B    = 100.0  # upper absolute limit (mm) for HI filter
DEFAULT_N_STAT        = 1      # minimum neighbours required for evaluation
DEFAULT_EVAL_PERIOD   = 24     # rolling window length (timesteps) for SO filter
DEFAULT_MMATCH        = 0.5    # fraction of matching rainy intervals for SO
DEFAULT_GAMMA         = 0.5    # Pearson correlation threshold for SO filter


# Internal helpers

def _build_distance_matrix(
    lons: np.ndarray,
    lats: np.ndarray,
    station_ids: np.ndarray,
) -> tuple[np.ndarray, xr.DataArray]:
    """
    Compute pairwise geodesic distances between stations.

    Returns
    -------
    dist_np : np.ndarray, shape (n, n)
        Distance matrix in kilometres.
    dist_da : xr.DataArray, dims (id, id_neighbor)
        Same matrix as xr.DataArray with id coordinates - required by
        pypwsqc.flagging.so_filter which calls .sel(id=...) on it.
    """
    geod  = Geod(ellps="WGS84")
    n     = len(station_ids)
    dist_np = np.zeros((n, n))

    for i in range(n):
        for j in range(n):
            _, _, d = geod.inv(lons[i], lats[i], lons[j], lats[j])
            dist_np[i, j] = d / 1000.0  # m → km

    dist_da = xr.DataArray(
        dist_np,
        dims=["id", "id_neighbor"],
        coords={"id": station_ids, "id_neighbor": station_ids},
    )
    return dist_np, dist_da


def _build_qc_dataset(
    rain_arr: np.ndarray,
    dist_np: np.ndarray,
    ds_pws_stacked: xr.Dataset,
    max_dist_km: float,
) -> tuple[xr.Dataset, np.ndarray]:
    """
    Build the xr.Dataset structure expected by all three pypwsqc filters.

    Required variables:
        rainfall - observed rainfall (id, time)
        reference - median of neighbouring stations (id, time)
        nbrs_not_nan - count of non-NaN neighbours per timestep (id, time)
        so_flag - pre-initialised to -1 (id, time)
        median_corr_nbrs - pre-initialised to NaN (id, time)

    Returns
    -------
    ds_for_qc : xr.Dataset
    nbrs_arr  : np.ndarray - neighbour count per station (used as n_stat)
    """
    n, time_len = rain_arr.shape
    ref_arr = np.full_like(rain_arr, np.nan)
    nbrs_not_nan = np.zeros_like(rain_arr)
    nbrs_arr = np.zeros(n, dtype=float)

    for i in range(n):
        mask = (dist_np[i] < max_dist_km) & (dist_np[i] > 0)
        nbrs_arr[i] = mask.sum()
        if mask.sum() > 0:
            ref_arr[i] = np.nanmedian(rain_arr[mask], axis=0)
            nbrs_not_nan[i] = (~np.isnan(rain_arr[mask])).sum(axis=0)

    ds_for_qc = xr.Dataset(
        {
            "rainfall" : (["id", "time"], rain_arr),
            "reference" : (["id", "time"], ref_arr),
            "nbrs_not_nan" : (["id", "time"], nbrs_not_nan),
            "so_flag" : (["id", "time"], np.full((n, time_len), -1, dtype=int)),
            "median_corr_nbrs": (["id", "time"], np.full((n, time_len), np.nan)),
        },
        coords=ds_pws_stacked.coords,
    )
    return ds_for_qc, nbrs_arr


# Public API

def run_pws_qc(
    ds_pws_stacked: xr.Dataset,
    rain_var: str = "rainfall_amount",
    max_dist_km: float = DEFAULT_MAX_DIST_KM,
    nint: int = DEFAULT_NINT,
    hi_thres_a: float = DEFAULT_HI_THRES_A,
    hi_thres_b: float = DEFAULT_HI_THRES_B,
    n_stat: int = DEFAULT_N_STAT,
    eval_period: int = DEFAULT_EVAL_PERIOD,
    mmatch: float = DEFAULT_MMATCH,
    gamma: float = DEFAULT_GAMMA,
) -> xr.Dataset:
    """
    Apply pypwsqc FZ, HI, and SO filters to a stacked PWS dataset.

    Parameters
    ----------
    ds_pws_stacked : xr.Dataset
        Output of pws_loader.stack_pws_to_dataset(). Must have dims (id, time)
        and coordinate variables lon, lat.
    rain_var : str
        Name of the rainfall variable (default "rainfall_amount").
    max_dist_km : float
        Neighbour search radius in km (default 10).
    nint : int
        Number of consecutive dry intervals required for FZ flag (default 10).
    hi_thres_a : float
        Reference median threshold (mm) for HI filter (default 10).
    hi_thres_b : float
        Absolute upper limit (mm) for HI filter (default 100).
    n_stat : int
        Minimum neighbours required for evaluation (default 1).
    eval_period : int
        Rolling window length (timesteps) for SO filter (default 24).
    mmatch : float
        Fraction of matching rainy intervals for SO filter (default 0.5).
    gamma : float
        Pearson correlation threshold for SO filter (default 0.5).

    Returns
    -------
    ds_pws_qc : xr.Dataset
        Copy of ds_pws_stacked with flagged values replaced by NaN.
        Includes attributes recording which QC flags were applied.

    Notes
    -----
    Falls back to a simple >100 mm threshold if pypwsqc raises an exception.
    """
    station_ids = ds_pws_stacked.id.values
    lons_arr = ds_pws_stacked.lon.values
    lats_arr = ds_pws_stacked.lat.values
    rain_arr = ds_pws_stacked[rain_var].values  # (n_stations, n_times)

    dist_np, dist_da = _build_distance_matrix(lons_arr, lats_arr, station_ids)
    ds_for_qc, _ = _build_qc_dataset(rain_arr, dist_np, ds_pws_stacked, max_dist_km)

    try:
        ds_for_qc = pypwsqc.flagging.fz_filter(
            ds_for_qc, nint=nint, n_stat=n_stat
        )
        ds_for_qc = pypwsqc.flagging.hi_filter(
            ds_for_qc,
            hi_thres_a=np.array(hi_thres_a),
            hi_thres_b=np.array(hi_thres_b),
            nint=nint,
            n_stat=n_stat,
        )
        ds_for_qc = pypwsqc.flagging.so_filter(
            ds_for_qc,
            distance_matrix   = dist_da,
            evaluation_period = eval_period,
            mmatch = np.array(mmatch),
            gamma = np.array(gamma),
            n_stat = n_stat,
            max_distance = np.array(max_dist_km),
        )

        fz_flag = ds_for_qc["fz_flag"].values
        hi_flag = ds_for_qc["hi_flag"].values
        so_flag = ds_for_qc["so_flag"].values

        # flag == 1 means detected; -1 means unevaluated (treat as clean)
        combined_flag = (fz_flag == 1) | (hi_flag == 1) | (so_flag == 1)

        n_total = rain_arr.size
        print("QC Summary:")
        print(f"  Faulty Zero (FZ)    : {int((fz_flag==1).sum()):>8,}  "
              f"({int((fz_flag==1).sum())/n_total*100:.2f}%)")
        print(f"  High Influx (HI)    : {int((hi_flag==1).sum()):>8,}  "
              f"({int((hi_flag==1).sum())/n_total*100:.2f}%)")
        print(f"  Station Outlier (SO): {int((so_flag==1).sum()):>8,}  "
              f"({int((so_flag==1).sum())/n_total*100:.2f}%)")
        print(f"  Total flagged (any) : {int(combined_flag.sum()):>8,}  "
              f"({int(combined_flag.sum())/n_total*100:.2f}%)")

        qc_method = "pypwsqc FZ+HI+SO"

    except Exception as exc:
        print(f"pypwsqc error: {exc}")
        print("Fallback: flagging values > 100 mm.")
        combined_flag = rain_arr > 100.0
        qc_method = "fallback threshold >100 mm"

    ds_pws_qc = ds_pws_stacked.copy()
    ds_pws_qc[rain_var] = xr.DataArray(
        np.where(combined_flag, np.nan, rain_arr),
        dims=["id", "time"],
        coords=ds_pws_stacked[rain_var].coords,
    )
    ds_pws_qc.attrs["qc_method"] = qc_method
    ds_pws_qc.attrs["qc_max_dist_km"] = max_dist_km
    return ds_pws_qc
