"""
Helper functions to load OpenMesh datasets.

This module provides functions to load:
1. OpenMesh CML (Commercial Microwave Links) data
2. PWS (Personal Weather Stations) data
3. NOAA ASOS (Automated Surface Observing System) data
4. Rain detection from CML attenuation data
"""

import xarray as xr
import pandas as pd
import numpy as np
import netCDF4 as nc
from pathlib import Path
from typing import Dict, Optional, Union, Tuple


# Default paths relative to this file
BASE_DIR = Path(__file__).parent.parent.parent
DATASET_DIR = BASE_DIR / "dataset"
LINKS_DIR = DATASET_DIR / "links"
WEATHER_STATIONS_DIR = DATASET_DIR / "weather stations"
# Alternative path: extracted dataset from Zenodo
EXTRACTED_WEATHER_STATIONS_DIR = BASE_DIR / "src" / "data" / "openmesh" / "extracted" / "dataset" / "weather stations"


def load_openmesh_cml(
    cml_file: Optional[Union[str, Path]] = None,
    metadata_file: Optional[Union[str, Path]] = None
) -> Tuple[xr.Dataset, pd.DataFrame]:
    """
    Load OpenMesh CML (Commercial Microwave Links) dataset.
    
    Parameters
    ----------
    cml_file : str or Path, optional
        Path to ds_openmesh.nc file. If None, uses default location.
    metadata_file : str or Path, optional
        Path to links_metadata.csv file. If None, uses default location.
    
    Returns
    -------
    ds_cml : xarray.Dataset
        CML dataset with RSL (Received Signal Level) data
    df_metadata : pandas.DataFrame
        Link metadata (coordinates, frequency, polarization, etc.)
    
    Examples
    --------
    >>> ds_cml, df_metadata = load_openmesh_cml()
    >>> print(ds_cml)
    >>> print(df_metadata.head())
    """
    # Set default paths
    if cml_file is None:
        cml_file = LINKS_DIR / "ds_openmesh.nc"
    else:
        cml_file = Path(cml_file)
    
    if metadata_file is None:
        metadata_file = LINKS_DIR / "links_metadata.csv"
    else:
        metadata_file = Path(metadata_file)
    
    # Load CML dataset
    if not cml_file.exists():
        raise FileNotFoundError(f"CML file not found: {cml_file}")
    
    print(f"Loading OpenMesh CML data from: {cml_file}")
    ds_cml = xr.open_dataset(cml_file)
    
    print(f"  ✓ Loaded CML dataset:")
    print(f"    Links: {len(ds_cml.cml_id)}")
    print(f"    Time range: {pd.to_datetime(ds_cml.time.values[0])} to {pd.to_datetime(ds_cml.time.values[-1])}")
    print(f"    Time points: {len(ds_cml.time):,}")
    
    # Load metadata
    df_metadata = None
    if metadata_file.exists():
        df_metadata = pd.read_csv(metadata_file)
        print(f"  ✓ Loaded metadata: {len(df_metadata)} sublinks")
    else:
        print(f"  ⚠ Metadata file not found: {metadata_file}")
        df_metadata = pd.DataFrame()
    
    return ds_cml, df_metadata


def load_pws_data(
    pws_file: Optional[Union[str, Path]] = None,
    source: str = 'full'
) -> Dict[str, xr.Dataset]:
    """
    Load PWS (Personal Weather Stations) data from NetCDF files.
    
    This function automatically searches for files in two locations:
    1. `dataset/weather stations/` (recommended - extract files here)
    2. `src/data/openmesh/extracted/dataset/weather stations/` (from Zenodo extraction)
    
    Parameters
    ----------
    pws_file : str or Path, optional
        Path to PWS NetCDF file. If None, searches default locations based on source.
    source : str, optional
        Data source: 'full' (default) or 'sample'
        - 'full': Load from full NetCDF file (all periods: Oct 2023 - Jul 2024)
        - 'sample': Load sample NetCDF data (2 weeks: Jan 15-30, 2024)
    
    Returns
    -------
    pws_data : dict
        Dictionary mapping station_id to xarray.Dataset for each station
    
    Notes
    -----
    **File Locations:**
    - **Recommended**: Extract files from Zenodo to `dataset/weather stations/`
    - **Alternative**: Use files directly from `src/data/openmesh/extracted/dataset/weather stations/`
      (if you extracted the Zenodo archive there)
    
    **Sample vs Full:**
    - Sample: `pws_opensense_sample_jan.nc` - 2 weeks (Jan 15-30, 2024)
    - Full: `pws_opensense_os.nc` - Complete dataset (Oct 2023 - Jul 2024)
    
    Examples
    --------
    >>> # Load full NetCDF dataset (default)
    >>> pws_data = load_pws_data(source='full')
    
    >>> # Load sample NetCDF data
    >>> pws_data = load_pws_data(source='sample')
    """
    if source == 'sample':
        return load_pws_sample_data(pws_file)
    else:  # 'full' or default
        return load_pws_from_netcdf(pws_file)


