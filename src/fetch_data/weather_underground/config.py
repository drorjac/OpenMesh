"""
Weather Underground PWS Data Configuration
==========================================

WU-SPECIFIC configuration for API access, column mappings, and data processing.

Data Source: Weather Underground Personal Weather Stations API
Resolution: Typically hourly aggregated data (avg/high/low per hour)
API Key: Required (set WU_API_KEY environment variable)

Unit Conversions Applied:
- Wind speed: km/h → m/s (to match ASOS standard)
- All other units already in metric

Filename Format:
- Combined files: WU_{start_date}_{end_date}.csv
- Example: WU_2024-01-01_2024-01-30.csv
"""

# =============================================================================
# API CONFIGURATION
# =============================================================================

BASE_URL = "https://api.weather.com/v2/pws"

# All available parameters in WU PWS API responses
CURRENT_PARAMS = {
    'stationID': 'Station ID',
    'obsTimeUtc': 'Observation Time (UTC)',
    'obsTimeLocal': 'Observation Time (Local)',
    'neighborhood': 'Neighborhood',
    'softwareType': 'Software Type',
    'country': 'Country',
    'solarRadiation': 'Solar Radiation (W/m²)',
    'lon': 'Longitude',
    'realtimeFrequency': 'Realtime Frequency',
    'epoch': 'Epoch Time',
    'lat': 'Latitude',
    'uv': 'UV Index',
    'winddir': 'Wind Direction (degrees)',
    'humidity': 'Humidity (%)',
    'qcStatus': 'QC Status'
}

IMPERIAL_PARAMS = {
    'temp': 'Temperature (°F)',
    'heatIndex': 'Heat Index (°F)',
    'dewpt': 'Dew Point (°F)',
    'windChill': 'Wind Chill (°F)',
    'windSpeed': 'Wind Speed (mph)',
    'windGust': 'Wind Gust (mph)',
    'pressure': 'Pressure (in)',
    'precipRate': 'Precipitation Rate (in/hr)',
    'precipTotal': 'Precipitation Total (in)',
    'elev': 'Elevation (ft)'
}

METRIC_PARAMS = {
    'temp': 'Temperature (°C)',
    'heatIndex': 'Heat Index (°C)',
    'dewpt': 'Dew Point (°C)',
    'windChill': 'Wind Chill (°C)',
    'windSpeed': 'Wind Speed (km/h)',
    'windGust': 'Wind Gust (km/h)',
    'pressure': 'Pressure (mb)',
    'precipRate': 'Precipitation Rate (mm/hr)',
    'precipTotal': 'Precipitation Total (mm)',
    'elev': 'Elevation (m)'
}

# =============================================================================
# UNIT LABELS (for plotting)
# =============================================================================

UNITS = {
    'precip_rate': 'mm/h',
    'precip_amount': 'mm',
    'temperature': '°C',
    'dewpoint': '°C',
    'wind_speed': 'm/s',
    'wind_gust': 'm/s',
    'humidity': '%',
    'pressure': 'hPa',
    'wind_direction': '°',
}

# =============================================================================
# COLUMN MAPPING: API names → standardized names
# =============================================================================
# Standardized names are SHARED with ASOS for cross-dataset compatibility.
# For WU: Values are HOURLY AGGREGATES (avg/high/low) from personal weather stations.
# Units: °C, m/s (converted from km/h), mm, mm/hr, degrees, %, mb

WU_COLUMN_MAPPING = {
    # ========== PRECIPITATION [mm, mm/hr] ==========
    'metric.precipRate': 'precip_rate',       # [mm/hr] hourly avg rate
    'metric.precipTotal': 'precip_amount',    # [mm] total for hour (SHARED)

    # ========== TIME & LOCATION ==========
    'obsTimeLocal': 'time_local',
    'obsTimeUtc': 'datetime',                 # [UTC] standardized (SHARED)
    'epoch': 'timestamp_unix',
    'stationID': 'station_id',                # (SHARED)
    'tz': 'timezone',
    'lat': 'latitude',
    'lon': 'longitude',

    # ========== TEMPERATURE [°C] ==========
    'metric.tempHigh': 'temperature_high',
    'metric.tempLow': 'temperature_low',
    'metric.tempAvg': 'temperature',          # [°C] hourly avg (SHARED)
    'metric.heatindexHigh': 'heat_index_high',
    'metric.heatindexLow': 'heat_index_low',
    'metric.heatindexAvg': 'heat_index',
    'metric.windchillHigh': 'wind_chill_high',
    'metric.windchillLow': 'wind_chill_low',
    'metric.windchillAvg': 'wind_chill',
    'metric.dewptHigh': 'dewpoint_high',
    'metric.dewptLow': 'dewpoint_low',
    'metric.dewptAvg': 'dewpoint',            # [°C] hourly avg (SHARED)

    # ========== HUMIDITY [%] ==========
    'humidityHigh': 'humidity_high',
    'humidityLow': 'humidity_low',
    'humidityAvg': 'humidity',                # [%] hourly avg (SHARED)

    # ========== WIND [m/s, converted from km/h] ==========
    'metric.windspeedHigh': 'wind_speed_high',
    'metric.windspeedLow': 'wind_speed_low',
    'metric.windspeedAvg': 'wind_speed',      # [m/s] hourly avg (SHARED)
    'metric.windgustHigh': 'wind_gust_high',
    'metric.windgustLow': 'wind_gust_low',
    'metric.windgustAvg': 'wind_gust',        # [m/s] hourly max (SHARED)
    'winddirAvg': 'wind_direction',           # [degrees] hourly avg (SHARED)

    # ========== PRESSURE [mb] ==========
    'metric.pressureMax': 'pressure',         # [mb] hourly max (SHARED)
    'metric.pressureMin': 'pressure_min',
    'metric.pressureTrend': 'pressure_trend',

    # ========== SOLAR/UV ==========
    'solarRadiationHigh': 'solar_radiation_high',
    'uvHigh': 'uv_index_high',

    # ========== QUALITY ==========
    'qcStatus': 'qc_status',
}

