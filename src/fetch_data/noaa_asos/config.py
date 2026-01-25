"""
ASOS Data Configuration
=======================

ASOS-SPECIFIC configuration for data processing and column mappings.

Data Source: IEM ASOS 1-Minute Archive
Resolution: 1-minute instantaneous readings
Delay: 18-36 hours (not real-time)

Filename Format:
- Combined files: ASOS_{interval}_{start_date}_{end_date}.csv
- Example: ASOS_1min_2024-01-01_2024-01-30.csv
"""

# =============================================================================
# RAW COLUMN NAMES (from API - US units)
# =============================================================================

RAW_COLUMNS = {
    'datetime': 'valid(UTC)',
    'station_id': 'station',
    'temperature': 'tmpf',       # °F
    'dewpoint': 'dwpf',          # °F
    'wind_speed': 'sknt',        # knots
    'wind_dir': 'drct',          # degrees
    'wind_gust': 'gust_sknt',    # knots
    'wind_gust_dir': 'gust_drct',# degrees
    'precipitation': 'precip',   # inches
    'precip_type': 'ptype',      # raw code
}

# =============================================================================
# PROCESSED DATA COLUMNS (Standardized - shared with WU)
# =============================================================================
# These column names are shared across ASOS and WU for consistency.
# For ASOS: Values are INSTANTANEOUS 1-minute readings from airport sensors.

PROCESSED_COLUMNS = {
    'datetime': 'datetime',           # UTC timestamp
    'station_id': 'station_id',       # 3-letter airport code (e.g., 'JFK')
    
    # PRECIPITATION
    'precip_amount': 'precip_amount', # [mm] Total precipitation per interval (instantaneous 1-min reading)
    'precip_rate': 'precip_rate',     # [mm/hr] Calculated rate from per-minute totals
    'precip_type': 'precip_type',     # Raw ASOS code (NP, R, S, P, M, etc.)
    'precip_category': 'precip_category',  # Simplified: dry, rain, snow, precip, missing
    
    # TEMPERATURE
    'temperature': 'temperature',     # [°C] Instantaneous air temperature
    'dewpoint': 'dewpoint',           # [°C] Instantaneous dewpoint temperature
    
    # WIND
    'wind_speed': 'wind_speed',       # [m/s] Instantaneous wind speed
    'wind_direction': 'wind_direction',  # [degrees] Instantaneous wind direction (0-360)
    'wind_gust': 'wind_gust',         # [m/s] Instantaneous wind gust speed
    'wind_gust_direction': 'wind_gust_direction',  # [degrees] Wind gust direction
}

# =============================================================================
# COLUMN INFO (documentation)
# =============================================================================

COLUMN_INFO = {
    'datetime':       {'unit': 'UTC',     'description': 'Observation timestamp'},
    'station_id':     {'unit': '-',       'description': '3-letter airport code'},
    'precip_amount':  {'unit': 'mm',      'description': 'Precipitation amount per 1-min interval'},
    'precip_rate':    {'unit': 'mm/hr',   'description': 'Precipitation rate (calculated)'},
    'precip_type':    {'unit': '-',       'description': 'Raw ASOS precip type code'},
    'precip_category':{'unit': '-',       'description': 'Simplified category: dry/rain/snow/precip/missing'},
    'temperature':    {'unit': '°C',      'description': 'Air temperature (instantaneous)'},
    'dewpoint':       {'unit': '°C',      'description': 'Dewpoint temperature (instantaneous)'},
    'wind_speed':     {'unit': 'm/s',     'description': 'Wind speed (instantaneous)'},
    'wind_direction': {'unit': 'degrees', 'description': 'Wind direction 0-360 (instantaneous)'},
    'wind_gust':      {'unit': 'm/s',     'description': 'Wind gust speed (instantaneous)'},
    'wind_gust_direction': {'unit': 'degrees', 'description': 'Wind gust direction'},
}

# =============================================================================
# FILENAME PREFIXES
# =============================================================================

FILENAME_PREFIXES = {
    'raw': 'raw',                    # Raw data (original API format)
    'processed': '1min',             # Processed 1-minute data
    'combined': 'ASOS',              # Combined all-stations prefix
}

# =============================================================================
# DEFAULT VALUES
# =============================================================================

# Default resampling interval for time series aggregation
DEFAULT_RESAMPLE_INTERVAL = '5min'