def load_pws_from_netcdf(
    pws_file: Optional[Union[str, Path]] = None
) -> Dict[str, xr.Dataset]:
    """
    Load PWS (Personal Weather Stations) data from grouped NetCDF file.
    
    This function looks for the full dataset NetCDF file in two locations:
    1. `dataset/weather stations/` (recommended - extract files here)
    2. `src/data/openmesh/extracted/dataset/weather stations/` (from Zenodo extraction)
    
    Parameters
    ----------
    pws_file : str or Path, optional
        Path to PWS NetCDF file. If None, searches default locations:
        - `dataset/weather stations/pws_opensense_os.nc` (full dataset)
        - `src/data/openmesh/extracted/dataset/weather stations/pws_opensense_os.nc` (extracted)
    
    Returns
    -------
    pws_data : dict
        Dictionary mapping station_id to xarray.Dataset for each station
    
    Notes
    -----
    **File Locations:**
    - **Recommended**: Extract files from Zenodo to `dataset/weather stations/`
    - **Alternative**: Use files directly from `src/data/openmesh/extracted/dataset/weather stations/`
      (if you extracted the Zenodo archive there)
    """
    # Set default path
    if pws_file is None:
        # Try primary location first, then extracted location
        search_paths = [
            (WEATHER_STATIONS_DIR, "pws_opensense_os.nc"),
            (WEATHER_STATIONS_DIR, "pws.nc"),
            (EXTRACTED_WEATHER_STATIONS_DIR, "pws_opensense_os.nc"),
            (EXTRACTED_WEATHER_STATIONS_DIR, "pws.nc"),
        ]
        
        for base_dir, filename in search_paths:
            candidate = base_dir / filename
            if candidate.exists():
                pws_file = candidate
                break
        
        if pws_file is None:
            tried_paths = "\n".join([f"  - {base_dir / filename}" for base_dir, filename in search_paths])
            raise FileNotFoundError(
                f"Full PWS NetCDF file not found. Tried:\n{tried_paths}\n\n"
                f"**Solution:** Extract files from Zenodo to `dataset/weather stations/` or "
                f"use the extracted path `src/data/openmesh/extracted/dataset/weather stations/`"
            )
    else:
        pws_file = Path(pws_file)
    
    if not pws_file.exists():
        raise FileNotFoundError(f"PWS file not found: {pws_file}")
    
    print(f"Loading FULL PWS data from NetCDF: {pws_file}")
    
    # Open NetCDF file to get groups
    nc_file = nc.Dataset(pws_file, 'r')
    station_ids = list(nc_file.groups.keys())
    nc_file.close()
    
    print(f"  Found {len(station_ids)} stations")
    
    # Load each station as xarray dataset
    pws_data = {}
    for station_id in station_ids:
        try:
            station_ds = xr.open_dataset(pws_file, group=station_id, engine='netcdf4')
            pws_data[station_id] = station_ds
            print(f"    ✓ {station_id}: {len(station_ds.time)} records")
        except Exception as e:
            print(f"    ✗ {station_id}: Error - {e}")
    
    print(f"  ✓ Loaded {len(pws_data)} PWS stations")
    
    return pws_data


def load_pws_from_csv(
    csv_dir: Optional[Union[str, Path]] = None
) -> Dict[str, xr.Dataset]:
    """
    Load PWS data from CSV files exported by wu_pipeline notebook.
    
    Converts CSV format to xarray.Dataset format matching the NetCDF structure.
    
    Parameters
    ----------
    csv_dir : str or Path, optional
        Directory containing CSV files. If None, searches in src/data/wu_pws/
    
    Returns
    -------
    pws_data : dict
        Dictionary mapping station_id to xarray.Dataset for each station
    """
    # Set default directory
    if csv_dir is None:
        csv_dir = BASE_DIR / "src" / "data" / "wu_pws"
    else:
        csv_dir = Path(csv_dir)
    
    if not csv_dir.exists():
        raise FileNotFoundError(f"CSV directory not found: {csv_dir}")
    
    print(f"Loading PWS data from CSV files: {csv_dir}")
    
    # Find all precipitation CSV files
    precip_files = list(csv_dir.glob("precipitation_*.csv"))
    if len(precip_files) == 0:
        raise FileNotFoundError(f"No precipitation CSV files found in {csv_dir}")
    
    print(f"  Found {len(precip_files)} CSV files")
    
    pws_data = {}
    
    for csv_file in precip_files:
        try:
            # Extract station ID from filename (format: precipitation_STATIONID_DATE.csv)
            filename = csv_file.stem  # Remove .csv extension
            parts = filename.split('_')
            if len(parts) >= 2:
                station_id = parts[1]  # Second part is station ID
            else:
                print(f"    ⚠ Could not parse station ID from {csv_file.name}, skipping...")
                continue
            
            # Read CSV
            df = pd.read_csv(csv_file)
            
            # Convert time_local to datetime
            if 'time_local' in df.columns:
                df['time'] = pd.to_datetime(df['time_local'])
            elif 'time' in df.columns:
                df['time'] = pd.to_datetime(df['time'])
            else:
                print(f"    ⚠ No time column found in {csv_file.name}, skipping...")
                continue
            
            # Set time as index
            df.set_index('time', inplace=True)
            df = df.sort_index()
            
            # Convert precipitation columns to mm
            # Prefer precip_total (already in mm), otherwise convert precip_rate (mm/h) to mm
            if 'precip_total' in df.columns:
                # Use total precipitation (already in mm per interval)
                precip_mm = df['precip_total'].values
            elif 'precip_rate' in df.columns:
                # Convert rate (mm/h) to amount (mm) based on actual time intervals
                # Calculate time differences in hours
                time_diffs = df.index.to_series().diff().dt.total_seconds() / 3600.0
                # Fill first NaN with median interval (usually 1 hour for hourly data)
                median_interval = time_diffs.median()
                time_diffs = time_diffs.fillna(median_interval)
                # Convert rate to amount: rate (mm/h) * interval (h) = amount (mm)
                precip_mm = (df['precip_rate'].values * time_diffs.values)
            else:
                print(f"    ⚠ No precipitation column found in {csv_file.name}, skipping...")
                continue
            
            # Create xarray Dataset matching NetCDF structure
            time_coords = df.index.values
            station_ds = xr.Dataset({
                'rainfall_amount': (['time'], precip_mm),
                'time': (['time'], time_coords)
            }, coords={'time': time_coords})
            
            pws_data[station_id] = station_ds
            print(f"    ✓ {station_id}: {len(station_ds.time)} records")
            
        except Exception as e:
            print(f"    ✗ Error loading {csv_file.name}: {e}")
            continue
    
    print(f"  ✓ Loaded {len(pws_data)} PWS stations from CSV")
    
    return pws_data