# Reversed mapping for converting back if needed
SIMPLE_TO_WU_MAPPING = {v: k for k, v in WU_COLUMN_MAPPING.items()}

# =============================================================================
# COLUMN ORDERING - PRECIPITATION FIRST!
# =============================================================================

COLUMN_ORDER = [
    # PRECIPITATION FIRST! [mm, mm/hr]
    'precip_rate',        # [mm/hr] (SHARED)
    'precip_amount',      # [mm] (SHARED)

    # Time
    'time_local',
    'datetime',           # [UTC] (SHARED)
    'timestamp_unix',

    # Location
    'station_id',         # (SHARED)
    'latitude',
    'longitude',
    'timezone',

    # Temperature [°C]
    'temperature',        # (SHARED)
    'temperature_high',
    'temperature_low',
    'dewpoint',           # (SHARED)
    'dewpoint_high',
    'dewpoint_low',
    'heat_index',
    'heat_index_high',
    'heat_index_low',
    'wind_chill',
    'wind_chill_high',
    'wind_chill_low',

    # Humidity [%]
    'humidity',           # (SHARED)
    'humidity_high',
    'humidity_low',

    # Wind [m/s]
    'wind_speed',         # (SHARED)
    'wind_speed_high',
    'wind_speed_low',
    'wind_gust',          # (SHARED)
    'wind_gust_high',
    'wind_gust_low',
    'wind_direction',     # [degrees] (SHARED)

    # Pressure [mb]
    'pressure',           # (SHARED)
    'pressure_min',
    'pressure_trend',

    # Solar/UV
    'solar_radiation_high',
    'uv_index_high',

    # Quality
    'qc_status',
]

# =============================================================================
# COLUMN INFO (documentation)
# =============================================================================

COLUMN_INFO = {
    'datetime':       {'unit': 'UTC',     'description': 'Observation timestamp'},
    'station_id':     {'unit': '-',       'description': 'PWS station ID'},
    'precip_amount':  {'unit': 'mm',      'description': 'Precipitation total for hour'},
    'precip_rate':    {'unit': 'mm/hr',   'description': 'Precipitation rate (hourly avg)'},
    'temperature':    {'unit': '°C',      'description': 'Air temperature (hourly avg)'},
    'dewpoint':       {'unit': '°C',      'description': 'Dewpoint temperature (hourly avg)'},
    'wind_speed':     {'unit': 'm/s',     'description': 'Wind speed (hourly avg, converted from km/h)'},
    'wind_direction': {'unit': 'degrees', 'description': 'Wind direction 0-360 (hourly avg)'},
    'wind_gust':      {'unit': 'm/s',     'description': 'Wind gust max (converted from km/h)'},
    'humidity':       {'unit': '%',       'description': 'Relative humidity (hourly avg)'},
    'pressure':       {'unit': 'mb',      'description': 'Air pressure (hourly max)'},
}

# =============================================================================
# API KEY CONFIGURATION
# =============================================================================
# Weather Underground API requires an API key for authentication.
#
# 📖 For complete setup instructions, see: API_KEY_SETUP.md
#
# QUICK SETUP (Recommended):
#   export WU_API_KEY="your_key_here"
#   Add to ~/.zshrc or ~/.bashrc for persistence
#
# CONFIGURATION PRIORITY:
#   1. Environment Variable (WU_API_KEY) - RECOMMENDED
#   2. Config File (WU_API_KEY below) - Fallback only
#   3. CLI Argument (--api-key flag) - Overrides both
#
# GET YOUR API KEY:
#   https://www.wunderground.com/member/api-keys

