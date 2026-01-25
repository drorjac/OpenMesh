"""
Shared Configuration for fetch_data
===================================

Defines common paths, settings, and STANDARDIZED OUTPUT FORMAT for all fetch pipelines.

Usage:
    from config import PROJECT_ROOT, OUTPUT_DIRS, STANDARD_COLUMNS
    
    OUTPUT_DIR = OUTPUT_DIRS['asos']

================================================================================
STANDARDIZED OUTPUT FORMAT
================================================================================

Both ASOS and Weather Underground pipelines output data with CONSISTENT:
- Column names (shared across sources)
- Units (metric SI)
- Time format (UTC datetime)

STANDARD COLUMNS (after processing):
------------------------------------
| Column          | Unit    | Description                          | ASOS | WU  |
|-----------------|---------|--------------------------------------|------|-----|
| datetime        | UTC     | Timestamp (timezone-aware)           | ✓    | ✓   |
| station_id      | -       | Station identifier                   | ✓    | ✓   |
| temperature     | °C      | Air temperature                      | ✓    | ✓   |
| dewpoint        | °C      | Dew point temperature                | ✓    | ✓   |
| wind_speed      | m/s     | Wind speed                           | ✓    | ✓   |
| wind_direction  | degrees | Wind direction (0-360)               | ✓    | ✓   |
| wind_gust       | m/s     | Wind gust speed                      | ✓    | ✓   |
| precip_amount   | mm      | Precipitation total/accumulated      | ✓    | ✓   |
| precip_rate     | mm/hr   | Precipitation rate (intensity)       | -    | ✓   |
| humidity        | %       | Relative humidity                    | -    | ✓   |
| pressure        | hPa/mb  | Atmospheric pressure                 | -    | ✓   |
| precip_type     | -       | Precipitation type (rain/snow/etc)   | ✓    | -   |

TIME RESOLUTION:
----------------
- ASOS: 1-minute native, can resample to any interval
- WU:   Variable (~5-15 min), hourly aggregates available

NOTES:
------
- All temperatures in Celsius (converted from °F if needed)
- All wind speeds in m/s (converted from knots or km/h)
- All precipitation in mm (converted from inches)
- Timestamps are UTC-aware datetime objects

================================================================================
"""

from pathlib import Path


def find_project_root():
    """
    Find project root by looking for parent directory containing both 'src' and 'dataset'.
    Uses __file__ location first (more reliable), then falls back to cwd.
    
    Returns
    -------
    Path
        Project root directory
    """
    # Method 1: Use this config file's location (most reliable)
    # This file is at: <project_root>/src/fetch_data/config.py
    config_file = Path(__file__).resolve()
    project_root_from_file = config_file.parent.parent.parent
    
    if (project_root_from_file / 'dataset').exists() and (project_root_from_file / 'src').exists():
        return project_root_from_file
    
    # Method 2: Search from current working directory
    current_dir = Path.cwd()
    for parent in [current_dir] + list(current_dir.parents):
        if (parent / 'dataset').exists() and (parent / 'src').exists():
            return parent
    
    # Fallback: look for 'dataset' directory only
    for parent in [current_dir] + list(current_dir.parents):
        if (parent / 'dataset').exists():
            return parent
    
    # Last resort: assume current directory is project root
    return current_dir


# Find project root
PROJECT_ROOT = find_project_root()


# =============================================================================
# STANDARDIZED COLUMN DEFINITIONS
# =============================================================================
# These are the agreed-upon column names for processed output data.
# Both ASOS and WU pipelines should output data using these names.