def load_pws_sample_data(
    pws_file: Optional[Union[str, Path]] = None
) -> Dict[str, xr.Dataset]:
    """
    Load sample PWS data from NetCDF file (2-week sample: Jan 15-30, 2024).
    
    This function looks for the sample NetCDF file in two locations:
    1. `dataset/weather stations/` (recommended - extract files here)
    2. `src/data/openmesh/extracted/dataset/weather stations/` (from Zenodo extraction)
    
    Parameters
    ----------
    pws_file : str or Path, optional
        Path to sample PWS NetCDF file. If None, searches default locations:
        - `dataset/weather stations/pws_opensense_sample_jan.nc` (sample: 2 weeks)
        - `src/data/openmesh/extracted/dataset/weather stations/pws_opensense_sample_jan.nc` (extracted)
        Falls back to full dataset if sample not found.
    
    Returns
    -------
    pws_data : dict
        Dictionary mapping station_id to xarray.Dataset for each station
    
    Notes
    -----
    **File Locations:**
    - **Recommended**: Extract files from Zenodo to `dataset/weather stations/`
    - **Alternative**: Use files directly from `src/data/openmesh/extracted/dataset/weather stations/`
      (if you extracted the Zenodo archive there)
    
    **Sample vs Full:**
    - Sample: `pws_opensense_sample_jan.nc` - 2 weeks (Jan 15-30, 2024)
    - Full: `pws_opensense_os.nc` - Complete dataset (Oct 2023 - Jul 2024)
    """
    # Set default path for sample data
    if pws_file is None:
        # Try sample file in both locations, then fall back to full file
        search_paths = [
            (WEATHER_STATIONS_DIR, "pws_opensense_sample_jan.nc"),
            (EXTRACTED_WEATHER_STATIONS_DIR, "pws_opensense_sample_jan.nc"),
            (WEATHER_STATIONS_DIR, "pws_opensense_os.nc"),
            (EXTRACTED_WEATHER_STATIONS_DIR, "pws_opensense_os.nc"),
            (WEATHER_STATIONS_DIR, "pws.nc"),
            (EXTRACTED_WEATHER_STATIONS_DIR, "pws.nc"),
        ]
        
        for base_dir, filename in search_paths:
            candidate = base_dir / filename
            if candidate.exists():
                pws_file = candidate
                is_sample = "sample_jan" in filename
                if not is_sample:
                    print(f"  ⚠ Sample file not found, using full dataset: {pws_file.name}")
                break
        
        if pws_file is None:
            tried_paths = "\n".join([f"  - {base_dir / filename}" for base_dir, filename in search_paths])
            raise FileNotFoundError(
                f"Sample PWS NetCDF file not found. Tried:\n{tried_paths}\n\n"
                f"**Solution:** Extract files from Zenodo to `dataset/weather stations/` or "
                f"use the extracted path `src/data/openmesh/extracted/dataset/weather stations/`"
            )
    else:
        pws_file = Path(pws_file)
    
    if not pws_file.exists():
        raise FileNotFoundError(f"Sample PWS file not found: {pws_file}")
    
    print(f"Loading SAMPLE PWS data from NetCDF: {pws_file}")
    
    # Use the same loading logic as full dataset
    return load_pws_from_netcdf(pws_file)


