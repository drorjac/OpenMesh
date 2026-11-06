"""Helpers of the v2 notebooks (tutorials/v2/), from the record's openmesh_tools.

    from analysis import v2 as om
    om.setup()                                  # D.use('v2'), finds the record, sets the plot style
    meta = om.link_meta()                       # one row per path
    x = om.links(cml_ids=["6"], start="2024-01-09", end="2024-01-11")

Files are read by analysis.datasets, the k-R law is analysis.itu_rainrate and the
rolling-median attenuation is analysis.cml_baseline; plots, quality and checks are the
record's own.
"""
from .io import (ERA_END, SIGNALS, aggregation_window, asos, asos_stations, band_of, data_dir, find_data, hourly,
                 link_meta, links, open_links, radar, radar_events, radar_kokx, set_data_dir, setup, split_of,
                 sublink_meta)
from .analysis import (attenuation, day_of, haversine, hourly_attenuation, link_level, nearest, radar_along_link,
                       xcorr_lags)
from .style import BAND_COLOR, BANDS, SLOT, SPLIT, SPLIT_COLOR, SPLIT_LABEL, style
from . import analysis, checks, plots, quality
