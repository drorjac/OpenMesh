# Data Analysis Pipeline

## File Organization

```
analysis/
├── pipeline.py          # All data operations (fetch + load + process)
├── plotting.py          # All visualization functions
├── analysis_functions.py  # Rain detection and analysis functions
├── analysis_complete.ipynb  # Main end-to-end analysis notebook
└── README.md           # This file
```

## What Changed?

### Before (Confusing):
- `data_loader.py` - fetch and load functions
- `load_data.py` - OpenMesh loading functions  
- Two files with "load" in the name - confusing!

### After (Clean):
- `pipeline.py` - ONE module with ALL data operations
- `plotting.py` - kept as is, all visualization
- `analysis_functions.py` - modular rain detection and analysis functions
- `analysis_complete.ipynb` - clean end-to-end notebook

## What's in `pipeline.py`?

Complete data pipeline in one place:

### 1. Fetch Operations (from APIs)
```python
from analysis.pipeline import fetch_asos_data, fetch_wu_data

# Fetch from APIs
asos_data, date_range = fetch_asos_data(['JFK', 'LGA'], start_date, end_date)
wu_data, date_range = fetch_wu_data(station_list, start_date, end_date)
```

### 2. Load Operations (from files)
```python
from analysis.pipeline import load_all_datasets

# Load everything from files
datasets = load_all_datasets()
# Returns: asos, wu, openmesh_cml, openmesh_pws, metadata
```

### 3. Processing & Conversion
```python
from analysis.pipeline import prepare_analysis_data

# Prepare unified analysis data
analysis_data = prepare_analysis_data(datasets, parameters='all')
# Returns: structured dict with 'cml', 'pws', 'asos' data
```

### 4. Helper Functions
```python
from analysis.pipeline import (
    load_openmesh_cml,      # Load CML NetCDF
    load_pws_from_netcdf,   # Load PWS NetCDF
    extract_pws_rainfall,   # Extract single PWS station
    extract_all_pws_rainfall, # Extract all PWS stations
    get_default_paths,      # Get default directory paths
    map_all_sensors         # Create map visualization
)
```

## What's in `analysis_functions.py`?

Modular functions for rain detection and analysis:

### 1. CML Data Preparation
```python
from analysis.analysis_functions import prepare_cml_data_for_detection

# Prepare CML data with baseline calculation
df_cml_rsl = prepare_cml_data_for_detection(
    analysis_data, 
    cml_id='1', 
    sublink_id='sublink_1',
    window='6h',              # Time-based window: '3h', '6h', '12h', '30min'
    baseline_method='max'     # 'max' (default), 'quantile', or 'mean'
)
```

**Baseline Methods:**
- `'max'` (default): Rolling maximum - safest, always positive attenuation
- `'quantile'`: High percentile (e.g., 99th) - adaptive to signal variations
- `'mean'`: Rolling mean - original method, can give negative attenuation

### 2. Rain Detection - Rolling Standard Deviation
```python
from analysis.analysis_functions import detect_rain_rolling_std

# Simple mode: Fixed threshold
df_detection = detect_rain_rolling_std(
    df_cml_rsl,
    window_size=36,          # Rolling window (36 = 3 hours at 5-min intervals)
    threshold_std=1.0,        # Fixed threshold in dB
    resample_freq='5min',
    verbose=True
)

# Dynamic mode: Quantile-based threshold (in plotting.py)
from analysis.plotting import detect_rain_rolling_std as detect_rain_dynamic

df_detection = detect_rain_dynamic(
    df_cml_rsl,
    window_size=36,
    threshold=1.0,            # Fallback if dynamic fails
    use_dynamic_threshold=True,  # Enable dynamic mode
    threshold_window=72,      # Window for threshold calculation (6 hours)
    threshold_quantile=0.95,  # 95th percentile threshold
    resample_freq='5min',
    verbose=True
)
```