def load_noaa_asos(
    asos_dir: Optional[Union[str, Path]] = None,
    station_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    mode: str = 'load',
    stations: Optional[list] = None,
    resolution: str = '5min'
) -> Optional[pd.DataFrame]:
    """
    Load NOAA ASOS data from existing CSV files.
    Optionally fetch data from API if not found.
    
    Parameters
    ----------
    asos_dir : str or Path, optional
        Directory containing ASOS CSV files. If None, searches in common locations.
    station_id : str, optional
        Station ID (e.g., 'KNYC'). If None, loads all stations from file.
    start_date : str, optional
        Start date in 'YYYYMMDD' format for filename matching.
    end_date : str, optional
        End date in 'YYYYMMDD' format for filename matching.
    mode : str, optional
        Operation mode:
        - 'load': Only load from existing files (default)
        - 'fetch': Only fetch from API (don't load existing files)
        - 'auto': Load if exists, otherwise fetch from API
        Default: 'load'
    stations : list, optional
        Station IDs to fetch if mode='fetch' or 'auto'. 
        Default: ['KJFK', 'KLGA', 'KNYC']
    resolution : str, optional
        Data resolution for fetching ('5min' or 'hourly').
        Default: '5min'
    
    Returns
    -------
    df_asos : pandas.DataFrame or None
        ASOS data with datetime index. If multiple stations, one column per station (station_id as column name).
        If single station or no station_id column, returns single 'precip_mm' column.
    """
    # Search in common locations
    search_dirs = []
    
    if asos_dir is not None:
        search_dirs.append(Path(asos_dir))
    else:
        # Try common locations
        search_dirs.extend([
            BASE_DIR / "src" / "data" / "noaa_asos",
            BASE_DIR / "dataset" / "weather stations",
            BASE_DIR / "data" / "noaa_asos",
        ])
    
    # Find CSV files
    csv_files = []
    for search_dir in search_dirs:
        if Path(search_dir).exists():
            # Look for ASOS CSV files
            pattern = f"*{station_id}*" if station_id else "*.csv"
            csv_files.extend(list(Path(search_dir).glob(pattern)))
    
    # Helper function to fetch ASOS data from API
    def _fetch_asos_data(start_dt, end_dt, stations_list, res):
        """Internal function to fetch ASOS data from API"""
        try:
            from datetime import datetime
            import importlib.util
            import sys
            
            # Add project root to path if not already there
            project_root = BASE_DIR
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            
            # Try importing using the path
            try:
                from src.fetch_data.noaa_asos import asos_functions as asos
            except ImportError:
                # Fallback: use importlib to load from file path
                asos_functions_path = BASE_DIR / "src" / "fetch_data" / "noaa_asos" / "asos_functions.py"
                if not asos_functions_path.exists():
                    raise ImportError(f"ASOS functions file not found: {asos_functions_path}")
                
                spec = importlib.util.spec_from_file_location("asos_functions", asos_functions_path)
                asos = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(asos)
            
            print(f"\n🔄 Fetching ASOS data from IEM API...")
            print(f"   Period: {start_dt.date()} to {end_dt.date()}")
            print(f"   Stations: {stations_list}")
            print(f"   Resolution: {res}\n")
            
            # Fetch data
            raw_data = asos.fetch_all_stations(
                station_ids=stations_list,
                start_date=start_dt,
                end_date=end_dt,
                resolution=res,
                verbose=True
            )
            
            if len(raw_data) == 0:
                print(f"⚠ No data fetched from API")
                return False
            
            # Process data
            processed_data = asos.process_all_stations(raw_data, verbose=True)
            
            # Save to default location
            output_dir = BASE_DIR / "src" / "data" / "noaa_asos"
            asos.save_processed_data(
                processed_data, 
                output_dir, 
                start_dt, 
                end_dt, 
                res
            )
            
            print(f"✓ Data fetched and saved to: {output_dir}")
            return True
            
        except ImportError as e:
            print(f"⚠ Error importing ASOS functions: {e}")
            print(f"  → Please ensure src/fetch_data/noaa_asos/asos_functions.py exists")
            return False
        except Exception as e:
            print(f"⚠ Error during fetch: {e}")
            print(f"  → Please run: src/fetch_data/noaa_asos/asos_pipeline.ipynb manually")
            return False
    
    # Handle different modes
    if mode == 'fetch':
        # Only fetch, don't load existing files
        if not start_date or not end_date:
            print(f"⚠ Mode 'fetch' requires start_date and end_date")
            return None
        
        if stations is None:
            stations = ['KJFK', 'KLGA', 'KNYC']
        
        start_dt = pd.to_datetime(start_date, format='%Y%m%d')
        end_dt = pd.to_datetime(end_date, format='%Y%m%d')
        
        print(f"🔄 Mode 'fetch': Fetching new data (ignoring existing files)...")
        if _fetch_asos_data(start_dt, end_dt, stations, resolution):
            # After fetching, try loading
            print(f"✓ Fetch complete. Loading fetched data...")
            return load_noaa_asos(
                asos_dir=asos_dir,
                station_id=station_id,
                start_date=start_date,
                end_date=end_date,
                mode='load',  # Prevent infinite loop
                stations=stations,
                resolution=resolution
            )
        return None
    
    # For 'load' and 'auto' modes, try to find existing files first
    if mode not in ['load', 'auto']:
        print(f"⚠ Invalid mode '{mode}'. Using 'load' mode.")
        mode = 'load'
    if len(csv_files) == 0:
        if mode == 'load':
            # Load mode: just return None if no files found
            print(f"⚠ No ASOS CSV files found in search directories")
            return None
        elif mode == 'auto':
            # Auto mode: fetch if not found
            if not start_date or not end_date:
                print(f"⚠ No ASOS CSV files found and auto-fetch requires start_date and end_date")
                return None
            
            print(f"⚠ No ASOS CSV files found in search directories")
            print(f"🔄 Auto-fetching ASOS data...")
            
            if stations is None:
                stations = ['KJFK', 'KLGA', 'KNYC']
            
            start_dt = pd.to_datetime(start_date, format='%Y%m%d')
            end_dt = pd.to_datetime(end_date, format='%Y%m%d')
            
            if _fetch_asos_data(start_dt, end_dt, stations, resolution):
                # After fetching, try loading again
                return load_noaa_asos(
                    asos_dir=asos_dir,
                    station_id=station_id,
                    start_date=start_date,
                    end_date=end_date,
                    mode='load',  # Prevent infinite loop
                    stations=stations,
                    resolution=resolution
                )
            return None
    
    # Filter by date in filename if provided (helps find the right file)
    if start_date and end_date:
        try:
            req_start = pd.to_datetime(start_date, format='%Y%m%d')
            req_end = pd.to_datetime(end_date, format='%Y%m%d')
            
            # Try exact match first
            filtered = [f for f in csv_files if start_date in f.name and end_date in f.name]
            
            if not filtered:
                # If exact match not found, try to find file that contains the date range
                # Look for files where the file's date range contains the requested range
                for f in csv_files:
                    # Try to extract dates from filename (format: ALL_STATIONS_YYYYMMDD_YYYYMMDD_*.csv)
                    parts = f.stem.split('_')
                    for i, part in enumerate(parts):
                        if len(part) == 8 and part.isdigit():  # YYYYMMDD format
                            file_start = pd.to_datetime(part, format='%Y%m%d')
                            # Check if next part is also a date
                            if i + 1 < len(parts) and len(parts[i+1]) == 8 and parts[i+1].isdigit():
                                file_end = pd.to_datetime(parts[i+1], format='%Y%m%d')
                                # Check if file's date range contains requested range
                                if file_start <= req_start and file_end >= req_end:
                                    filtered.append(f)
                                    break
        except Exception as e:
            print(f"  ⚠ Warning: Error parsing dates for file selection: {e}")
            # Fall back to simple string matching
            filtered = [f for f in csv_files if start_date in f.name or end_date in f.name]
        
        if filtered:
            csv_files = filtered
            if len(csv_files) > 1:
                # Prefer files with exact date match, or files that contain the requested range
                # Sort by: exact match first, then by how well the range is contained
                def file_score(f):
                    name = f.name
                    # Exact match gets highest priority
                    if start_date in name and end_date in name:
                        return (0, name)
                    # Files containing the range get next priority
                    try:
                        parts = f.stem.split('_')
                        for i, part in enumerate(parts):
                            if len(part) == 8 and part.isdigit():
                                file_start = pd.to_datetime(part, format='%Y%m%d')
                                if i + 1 < len(parts) and len(parts[i+1]) == 8 and parts[i+1].isdigit():
                                    file_end = pd.to_datetime(parts[i+1], format='%Y%m%d')
                                    req_start = pd.to_datetime(start_date, format='%Y%m%d')
                                    req_end = pd.to_datetime(end_date, format='%Y%m%d')
                                    # Check if file contains the requested range
                                    if file_start <= req_start and file_end >= req_end:
                                        return (1, name)  # Contains range
                                    elif file_start <= req_start and file_end >= req_start:
                                        return (2, name)  # Overlaps at start
                                    elif file_start <= req_end and file_end >= req_end:
                                        return (3, name)  # Overlaps at end
                    except:
                        pass
                    return (4, name)  # No match
                csv_files.sort(key=file_score)
        else:
            print(f"  ℹ No files found with exact date match {start_date} to {end_date}")
            print(f"    Will try to filter data from available files...")
    
    # Use first matching file (or first available if no date match)
    csv_file = csv_files[0]
    if mode == 'load':
        print(f"✓ Found existing ASOS file: {csv_file.name}")
    elif mode == 'auto':
        print(f"✓ Found existing ASOS file: {csv_file.name}")
    print(f"Loading NOAA ASOS data from: {csv_file}")
    
    try:
        df_asos = pd.read_csv(csv_file)
        
        # Convert datetime column if present
        if 'datetime' in df_asos.columns:
            df_asos['time'] = pd.to_datetime(df_asos['datetime'])
            df_asos.set_index('time', inplace=True)
        elif 'time' in df_asos.columns:
            df_asos['time'] = pd.to_datetime(df_asos['time'])
            df_asos.set_index('time', inplace=True)
        else:
            print(f"  ⚠ Warning: No 'datetime' or 'time' column found in CSV")
            print(f"    Available columns: {list(df_asos.columns)}")
            return None
        
        # Store original date range for error messages
        original_date_range = (df_asos.index.min(), df_asos.index.max())
        
        # Filter data by date range if provided (after loading, before processing)
        if start_date and end_date:
            try:
                # Convert YYYYMMDD strings to datetime
                filter_start = pd.to_datetime(start_date, format='%Y%m%d')
                filter_end = pd.to_datetime(end_date, format='%Y%m%d')
                # Include the full end date (set to end of day)
                filter_end = filter_end.replace(hour=23, minute=59, second=59)
                
                # Filter data to requested date range
                original_len = len(df_asos)
                df_asos = df_asos[(df_asos.index >= filter_start) & (df_asos.index <= filter_end)].copy()
                
                if len(df_asos) == 0:
                    print(f"  ⚠ Warning: No data in date range {start_date} to {end_date}")
                    print(f"    Available data range: {original_date_range[0]} to {original_date_range[1]}")
                    return None
                elif len(df_asos) < original_len:
                    print(f"  ℹ Filtered to date range: {filter_start.date()} to {filter_end.date()}")
                    print(f"    (Reduced from {original_len:,} to {len(df_asos):,} records)")
            except Exception as e:
                print(f"  ⚠ Warning: Could not filter by date range: {e}")
                # Continue with unfiltered data
        
        # Check if DataFrame is empty after setting index
        if len(df_asos) == 0:
            print(f"  ⚠ Warning: DataFrame is empty after setting index")
            return None
        
        # Check if file contains multiple stations
        if 'station_id' in df_asos.columns and 'precip_mm' in df_asos.columns:
            # Extract all unique stations
            unique_stations = df_asos['station_id'].unique()
            print(f"  ✓ Found {len(unique_stations)} stations: {list(unique_stations)}")
            
            # Create DataFrame with one column per station using pivot
            # This is more reliable than manual joins
            try:
                df_asos_stations = df_asos.pivot_table(
                    index=df_asos.index,
                    columns='station_id',
                    values='precip_mm',
                    aggfunc='first'  # Use first value if duplicates exist
                )
                df_asos_stations.index.name = 'time'
            except Exception as e:
                print(f"  ⚠ Warning: Pivot failed, trying manual join: {e}")
                # Fallback to manual join
                all_times = df_asos.index.sort_values().unique()
                df_asos_stations = pd.DataFrame(index=all_times)
                df_asos_stations.index.name = 'time'
                
                for st_id in unique_stations:
                    st_data = df_asos[df_asos['station_id'] == st_id][['precip_mm']].copy()
                    if len(st_data) > 0:
                        st_data.columns = [st_id]
                        df_asos_stations = df_asos_stations.join(st_data, how='outer')
            
            df_asos_stations = df_asos_stations.sort_index()
            
            # Apply date filtering to pivoted DataFrame if needed
            if start_date and end_date:
                try:
                    filter_start = pd.to_datetime(start_date, format='%Y%m%d')
                    filter_end = pd.to_datetime(end_date, format='%Y%m%d')
                    filter_end = filter_end.replace(hour=23, minute=59, second=59)
                    
                    original_len = len(df_asos_stations)
                    df_asos_stations = df_asos_stations[(df_asos_stations.index >= filter_start) & (df_asos_stations.index <= filter_end)].copy()
                    
                    if len(df_asos_stations) == 0:
                        print(f"  ⚠ Warning: No data in date range after pivoting")
                        return None
                except Exception as e:
                    print(f"  ⚠ Warning: Could not filter pivoted data by date: {e}")
            
            # Check if we have any columns (stations)
            if len(df_asos_stations.columns) == 0:
                print(f"  ⚠ Warning: No station columns created")
                print(f"    Debug: unique_stations={unique_stations}, df_asos shape={df_asos.shape}")
                return None
            
            # Fill NaN with 0 for better visibility (zero precipitation)
            df_asos_stations = df_asos_stations.fillna(0)
            
            # Clip negative values to 0
            df_asos_stations = df_asos_stations.clip(lower=0)
            
            print(f"  ✓ Loaded {len(df_asos_stations):,} time points")
            if len(df_asos_stations.columns) > 0:
                print(f"    Precipitation range: {df_asos_stations.min().min():.2f} to {df_asos_stations.max().max():.2f} mm")
            return df_asos_stations
        else:
            # Single station or no station_id column - return as is
            print(f"  ✓ Loaded {len(df_asos):,} records")
            if 'precip_mm' in df_asos.columns:
                # Fill NaN with 0 for better visibility
                df_asos['precip_mm'] = df_asos['precip_mm'].fillna(0)
                # Clip negative values to 0
                df_asos['precip_mm'] = df_asos['precip_mm'].clip(lower=0)
                print(f"    Precipitation range: {df_asos['precip_mm'].min():.2f} to {df_asos['precip_mm'].max():.2f} mm")
            return df_asos
        
    except Exception as e:
        import traceback
        print(f"  ✗ Error loading ASOS data: {e}")
        print(f"  Full traceback:")
        traceback.print_exc()
        return None


