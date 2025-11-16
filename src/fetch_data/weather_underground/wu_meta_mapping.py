"""
Weather Underground Data Column Mapping Configuration
Converts complex nested column names to simple, clean names
Precipitation columns come first!
"""

# ============================================================================
# COLUMN MAPPING CONFIGURATION
# ============================================================================

# Column mapping: original_name -> new_simple_name
# Organized by category with precipitation FIRST
WU_COLUMN_MAPPING = {
    # ========== PRECIPITATION (FIRST!) ==========
    'metric.precipRate': 'precip_rate',  # mm/h or in/h
    'metric.precipTotal': 'precip_total',  # mm or in

    # ========== TIME & LOCATION ==========
    'obsTimeLocal': 'time_local',
    'obsTimeUtc': 'time_utc',
    'epoch': 'timestamp_unix',
    'stationID': 'station_id',
    'tz': 'timezone',
    'lat': 'latitude',
    'lon': 'longitude',

    # ========== TEMPERATURE ==========
    'metric.tempHigh': 'temp_high',
    'metric.tempLow': 'temp_low',
    'metric.tempAvg': 'temp_avg',
    'metric.heatindexHigh': 'heat_index_high',
    'metric.heatindexLow': 'heat_index_low',
    'metric.heatindexAvg': 'heat_index_avg',
    'metric.windchillHigh': 'wind_chill_high',
    'metric.windchillLow': 'wind_chill_low',
    'metric.windchillAvg': 'wind_chill_avg',
    'metric.dewptHigh': 'dewpoint_high',
    'metric.dewptLow': 'dewpoint_low',
    'metric.dewptAvg': 'dewpoint_avg',

    # ========== HUMIDITY ==========
    'humidityHigh': 'humidity_high',
    'humidityLow': 'humidity_low',
    'humidityAvg': 'humidity_avg',

    # ========== WIND ==========
    'metric.windspeedHigh': 'wind_speed_high',
    'metric.windspeedLow': 'wind_speed_low',
    'metric.windspeedAvg': 'wind_speed_avg',
    'metric.windgustHigh': 'wind_gust_high',
    'metric.windgustLow': 'wind_gust_low',
    'metric.windgustAvg': 'wind_gust_avg',
    'winddirAvg': 'wind_direction_avg',

    # ========== PRESSURE ==========
    'metric.pressureMax': 'pressure_max',
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

# ============================================================================
# COLUMN ORDERING - PRECIPITATION FIRST!
# ============================================================================

# Define the order of columns in the clean DataFrame
COLUMN_ORDER = [
    # PRECIPITATION FIRST!
    'precip_rate',
    'precip_total',

    # Time
    'time_local',
    'time_utc',
    'timestamp_unix',

    # Location
    'station_id',
    'latitude',
    'longitude',
    'timezone',

    # Temperature
    'temp_avg',
    'temp_high',
    'temp_low',
    'dewpoint_avg',
    'dewpoint_high',
    'dewpoint_low',
    'heat_index_avg',
    'heat_index_high',
    'heat_index_low',
    'wind_chill_avg',
    'wind_chill_high',
    'wind_chill_low',

    # Humidity
    'humidity_avg',
    'humidity_high',
    'humidity_low',

    # Wind
    'wind_speed_avg',
    'wind_speed_high',
    'wind_speed_low',
    'wind_gust_avg',
    'wind_gust_high',
    'wind_gust_low',
    'wind_direction_avg',

    # Pressure
    'pressure_max',
    'pressure_min',
    'pressure_trend',

    # Solar/UV
    'solar_radiation_high',
    'uv_index_high',

    # Quality
    'qc_status',
]


# ============================================================================
# CONVERSION FUNCTIONS
# ============================================================================

"""
Read PWS Metadata from OpenMesh Dataset
========================================
Reads pws_metadata.csv containing NYC Personal Weather Station information
"""

import pandas as pd
from pathlib import Path


def find_project_root():
    """Find project root by looking for dataset folder"""
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / 'dataset' / 'weather stations').exists():
            return parent
    return None


def read_pws_metadata(custom_path=None):
    """
    Read PWS metadata CSV file

    Args:
        custom_path: Optional path to pws_metadata.csv

    Returns:
        DataFrame with PWS metadata
    """
    if custom_path:
        df = pd.read_csv(custom_path)
    else:
        root = find_project_root()
        if root is None:
            raise FileNotFoundError("Could not find dataset folder. Please provide custom_path.")
        df = pd.read_csv(root / 'dataset' / 'weather stations' / 'pws_metadata.csv')

    # Clean up
    if 'Unnamed: 0' in df.columns:
        df = df.drop(columns=['Unnamed: 0'])

    return df


def get_station_list(pws_meta):
    """
    Get list of station IDs

    Args:
        pws_meta: DataFrame with PWS metadata

    Returns:
        List of station IDs
    """
    return pws_meta['Station ID'].tolist()


def convert_wu_columns(df, keep_original=False):
    """
    Convert Weather Underground DataFrame columns to simple names
    Precipitation columns come first!

    Args:
        df: pandas DataFrame with WU data
        keep_original: If True, keep original columns with '_orig' suffix

    Returns:
        DataFrame with renamed columns
    """
    import pandas as pd

    # Make a copy
    df_clean = df.copy()

    # Keep original columns if requested
    if keep_original:
        for old_col, new_col in WU_COLUMN_MAPPING.items():
            if old_col in df_clean.columns:
                df_clean[f'{new_col}_orig'] = df_clean[old_col]

    # Rename columns
    df_clean = df_clean.rename(columns=WU_COLUMN_MAPPING)

    # Reorder columns (precipitation first!)
    available_cols = [col for col in COLUMN_ORDER if col in df_clean.columns]
    other_cols = [col for col in df_clean.columns if col not in available_cols]

    # Precipitation columns first, then rest in order, then any extras
    df_clean = df_clean[available_cols + other_cols]

    return df_clean


