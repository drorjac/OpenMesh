"""MRMS radar (NOAA/NSSL Multi-Radar/Multi-Sensor) for NYC: fetch, crop, cache, sample.

Ported from github.com/drorjac/pcpn_maps (commit e56d297). Files come from the NOAA
open-data bucket ``noaa-mrms-pds`` (AWS, archive from Oct 2020) with the IEM mtarchive
mirror as fallback; decoding needs ``eccodes``. Only a small crop per product/day is kept
under ``dataset/raw/radar/mrms/cache`` (see :func:`default_data_dir`).

    from fetch_data.mrms import MRMSClient, NYC, hourly_rainfall
    qpe = hourly_rainfall("2024-01-09", "2024-01-10", NYC)   # (time, lat, lon) mm/h
"""

from .client import MRMSClient, MRMSError, MRMSNotFound, default_data_dir, file_url, valid_times
from .domain import NYC, OPENMESH, Domain, Grid, haversine_m
from .maps import (QPE_1H, domain_mean_series, event_accumulation, hourly_rainfall,
                   mask_low_quality, path_average, rain_rate, sample_points, to_grid)
from .products import (COOL_RAIN_FLAGS, PRECIP_FLAG, PRODUCTS, RAIN_FLAGS, SNOW_FLAGS,
                       MRMSProduct, get_product)

__all__ = ["MRMSClient", "MRMSError", "MRMSNotFound", "default_data_dir", "file_url",
           "valid_times", "NYC", "OPENMESH", "Domain", "Grid", "haversine_m", "QPE_1H",
           "domain_mean_series", "event_accumulation", "hourly_rainfall", "mask_low_quality",
           "path_average", "rain_rate", "sample_points", "to_grid", "COOL_RAIN_FLAGS",
           "PRECIP_FLAG", "PRODUCTS", "RAIN_FLAGS", "SNOW_FLAGS", "MRMSProduct", "get_product"]