def extract_cml_timeseries(
    ds_cml: xr.Dataset,
    link_id: str = '1',
    sublink_id: str = 'sublink_1'
) -> pd.DataFrame:
    """
    Extract RSL time series for a specific link and sublink.
    
    Parameters
    ----------
    ds_cml : xarray.Dataset
        CML dataset
    link_id : str
        Link ID (e.g., '1', '2', etc.)
    sublink_id : str
        Sublink ID (e.g., 'sublink_1', 'sublink_2', etc.)
    
    Returns
    -------
    df_cml : pandas.DataFrame
        DataFrame with 'time' index and 'rsl' column, plus calculated 'attenuation'
    """
    # Extract RSL for selected link and sublink
    rsl_data = ds_cml.rsl.sel(cml_id=link_id, sublink_id=sublink_id)
    
    # Convert to pandas
    df_cml = pd.DataFrame({
        'time': pd.to_datetime(rsl_data.time.values),
        'rsl': rsl_data.values,
        'link_id': link_id,
        'sublink_id': sublink_id
    })
    
    # Set time as index first (needed for rolling window)
    df_cml.set_index('time', inplace=True)
    
    # Calculate rolling baseline (3 hours window) using 95th percentile for each time step
    # This gives a dynamic baseline that adapts to local conditions
    window_size = '3H'  # 3-hour rolling window
    rolling_baseline = df_cml['rsl'].rolling(window=window_size, min_periods=1).quantile(0.95)
    
    # Store rolling baseline in the dataframe
    df_cml['baseline'] = rolling_baseline
    
    # Calculate attenuation (rolling baseline - RSL) for each time step
    df_cml['attenuation'] = df_cml['baseline'] - df_cml['rsl']
    df_cml['attenuation'] = df_cml['attenuation'].clip(lower=0)  # Only positive attenuation
    
    return df_cml