def create_metadata_df(df):
    """
    Create a metadata DataFrame with column descriptions

    Args:
        df: pandas DataFrame with clean column names

    Returns:
        DataFrame with metadata (column name, description, units, data type)
    """
    import pandas as pd

    metadata = {
        # Precipitation
        'precip_rate': ('Precipitation Rate', 'mm/h or in/h', 'float'),
        'precip_total': ('Precipitation Total', 'mm or in', 'float'),

        # Time
        'time_local': ('Observation Time (Local)', 'datetime', 'datetime'),
        'time_utc': ('Observation Time (UTC)', 'datetime', 'datetime'),
        'timestamp_unix': ('Unix Timestamp', 'seconds since epoch', 'int'),

        # Location
        'station_id': ('Weather Station ID', 'string', 'object'),
        'latitude': ('Latitude', 'degrees', 'float'),
        'longitude': ('Longitude', 'degrees', 'float'),
        'timezone': ('Time Zone', 'string', 'object'),

        # Temperature
        'temp_avg': ('Temperature Average', '°C or °F', 'float'),
        'temp_high': ('Temperature High', '°C or °F', 'float'),
        'temp_low': ('Temperature Low', '°C or °F', 'float'),
        'dewpoint_avg': ('Dew Point Average', '°C or °F', 'float'),
        'dewpoint_high': ('Dew Point High', '°C or °F', 'float'),
        'dewpoint_low': ('Dew Point Low', '°C or °F', 'float'),
        'heat_index_avg': ('Heat Index Average', '°C or °F', 'float'),
        'heat_index_high': ('Heat Index High', '°C or °F', 'float'),
        'heat_index_low': ('Heat Index Low', '°C or °F', 'float'),
        'wind_chill_avg': ('Wind Chill Average', '°C or °F', 'float'),
        'wind_chill_high': ('Wind Chill High', '°C or °F', 'float'),
        'wind_chill_low': ('Wind Chill Low', '°C or °F', 'float'),

        # Humidity
        'humidity_avg': ('Humidity Average', '%', 'float'),
        'humidity_high': ('Humidity High', '%', 'float'),
        'humidity_low': ('Humidity Low', '%', 'float'),

        # Wind
        'wind_speed_avg': ('Wind Speed Average', 'km/h or mph', 'float'),
        'wind_speed_high': ('Wind Speed High', 'km/h or mph', 'float'),
        'wind_speed_low': ('Wind Speed Low', 'km/h or mph', 'float'),
        'wind_gust_avg': ('Wind Gust Average', 'km/h or mph', 'float'),
        'wind_gust_high': ('Wind Gust High', 'km/h or mph', 'float'),
        'wind_gust_low': ('Wind Gust Low', 'km/h or mph', 'float'),
        'wind_direction_avg': ('Wind Direction Average', 'degrees (0-360)', 'float'),

        # Pressure
        'pressure_max': ('Pressure Maximum', 'mb or inHg', 'float'),
        'pressure_min': ('Pressure Minimum', 'mb or inHg', 'float'),
        'pressure_trend': ('Pressure Trend', 'mb or inHg', 'float'),

        # Solar/UV
        'solar_radiation_high': ('Solar Radiation High', 'W/m²', 'float'),
        'uv_index_high': ('UV Index High', 'index', 'float'),

        # Quality
        'qc_status': ('Quality Control Status', 'status code', 'int'),
    }

    # Build metadata DataFrame
    meta_data = []
    for col in df.columns:
        if col in metadata:
            desc, units, dtype = metadata[col]
            meta_data.append({
                'column': col,
                'description': desc,
                'units': units,
                'data_type': dtype,
                'has_data': df[col].notna().any(),
                'non_null_count': df[col].notna().sum(),
                'null_count': df[col].isna().sum(),
            })
        else:
            # Unknown column
            meta_data.append({
                'column': col,
                'description': 'Unknown',
                'units': 'Unknown',
                'data_type': str(df[col].dtype),
                'has_data': df[col].notna().any(),
                'non_null_count': df[col].notna().sum(),
                'null_count': df[col].isna().sum(),
            })

    return pd.DataFrame(meta_data)


def print_column_comparison(df_original, df_clean):
    """
    Print a comparison of original vs clean column names

    Args:
        df_original: Original DataFrame
        df_clean: Cleaned DataFrame
    """
    print("=" * 80)
    print("COLUMN NAME MAPPING")
    print("=" * 80)
    print(f"\n{'Original Column':<40} → {'Clean Column':<30}")
    print("-" * 80)

    for old_col, new_col in WU_COLUMN_MAPPING.items():
        if old_col in df_original.columns:
            marker = "✅" if new_col in df_clean.columns else "❌"
            print(f"{marker} {old_col:<38} → {new_col:<30}")

    print("\n" + "=" * 80)
    print(f"Total columns: {len(df_original.columns)} → {len(df_clean.columns)}")
    print("=" * 80)


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    """
    Example usage:

    # Convert columns
    df_clean = convert_wu_columns(df)

    # Create metadata
    metadata = create_metadata_df(df_clean)

    # Show comparison
    print_column_comparison(df, df_clean)
    """
    pass