STANDARD_COLUMNS = {
    # Time & Location
    'datetime': {'unit': 'UTC', 'description': 'Timestamp (timezone-aware)'},
    'station_id': {'unit': '-', 'description': 'Station identifier'},
    'latitude': {'unit': 'degrees', 'description': 'Station latitude'},
    'longitude': {'unit': 'degrees', 'description': 'Station longitude'},
    
    # Temperature (°C)
    'temperature': {'unit': '°C', 'description': 'Air temperature'},
    'dewpoint': {'unit': '°C', 'description': 'Dew point temperature'},
    
    # Wind (m/s, degrees)
    'wind_speed': {'unit': 'm/s', 'description': 'Wind speed'},
    'wind_direction': {'unit': 'degrees', 'description': 'Wind direction (0-360)'},
    'wind_gust': {'unit': 'm/s', 'description': 'Wind gust speed'},
    
    # Precipitation (mm)
    'precip_amount': {'unit': 'mm', 'description': 'Precipitation total/accumulated'},
    'precip_rate': {'unit': 'mm/hr', 'description': 'Precipitation rate (intensity)'},
    'precip_type': {'unit': '-', 'description': 'Type: dry/rain/snow/precip/missing'},
    
    # Other
    'humidity': {'unit': '%', 'description': 'Relative humidity'},
    'pressure': {'unit': 'hPa', 'description': 'Atmospheric pressure'},
}

# =============================================================================
# DATASET FOLDER STRUCTURE
# =============================================================================
# dataset/
# ├── archived/             # Downloaded zips ONLY
# │   └── openmesh/
# ├── examples/             # Notebooks
# ├── meta/                 # ALL metadata CSVs
# │   ├── maps/
# │   └── openmesh/         # OpenMesh-specific metadata
# └── raw/                  # All raw data
#     ├── fetched/          # API fetched data
#     │   ├── asos/
#     │   └── wu/
#     └── openmesh/         # Extracted OpenMesh raw data (NetCDF)

# Base dataset paths
DATASET_DIR = PROJECT_ROOT / 'dataset'
ARCHIVED_DIR = DATASET_DIR / 'archived'
EXAMPLES_DIR = DATASET_DIR / 'examples'
META_DIR = DATASET_DIR / 'meta'
RAW_DIR = DATASET_DIR / 'raw'

# Output directories
OUTPUT_DIRS = {
    # Fetched data (API)
    'asos': RAW_DIR / 'fetched' / 'asos',
    'wu': RAW_DIR / 'fetched' / 'wu',
    # OpenMesh
    'openmesh_raw': RAW_DIR / 'openmesh',
    'openmesh_meta': META_DIR / 'openmesh',
    'openmesh_archived': ARCHIVED_DIR / 'openmesh',
    # General
    'meta': META_DIR,
    'examples': EXAMPLES_DIR,
}

# Backwards compatibility alias
OUTPUT_DIRS['wu_pws'] = OUTPUT_DIRS['wu']
OUTPUT_DIRS['openmesh'] = OUTPUT_DIRS['openmesh_raw']  # Legacy

# Ensure output directories exist
for output_dir in OUTPUT_DIRS.values():
    output_dir.mkdir(parents=True, exist_ok=True)


def get_output_dir(source: str, fetch_location: str = 'dataset') -> Path:
    """
    Get output directory for saving fetched data.
    
    Parameters
    ----------
    source : str
        Data source: 'asos', 'wu', 'openmesh', or 'meta'
    fetch_location : str, default 'dataset'
        Where to save data:
        - 'dataset': Save to main dataset folder (PROJECT_ROOT/dataset/raw/fetched/<source>/)
        - 'current': Save to current working directory
    
    Returns
    -------
    Path
        Output directory path (created if doesn't exist)
    
    Examples
    --------
    >>> output_dir = get_output_dir('asos')  # Default: dataset folder
    >>> output_dir = get_output_dir('asos', fetch_location='current')  # Current dir
    """
    if fetch_location == 'current':
        output_dir = Path.cwd() / source
    else:
        # Default: use main dataset folder
        if source not in OUTPUT_DIRS:
            raise ValueError(f"Unknown source: {source}. Use: {list(OUTPUT_DIRS.keys())}")
        output_dir = OUTPUT_DIRS[source]
    
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


if __name__ == '__main__':
    print(f"Project root: {PROJECT_ROOT}")
    print(f"\nDataset structure:")
    print(f"  meta: {META_DIR}")
    print(f"  raw:  {RAW_DIR}")
    print(f"\nOutput directories:")
    for name, path in OUTPUT_DIRS.items():
        if name not in ['wu_pws', 'openmesh']:  # Skip aliases
            print(f"  {name}: {path}")