def extract_pws_rainfall(
    pws_data: Dict[str, xr.Dataset],
    station_id: Optional[str] = None
) -> pd.DataFrame:
    """
    Extract rainfall data from PWS dataset.
    
    Parameters
    ----------
    pws_data : dict
        Dictionary of xarray.Dataset objects (one per station)
    station_id : str, optional
        Station ID to extract. If None, uses first station.
    
    Returns
    -------
    df_pws : pandas.DataFrame
        DataFrame with 'time' index and 'precipitation_mm' column
    """
    if station_id is None:
        station_id = list(pws_data.keys())[0]
        print(f"Using station '{station_id}' (first available)")
    
    if station_id not in pws_data:
        raise ValueError(f"Station '{station_id}' not found in PWS data")
    
    station_ds = pws_data[station_id]
    
    # Get time values directly from xarray Dataset (handles irregular time steps)
    # Convert time to pandas datetime - xarray handles the conversion
    try:
        # Try to get time as pandas DatetimeIndex directly
        if hasattr(station_ds.time, 'to_pandas'):
            time_index = station_ds.time.to_pandas()
        else:
            # Convert time values to datetime
            time_values = station_ds.time.values
            # Handle different time formats (seconds since epoch, datetime64, etc.)
            if isinstance(time_values[0], (int, float, np.integer, np.floating)):
                # Assume Unix timestamp (seconds since 1970-01-01)
                time_index = pd.to_datetime(time_values, unit='s', errors='coerce')
            else:
                # Already datetime-like
                time_index = pd.to_datetime(time_values, errors='coerce')
    except Exception as e:
        print(f"Warning: Error converting time: {e}. Trying alternative method...")
        time_index = pd.to_datetime(station_ds.time.values, errors='coerce')
    
    # Extract rainfall data
    if 'rainfall_amount' in station_ds.data_vars:
        rainfall_var = station_ds['rainfall_amount']
        # Get values - handle multi-dimensional arrays
        rainfall_values = rainfall_var.values
        
        # Flatten if multi-dimensional (e.g., if there are extra dimensions)
        if rainfall_values.ndim > 1:
            # Take the first slice along non-time dimensions
            # Assuming time is the first dimension
            if 'time' in rainfall_var.dims:
                time_dim_idx = rainfall_var.dims.index('time')
                # Reshape to 1D along time dimension
                rainfall_values = rainfall_values.flatten()
                # If flattened array is longer than time, truncate
                if len(rainfall_values) > len(time_index):
                    rainfall_values = rainfall_values[:len(time_index)]
                elif len(rainfall_values) < len(time_index):
                    # Pad with NaN if shorter
                    pad_length = len(time_index) - len(rainfall_values)
                    rainfall_values = np.concatenate([rainfall_values, np.full(pad_length, np.nan)])
        else:
            # Ensure same length as time
            if len(rainfall_values) != len(time_index):
                min_len = min(len(rainfall_values), len(time_index))
                rainfall_values = rainfall_values[:min_len]
                time_index = time_index[:min_len]
        
        df_pws = pd.DataFrame({
            'precipitation_mm': rainfall_values
        }, index=time_index)
        
    elif 'rainfall_rate' in station_ds.data_vars:
        rainfall_var = station_ds['rainfall_rate']
        # Get values - handle multi-dimensional arrays
        rainfall_values = rainfall_var.values
        
        # Flatten if multi-dimensional
        if rainfall_values.ndim > 1:
            rainfall_values = rainfall_values.flatten()
            if len(rainfall_values) > len(time_index):
                rainfall_values = rainfall_values[:len(time_index)]
            elif len(rainfall_values) < len(time_index):
                pad_length = len(time_index) - len(rainfall_values)
                rainfall_values = np.concatenate([rainfall_values, np.full(pad_length, np.nan)])
        else:
            if len(rainfall_values) != len(time_index):
                min_len = min(len(rainfall_values), len(time_index))
                rainfall_values = rainfall_values[:min_len]
                time_index = time_index[:min_len]
        
        # Convert rate (mm/h) to amount (mm) - assuming irregular intervals
        # For irregular intervals, we'll use a simple conversion factor
        # This is approximate - ideally we'd use actual time differences
        df_pws = pd.DataFrame({
            'precipitation_mm': rainfall_values * (5/60)  # Approximate: 5 min intervals
        }, index=time_index)
    else:
        raise ValueError(f"No rainfall variable found in station '{station_id}'. Available variables: {list(station_ds.data_vars.keys())}")
    
    # Remove rows with invalid time (NaT)
    df_pws = df_pws[df_pws.index.notna()]
    
    # Fill NaN with 0 for better visibility (zero precipitation)
    df_pws['precipitation_mm'] = df_pws['precipitation_mm'].fillna(0)
    
    # Clip negative values to 0 (shouldn't happen, but safety check)
    df_pws['precipitation_mm'] = df_pws['precipitation_mm'].clip(lower=0)
    
    # Clip unreasonably high values (>20 mm per 5-min = 240 mm/h, which is extreme)
    # This handles potential data issues while preserving real heavy rain events
    df_pws['precipitation_mm'] = df_pws['precipitation_mm'].clip(upper=20)
    
    return df_pws


