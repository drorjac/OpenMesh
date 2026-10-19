"""NEXRAD Level-3 data for OpenMesh: KOKX (Upton, NY).

Fetches dual-pol products (HHC hydrometeor class, N0B reflectivity, N0X ZDR, N0C CC)
from the AWS unidata-nexrad-level3 bucket. Complements MRMS with radar reflectivity
and hydrometeor classification at ~1.5 km above ground (KOKX beam centre).

Usage::

    from fetch_data.nexrad import kokx
    from fetch_data.nexrad import HYDRO_LEGEND, PRODUCTS

    kokx.fetch_window("2024-01-09", "2024-01-10")        # download and cache
    df = kokx.load("2024-01-09", "2024-01-10", "HHC")    # load cached samples
"""

from .kokx import HYDRO_LEGEND, PRODUCTS, fetch_window, load

__all__ = ["kokx", "HYDRO_LEGEND", "PRODUCTS", "fetch_window", "load"]
