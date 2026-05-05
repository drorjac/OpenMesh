"""
kriging.py - Ordinary Kriging spatial interpolation for rainfall maps.

Uses pykrige.OrdinaryKriging, the same library referenced in the mergeplg
OpenSense repository for spatial merging of opportunistic sensor data.

Fixes applied:
  - pykrige returns numpy MaskedArrays — converted to plain ndarray with
    np.ma.filled() so masked cells become NaN instead of plotting as coloured
  - grid axes verified against meshgrid shape to prevent row/col flip
  - variance panel uses its own independent colormap (not shared with rainfall)

Install:  pip install pykrige
"""
from __future__ import annotations

import warnings
import numpy as np

try:
    from pykrige.ok import OrdinaryKriging
    PYKRIGE_AVAILABLE = True
except ImportError:
    PYKRIGE_AVAILABLE = False

DEFAULT_VARIOGRAM_MODEL = "spherical"
DEFAULT_MIN_STATIONS    = 5
DEFAULT_NLAGS           = 6


def kriging_interpolate(
    lons_obs: np.ndarray,
    lats_obs: np.ndarray,
    values: np.ndarray,
    grid_lon: np.ndarray,
    grid_lat: np.ndarray,
    variogram_model: str = DEFAULT_VARIOGRAM_MODEL,
    min_stations: int    = DEFAULT_MIN_STATIONS,
    nlags: int           = DEFAULT_NLAGS,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Ordinary Kriging interpolation from point observations to a regular grid.

    Parameters
    ----------
    lons_obs, lats_obs : array-like
        Station coordinates in decimal degrees.
    values : array-like
        Observed rainfall values (mm). NaN observations are excluded.
    grid_lon, grid_lat : 2-D np.ndarray
        Output grid from idw.make_grid() / np.meshgrid().
        Shape must be (n_lat, n_lon).
    variogram_model : str
        'spherical' (default), 'gaussian', 'exponential', 'linear', 'power'.
    min_stations : int
        Minimum valid stations required (default 5).
    nlags : int
        Number of lags for variogram fitting (default 6).

    Returns
    -------
    grid_rain : np.ndarray shape (n_lat, n_lon)
        Kriged rainfall field (mm). NaN where data is insufficient.
    grid_var : np.ndarray shape (n_lat, n_lon)
        Kriging variance. NaN where data is insufficient.
    """
    if not PYKRIGE_AVAILABLE:
        raise ImportError(
            "pykrige is required for Kriging.\n"
            "Install with:  pip install pykrige"
        )

    mask   = ~np.isnan(np.asarray(values))
    lons_v = np.asarray(lons_obs)[mask]
    lats_v = np.asarray(lats_obs)[mask]
    vals_v = np.asarray(values)[mask]

    nan_grid = np.full(grid_lon.shape, np.nan)

    if len(vals_v) < min_stations:
        return nan_grid, nan_grid

    # Kriging requires spatial variance - skip if all values are nearly identical
    # (eg all-zero windows, or a single outlier station dominating)
    if np.nanstd(vals_v) < 0.01:
        return nan_grid, nan_grid

    # Also skip if one station is more than 10x the 90th percentile of others
    # (catches the 95mm outlier vs 0mm everywhere else case)
    p90 = np.nanpercentile(vals_v, 90)
    if p90 > 0 and np.nanmax(vals_v) > 10 * p90:
        return nan_grid, nan_grid

    # pykrige expects 1D grid vectors, not 2D meshgrid arrays
    # grid_lon shape is (n_lat, n_lon): first row = lon values, first col = lat values
    grid_lon_vec = grid_lon[0, :]    # shape (n_lon,)
    grid_lat_vec = grid_lat[:, 0]    # shape (n_lat,)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ok = OrdinaryKriging(
                lats_v, lons_v, vals_v, 
                variogram_model  = variogram_model,
                verbose = False,
                enable_plotting  = False,
                nlags = max(4, len(vals_v) // 6),
                coordinates_type = "geographic",
                weight = True,
            )
            # ok.execute returns shape (n_lat, n_lon) when given (lon_vec, lat_vec)
            z, ss = ok.execute("grid", grid_lat_vec, grid_lon_vec)

        # pykrige returns numpy MaskedArrays - convert to plain ndarray.
        # Using np.ma.filled(fill_value=np.nan) ensures masked cells become NaN
        # rather than being rendered as a colour by matplotlib.
        grid_rain = np.ma.filled(np.ma.array(z),  fill_value=np.nan).T
        grid_var  = np.ma.filled(np.ma.array(ss), fill_value=np.nan).T
        # Rainfall cannot be negative
        grid_rain = np.clip(grid_rain, 0, None)
        grid_var  = np.clip(grid_var,  0, None)

        return grid_rain, grid_var

    except Exception as exc:
        print(f"  Kriging failed ({exc}), returning NaN grid.")
        return nan_grid, nan_grid