def extract_all_pws_rainfall(
    pws_data: Dict[str, xr.Dataset],
    station_ids: Optional[list] = None
) -> pd.DataFrame:
    """
    Extract rainfall data from ALL PWS stations and combine into one DataFrame.
    Each station becomes a column.
    
    Parameters
    ----------
    pws_data : dict
        Dictionary of xarray.Dataset objects (one per station)
    station_ids : list, optional
        List of station IDs to extract. If None, extracts all stations.
    
    Returns
    -------
    df_pws_all : pandas.DataFrame
        DataFrame with 'time' index and one column per station (named by station_id)
    """
    if station_ids is None:
        station_ids = list(pws_data.keys())
    
    print(f"Extracting rainfall from {len(station_ids)} PWS stations...")
    
    # Dictionary to store DataFrames for each station
    station_dfs = {}
    
    for station_id in station_ids:
        if station_id not in pws_data:
            print(f"  ⚠ Station '{station_id}' not found, skipping...")
            continue
        
        try:
            # Extract single station data
            df_station = extract_pws_rainfall(pws_data, station_id=station_id)
            if df_station is not None and len(df_station) > 0:
                # Rename column to station ID
                df_station.columns = [station_id]
                station_dfs[station_id] = df_station
                print(f"  ✓ {station_id}: {len(df_station):,} records")
            else:
                print(f"  ⚠ {station_id}: No data extracted")
        except Exception as e:
            print(f"  ✗ {station_id}: Error - {e}")
            continue
    
    if len(station_dfs) == 0:
        print("✗ No PWS data extracted from any station")
        return pd.DataFrame()
    
    # Combine all stations into one DataFrame
    # Use outer join to keep all time points (stations may have different time coverage)
    df_pws_all = pd.DataFrame()
    for station_id, df_station in station_dfs.items():
        # Ensure each station's data is properly processed (zero-fill and clip already done in extract_pws_rainfall)
        if len(df_pws_all) == 0:
            df_pws_all = df_station.copy()
        else:
            df_pws_all = df_pws_all.join(df_station, how='outer')
    
    # Sort by time
    df_pws_all = df_pws_all.sort_index()
    
    # Fill NaN with 0 for better visibility (zero precipitation)
    df_pws_all = df_pws_all.fillna(0)
    
    # Clip negative values to 0 and unreasonably high values (>20 mm per 5-min)
    df_pws_all = df_pws_all.clip(lower=0, upper=20)
    
    print(f"\n✓ Combined PWS data:")
    print(f"  Stations: {len(df_pws_all.columns)}")
    print(f"  Time range: {df_pws_all.index.min()} to {df_pws_all.index.max()}")
    print(f"  Total time points: {len(df_pws_all):,}")
    if len(df_pws_all.columns) > 0:
        print(f"  Precipitation range: {df_pws_all.min().min():.2f} to {df_pws_all.max().max():.2f} mm")
    
    return df_pws_all