### 3. Ground Truth Rainfall Preparation
```python
from analysis.analysis_functions import (
    prepare_ground_truth_rainfall,
    prepare_combined_ground_truth
)

# Get separate PWS and ASOS rainfall
df_pws, df_asos = prepare_ground_truth_rainfall(
    analysis_data,
    matched_pws=['station1', 'station2'],
    matched_asos=['JFK', 'LGA'],
    rainfall_source='both'  # 'pws_mean', 'asos_mean', or 'both'
)

# Get combined rainfall
df_rain_combined = prepare_combined_ground_truth(
    analysis_data,
    matched_pws=['station1', 'station2'],
    matched_asos=['JFK', 'LGA'],
    rainfall_source='both'
)
```

### 4. Link Filtering and Selection
```python
from analysis.analysis_functions import (
    filter_links_by_features,
    select_link_group,
    match_links_to_pws,
    calculate_db_per_km_for_links
)

# Filter links by length and frequency
filtered_links, filtered_pairs = filter_links_by_features(
    links_metadata,
    min_length=1000,    # meters
    max_length=5000,    # meters
    min_freq=5000,      # MHz
    max_freq=80000      # MHz
)

# Select a group of links
selected_pairs = select_link_group(
    filtered_pairs,
    select_mode='first_n',  # 'first_n', 'all', or 'specific'
    n_links=10
)

# Match links to PWS stations
cml_to_pws = match_links_to_pws(
    selected_pairs,
    filtered_links,
    pws_metadata,
    max_distance_km=5.0
)
```

### 5. Scatter Plot Analysis
```python
from analysis.analysis_functions import create_scatter_plot_db_vs_rainfall

# Calculate dB/km for selected links
link_data_dict = calculate_db_per_km_for_links(
    analysis_data,
    selected_pairs,
    filtered_links,
    sampling_interval='10min',
    window_3h=36
)

# Create scatter plot
create_scatter_plot_db_vs_rainfall(
    link_data_dict,
    df_pws_rain_mean,
    df_asos_rain_mean,
    rainfall_source='both',  # 'pws_mean', 'asos_mean', or 'both'
    selected_pairs=selected_pairs,
    sampling_interval='10min'
)
```

## Plotting Functions

All visualization functions are in `plotting.py`:

### Basic Plotting
```python
from analysis.plotting import (
    plot_all_datasets,           # Plot CML + PWS + ASOS together
    plot_cml_rsl_attenuation,   # Plot CML RSL and attenuation
    plot_rain_detection,        # Plot rain detection results
    plot_weather_subplots,      # Plot multiple weather parameters
    plot_links_scatter,         # Scatter plot of link characteristics
    plot_weather_params         # Plot weather parameters with outlier handling
)
```

### Enhanced Detection Plotting
```python
from analysis.plotting import (
    plot_rolling_baseline_detection,  # RSL, rolling std, PWS/ASOS with detections
    plot_detection_with_periods        # Enhanced plotting with period highlighting
)

# Rolling baseline detection plot
plot_rolling_baseline_detection(
    df_cml_rsl=df_cml_plot,
    df_pws=df_pws_plot,
    df_asos=df_asos_plot,
    df_detection=df_rolling_result,
    selected_link_id="1 - sublink_1",
    window_size=36,
    threshold_quantile=0.95,  # 95th percentile threshold
    start_date=None,
    end_date=None
)

# Enhanced detection with period highlighting
plot_detection_with_periods(
    df_cml_rsl=df_cml_rsl,
    df_detection=df_detection,
    df_pws=df_pws,
    df_asos=df_asos,
    selected_link_id="1 - sublink_1",
    highlight_detection_periods=True
)
```

### Map Visualization
```python
from analysis.pipeline import map_all_sensors

# Create map showing selected sensors
fig, ax = map_all_sensors(
    links_meta=links_meta,
    asos_meta=asos_metadata,
    pws_meta=pws_metadata,
    cml_ids=['1', '2', '5'],              # Filter by CML IDs
    pws_station_ids=['station1', 'station2'],  # Filter by PWS stations
    asos_station_ids=['JFK', 'LGA'],     # Filter by ASOS stations
    map_type='matplotlib',               # 'matplotlib' or 'folium'
    show_link_labels=True
)
```

## How to Use `analysis_complete.ipynb`

The notebook provides a complete end-to-end workflow:

1. Setup - Import modules and configure paths
2. Load Data - Load ASOS, WU, OpenMesh datasets
3. Prepare Analysis Data - Convert to unified format
4. Select CML Link - Choose link and get matched stations
5. Rain Detection - Run rolling std detection method
6. Visualization - Plot results with detection marks
7. Scatter Analysis - dB/km vs rainfall analysis
8. Save Results - Export if needed

### Quick Start

```python
# 1. Load all available data
from analysis.pipeline import load_all_datasets, prepare_analysis_data

datasets = load_all_datasets()
analysis_data = prepare_analysis_data(datasets, parameters='all')

# 2. Select CML link and prepare data
from analysis.analysis_functions import prepare_cml_and_matched_stations

SELECTED_CML_ID = '1'
SELECTED_SUBLINK_ID = 'sublink_1'

df_cml_rsl, matched_pws, matched_asos = prepare_cml_and_matched_stations(
    analysis_data, SELECTED_CML_ID, SELECTED_SUBLINK_ID
)

# 3. Run detection
from analysis.analysis_functions import detect_rain_rolling_std

df_detection = detect_rain_rolling_std(
    df_cml_rsl, 
    window_size=36, 
    threshold_std=1.0, 
    resample_freq='5min'
)

# 4. Plot results
from analysis.plotting import plot_rolling_baseline_detection

plot_rolling_baseline_detection(
    df_cml_rsl=df_cml_rsl,
    df_pws=df_pws_plot,
    df_asos=df_asos_plot,
    df_detection=df_detection,
    selected_link_id=f"{SELECTED_CML_ID} - {SELECTED_SUBLINK_ID}",
    threshold_quantile=0.95
)
```

## Key Features

### Baseline Calculation Methods

The `prepare_cml_data_for_detection` function supports three baseline methods:

1. **Max Method (default)**: Rolling maximum
   - Always produces positive attenuation
   - Best for detecting rain events
   - Window: time-based string (e.g., '6h', '3h', '12h')

2. **Quantile Method**: High percentile (99th)
   - Adaptive to signal variations
   - Good for noisy signals
   - Window: time-based string

3. **Mean Method**: Rolling mean
   - Original method
   - Can produce negative attenuation
   - Window: time-based string

### Rain Detection Methods

1. **Rolling Standard Deviation (Simple)**
   - Fixed threshold (e.g., 1.0 dB)
   - Rain detected when: rolling_std > threshold
   - Fast and simple

2. **Rolling Standard Deviation (Dynamic)**
   - Quantile-based threshold
   - Threshold adapts to local conditions
   - Rain detected when: rolling_std > dynamic_threshold
   - More adaptive to varying signal conditions

### Detection Visualization

The plotting functions provide:
- RSL and baseline plots
- Rolling std with threshold line
- Attenuation visualization
- PWS and ASOS rainfall with detection marks
- Period highlighting for continuous detections

## Function Reference

### Pipeline Functions (`pipeline.py`)

**Fetch Functions:**
- `fetch_asos_data(stations, start_date, end_date)` → (data_dict, date_range)
- `fetch_wu_data(stations, start_date, end_date, units='m')` → (data_dict, date_range)
- `check_wu_api_key()` → api_key or None

**Load Functions:**
- `load_all_datasets(output_dirs, select_asos_date_range, select_wu_date_range)` → datasets dict
- `load_asos_from_files(output_dir, date_range)` → (data_dict, date_range)
- `load_wu_from_files(output_dir, date_range)` → (data_dict, date_range)
- `load_openmesh_cml(cml_file, metadata_file)` → (xr.Dataset, metadata_df)
- `load_pws_from_netcdf(pws_file)` → {station_id: xr.Dataset}

**Processing Functions:**
- `prepare_analysis_data(datasets, parameters, analysis_period)` → analysis_data dict
- `extract_pws_rainfall(pws_data, station_id)` → DataFrame
- `extract_all_pws_rainfall(pws_data, station_ids)` → DataFrame

**Utility Functions:**
- `get_default_paths()` → paths dict
- `map_all_sensors(...)` → map visualization
- `discover_available_parameters(data, source_type)` → parameter mapping

### Analysis Functions (`analysis_functions.py`)