# Fallback API key (only used if WU_API_KEY env var is not set)
# Leave empty and use environment variable instead (recommended)
WU_API_KEY = '****************'  # Fallback only - use env var instead




def load_api_key_from_shell_config():
    """
    Load WU_API_KEY from shell configuration files (.zshrc, .bashrc, etc.)
    if not already set in environment.
    
    This is useful for notebook kernels that don't inherit shell environment variables.
    
    Returns
    -------
    bool
        True if API key was loaded, False otherwise
    """
    import os
    from pathlib import Path
    
    # Skip if already set
    if os.environ.get('WU_API_KEY'):
        return False
    
    home = Path.home()
    for rc_file in ['.zshrc', '.bashrc', '.bash_profile']:
        rc_path = home / rc_file
        if rc_path.exists():
            try:
                with open(rc_path, 'r') as f:
                    for line in f:
                        if line.strip().startswith('export WU_API_KEY='):
                            # Extract the key value (handles both "key" and 'key' formats)
                            key_value = line.split('=', 1)[1].strip().strip('"').strip("'")
                            if key_value:
                                os.environ['WU_API_KEY'] = key_value
                                return True
            except Exception:
                pass  # Silently continue if file can't be read
    
    return False


def check_api_key_status():
    """
    Check if API key is available and return status information.
    
    Returns
    -------
    dict
        Dictionary with 'available', 'source', and 'message' keys
    """
    import os
    
    # Try loading from shell config
    loaded_from_file = load_api_key_from_shell_config()
    
    # Check environment variable
    api_key = os.environ.get('WU_API_KEY')
    if api_key and api_key.strip():
        source = 'shell_config_file' if loaded_from_file else 'environment_variable'
        return {
            'available': True,
            'source': source,
            'message': f'✓ API key found ({source})'
        }
    
    # Check config file
    if WU_API_KEY and WU_API_KEY.strip():
        return {
            'available': True,
            'source': 'config_file',
            'message': '✓ API key found (config file)'
        }
    
    # Not found
    return {
        'available': False,
        'source': None,
        'message': '⚠ WARNING: API key not found. Cannot fetch data. Set WU_API_KEY environment variable or in config.py'
    }


def get_api_key(api_key=None, raise_error=True):
    """
    Get WU API key from direct parameter, environment variable, or config file.
    
    Priority order:
    1. Direct parameter (if provided) - Use when passing key directly
    2. Environment variable (WU_API_KEY) - RECOMMENDED for most cases
    3. Config file (WU_API_KEY constant) - Fallback only (if env var not set)
    
    If config file has empty string or None, it will still check environment variable first.
    
    Parameters
    ----------
    api_key : str, optional
        Direct API key string. If provided, this takes highest priority.
        Use this when you want to pass the key directly instead of using env var.
    raise_error : bool, default True
        If True, raise ValueError when key not found. If False, return None.
    
    Returns
    -------
    str or None
        API key string (stripped of whitespace), or None if not found and raise_error=False
        
    Raises
    ------
    ValueError
        If no API key is found and raise_error=True
        
    Examples
    --------
    >>> # Use environment variable (default)
    >>> key = get_api_key()
    
    >>> # Pass key directly
    >>> key = get_api_key(api_key='your_key_here')
    
    >>> # Pass key directly, don't raise error if not found
    >>> key = get_api_key(api_key='your_key_here', raise_error=False)
    """
    import os
    
    # Priority 1: Direct parameter (if provided)
    if api_key and isinstance(api_key, str) and api_key.strip():
        return api_key.strip()
    
    # Try loading from shell config files (for notebook kernels)
    load_api_key_from_shell_config()
    
    # Priority 2: Check environment variable
    env_api_key = os.environ.get('WU_API_KEY')
    
    # Priority 3: Only use config file if env var is not set, None, or empty string
    if not env_api_key or (isinstance(env_api_key, str) and env_api_key.strip() == ''):
        # Fallback to config file value
        api_key = WU_API_KEY
    else:
        api_key = env_api_key
    
    # Validate that we have a non-empty key
    if not api_key or (isinstance(api_key, str) and api_key.strip() == ''):
        if raise_error:
            raise ValueError(
                "WU_API_KEY not found. Set it as:\n"
                "  1. Direct parameter: get_api_key(api_key='your_key')\n"
                "  2. Environment variable: export WU_API_KEY='your_key'\n"
                "  3. Config file: Add to weather_underground/config.py\n"
                "Or add to ~/.zshrc for persistence.\n"
                "See API_KEY_SETUP.md for detailed instructions."
            )
        else:
            return None
    
    # Return stripped key (remove any whitespace)
    return api_key.strip() if isinstance(api_key, str) else api_key