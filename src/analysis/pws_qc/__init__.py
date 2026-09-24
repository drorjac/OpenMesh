"""
PWS QC subpackage — Personal Weather Station quality control + multi-network plot helpers.

Two submodules, both re-exported at package level:
    qc     — pyramid filter, ASOS bypass, condition encoding, save helpers
    plots  — folium maps, accumulation plots, event zooms, cross-network helpers

Usage:
    from analysis.pws_qc import QCConfig, pyramid_qc, save_qc      # from qc.py
    from analysis.pws_qc import plot_accumulation, plot_event_zoom  # from plots.py
"""

from .qc import (
    ASOS_STATIONS, QCConfig,
    pyramid_qc, encode_condition, save_qc, read_qc_status,
    verify_utc_time,
)

from .plots import (
    DEFAULT_COLORS,
    network_resample, network_hourly_rain, station_locations,
    filter_stations_by_bbox,
    station_map_folium, station_map_static,
    plot_accumulation, plot_overlay,
    plot_event_zoom, plot_event_qc_compare,
    plot_per_station_before_after,
    plot_daily_heatmap,
    pairwise_correlation,
)

__all__ = [
    # qc
    'ASOS_STATIONS', 'QCConfig',
    'pyramid_qc', 'encode_condition', 'save_qc', 'read_qc_status',
    'verify_utc_time',
    # plots
    'DEFAULT_COLORS',
    'network_resample', 'network_hourly_rain', 'station_locations',
    'filter_stations_by_bbox',
    'station_map_folium', 'station_map_static',
    'plot_accumulation', 'plot_overlay',
    'plot_event_zoom', 'plot_event_qc_compare',
    'plot_per_station_before_after',
    'plot_daily_heatmap',
    'pairwise_correlation',
]