**Data Preparation:**
- `prepare_cml_data_for_detection(analysis_data, cml_id, sublink_id, window, baseline_method)` → DataFrame
- `prepare_cml_and_matched_stations(analysis_data, cml_id, sublink_id, cml_to_pws)` → (DataFrame, list, list)
- `prepare_ground_truth_rainfall(analysis_data, matched_pws, matched_asos, rainfall_source)` → (DataFrame, DataFrame)
- `prepare_combined_ground_truth(analysis_data, matched_pws, matched_asos, rainfall_source)` → DataFrame

**Rain Detection:**
- `detect_rain_rolling_std(df_cml_rsl, window_size, threshold_std, resample_freq, verbose)` → DataFrame

**Link Analysis:**
- `filter_links_by_features(links_metadata, min_length, max_length, min_freq, max_freq)` → (DataFrame, list)
- `select_link_group(filtered_pairs, select_mode, selected_cml_ids, n_links)` → list
- `match_links_to_pws(selected_pairs, filtered_links, pws_metadata, max_distance_km)` → dict
- `calculate_db_per_km_for_links(analysis_data, selected_pairs, filtered_links, sampling_interval)` → dict
- `create_scatter_plot_db_vs_rainfall(link_data_dict, df_pws_rain_mean, df_asos_rain_mean, ...)` → None

### Plotting Functions (`plotting.py`)

**Basic Plotting:**
- `plot_all_datasets(df_cml, df_pws, df_asos, selected_link_id, ...)` → None
- `plot_cml_rsl_attenuation(df_cml, df_rain, selected_link_id, rain_source)` → None
- `plot_weather_params(analysis_data, parameter, mode, ...)` → figure, axes
- `plot_links_scatter(links_meta, x_param, y_param, ...)` → figure, axes

**Detection Plotting:**
- `plot_rolling_baseline_detection(df_cml_rsl, df_pws, df_asos, df_detection, ...)` → None
- `plot_detection_with_periods(df_cml_rsl, df_detection, df_pws, df_asos, ...)` → None

## Design Principles

1. **Modular** - Functions in .py files, not in notebooks
2. **Clear naming** - Functions describe what they do
3. **End-to-end** - Complete pipeline from fetch to analysis
4. **Well-organized** - One file per purpose
5. **Easy to use** - Simple imports, clear functions
6. **Flexible** - Multiple baseline and detection methods

## Migration from Old Files

If you have existing notebooks using the old structure:

**Old imports:**
```python
from analysis.data_loader import fetch_asos_data, load_all_datasets
from analysis.load_data import load_openmesh_cml, extract_pws_rainfall
```

**New imports (same functions, one module):**
```python
from analysis.pipeline import (
    fetch_asos_data, 
    load_all_datasets,
    load_openmesh_cml, 
    extract_pws_rainfall
)
```

## Example Workflow

```python
# 1. Load all available data
from analysis.pipeline import load_all_datasets, prepare_analysis_data

datasets = load_all_datasets()
analysis_data = prepare_analysis_data(datasets, parameters='all')

# 2. Select CML link and prepare detection data
from analysis.analysis_functions import (
    prepare_cml_and_matched_stations,
    prepare_combined_ground_truth,
    detect_rain_rolling_std
)

SELECTED_CML_ID = '1'
SELECTED_SUBLINK_ID = 'sublink_1'

df_cml_rsl, matched_pws, matched_asos = prepare_cml_and_matched_stations(
    analysis_data, SELECTED_CML_ID, SELECTED_SUBLINK_ID
)

df_rain_gt = prepare_combined_ground_truth(
    analysis_data, matched_pws, matched_asos, 'both'
)

# 3. Run detection
df_detection = detect_rain_rolling_std(
    df_cml_rsl, window_size=36, threshold_std=1.0, resample_freq='5min'
)

# 4. Visualize
from analysis.plotting import plot_rolling_baseline_detection

plot_rolling_baseline_detection(
    df_cml_rsl=df_cml_rsl,
    df_pws=df_pws_plot,
    df_asos=df_asos_plot,
    df_detection=df_detection,
    selected_link_id=f"{SELECTED_CML_ID} - {SELECTED_SUBLINK_ID}",
    threshold_quantile=0.95
)
```

---

For complete working examples, check `analysis_complete.ipynb`!