def detect_rain_constant_threshold(
    df_cml: pd.DataFrame,
    threshold_dB: float = 2.0,
    resample_freq: str = '5min'
) -> pd.DataFrame:
    """
    Detect rain using a constant threshold on CML attenuation.
    
    Parameters
    ----------
    df_cml : pd.DataFrame
        CML data with 'attenuation' column, indexed by time
    threshold_dB : float, optional
        Constant threshold in dB. If attenuation > threshold, rain is detected. Default: 2.0 dB
    resample_freq : str, optional
        Resampling frequency for CML data. Default: '5min'
    
    Returns
    -------
    df_result : pd.DataFrame
        DataFrame with columns:
        - 'attenuation': resampled attenuation values
        - 'rain_detected': binary detection (1 = rain, 0 = no rain)
        - 'threshold_constant': constant threshold value
    """
    if df_cml is None or len(df_cml) == 0:
        print("⚠ Error: No CML data provided")
        return pd.DataFrame()
    
    if 'attenuation' not in df_cml.columns:
        print("⚠ Error: 'attenuation' column not found in CML data")
        return pd.DataFrame()
    
    # Resample CML to specified frequency
    df_resampled = df_cml[['attenuation']].resample(resample_freq).mean()
    
    # Binary detection: 1 = rain, 0 = no rain
    df_resampled['rain_detected'] = (
        df_resampled['attenuation'] > threshold_dB
    ).astype(int)
    
    # Store threshold for plotting
    df_resampled['threshold_constant'] = threshold_dB
    
    return df_resampled

