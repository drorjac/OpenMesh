"""NEXRAD Level-3 data for OpenMesh: KOKX (Upton, NY).

Fetches dual-pol products (HHC hydrometeor class, N0B reflectivity, N0X ZDR, N0C CC)
from the AWS unidata-nexrad-level3 bucket. Complements MRMS with radar reflectivity
(0.5° tilt, ~1–1.5 km above ground over the links) and hybrid hydrometeor classification.

Usage::

    from fetch_data.nexrad import kokx
    scan = kokx.read_scan("N0B", "2024-03-23 12:00")     # one raw scan (polar)
    kokx.fetch_window("2024-03-23", "2024-03-24")         # samples at the links, cached
    df = kokx.load("2024-03-23", "2024-03-24", "N0B")     # load cached samples
"""

from . import kokx
from .kokx import (HYDRO_LEGEND, PRODUCTS, fetch_window, grid_axes, hourly_rain, link_points,
                   load, load_grid, rain_field, rain_rate, read_scan, sample_grid, scan_lonlat)

__all__ = ["kokx", "HYDRO_LEGEND", "PRODUCTS", "fetch_window", "grid_axes", "hourly_rain",
           "link_points", "load", "load_grid", "rain_field", "rain_rate", "read_scan", "sample_grid",
           "scan_lonlat"]
