"""
idw.py - Inverse Distance Weighting spatial interpolation for rainfall maps.

Formula:  R_hat(x) = sum(w_i * R_i) / sum(w_i),   w_i = 1 / d_i^p
"""
from __future__ import annotations
import numpy as np
from scipy.spatial import cKDTree

DEFAULT_POWER = 2
DEFAULT_GRID_RES_DEG = 0.01
DEFAULT_GRID_PAD_DEG = 0.05
DEFAULT_MIN_STATIONS = 3
DEFAULT_K_NEIGHBOURS = 10


def make_grid(
    lons: np.ndarray,
    lats: np.ndarray,
    res: float = DEFAULT_GRID_RES_DEG,
    pad: float = DEFAULT_GRID_PAD_DEG,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a regular lon/lat grid covering the station bounding box."""
    lons = np.asarray(lons)
    lats = np.asarray(lats)

    if np.all(np.isnan(lons)) or np.all(np.isnan(lats)):
        raise ValueError(
            "All station coordinates are NaN. "
            "Check that pws_metadata.csv was found and loaded correctly "
            "(pass --pws-meta explicitly if needed)."
        )

    lon_min = np.nanmin(lons) - pad
    lon_max = np.nanmax(lons) + pad
    lat_min = np.nanmin(lats) - pad
    lat_max = np.nanmax(lats) + pad

    lon_vec = np.arange(lon_min, lon_max, res)
    lat_vec = np.arange(lat_min, lat_max, res)
    return np.meshgrid(lon_vec, lat_vec)


def idw_interpolate(
    lons_obs: np.ndarray,
    lats_obs: np.ndarray,
    values: np.ndarray,
    grid_lon: np.ndarray,
    grid_lat: np.ndarray,
    power: float = DEFAULT_POWER,
    min_stations: int = DEFAULT_MIN_STATIONS,
    k: int = DEFAULT_K_NEIGHBOURS,
) -> np.ndarray:
    """
    IDW interpolation from point observations to a regular grid.

    Returns 2-D array matching grid_lon shape. All-NaN if < min_stations valid.
    """
    mask = ~np.isnan(np.asarray(values))
    lons_v = np.asarray(lons_obs)[mask]
    lats_v = np.asarray(lats_obs)[mask]
    vals_v = np.asarray(values)[mask]

    if len(vals_v) < min_stations:
        return np.full(grid_lon.shape, np.nan)

    grid_pts = np.column_stack([grid_lon.ravel(), grid_lat.ravel()])
    obs_pts = np.column_stack([lons_v, lats_v])

    tree = cKDTree(obs_pts)
    dists, idxs = tree.query(grid_pts, k=min(len(vals_v), k))
    dists = np.where(dists == 0, 1e-10, dists)
    weights = 1.0 / dists ** power
    result = (weights * vals_v[idxs]).sum(axis=1) / weights.sum(axis=1)
    return result.reshape(grid_lon.shape)
