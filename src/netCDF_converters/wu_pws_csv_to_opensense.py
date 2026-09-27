"""
Convert scraped Weather Underground PWS CSVs to OpenSense-PWS-v1.0 netCDF — the
converter behind the published Zenodo file `pws_wu_os.nc` (record 17508286,
dataset/raw/openmesh/pws_wu_os.nc). DEFAULT WU converter of this project.

Ported from ~/PycharmProjects/OpenMesh: data/weather/wu/converter.py (conversion,
filtering, spec alignment, missing-rain check) and data/weather/wu/pws_to_netcdf.ipynb
(`save_pws_groups`, `set_global_attributes`). Functions are unchanged; plotting and
display helpers were left out; `convert()` chains the notebook's steps:

  1. process_all_csv_files      CSVs -> intermediate grouped netCDF (metric, UTC)
  2. convert_groups_to_xarray_dict
  3. filter_and_rename_pws_stations(start, end)   (Zenodo: 2023-10-29 .. 2024-07-01)
  4. align_pws_to_spec           per station (OpenSense variable names / attrs)
  5. check_missing_rainfall      stations with too much missing rain are dropped
  6. save_pws_groups             one netCDF4 group per station + global attributes

For the 2023-2026 WU scrape format (with airports) use `wu_pws_csv_to_netcdf.py`.

Usage (CLI):
    python wu_pws_csv_to_opensense.py <input_dir> <metadata_csv> <output.nc> \
        [--start 2023-10-29 --end 2024-07-01]
Usage (import):
    from wu_pws_csv_to_opensense import convert
    convert(input_dir, metadata_csv, output_nc)
"""
import argparse
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import netCDF4 as nc
import numpy as np
import pandas as pd
import xarray as xr

logger = logging.getLogger(__name__)


def inches_to_mm(inches: float) -> float:
    return inches * 25.4


def fahrenheit_to_celsius(fahrenheit: float) -> float:
    return (fahrenheit - 32) * 5 / 9


def mph_to_ms(mph: float) -> float:
    return mph * 0.44704


def inhg_to_hpa(inhg: float) -> float:
    return inhg * 33.8639


def direction_to_degrees(direction: str) -> Optional[float]:
    direction_map = {
        'N': 0, 'NNE': 22.5, 'NE': 45, 'ENE': 67.5,
        'E': 90, 'ESE': 112.5, 'SE': 135, 'SSE': 157.5,
        'S': 180, 'SSW': 202.5, 'SW': 225, 'WSW': 247.5,
        'W': 270, 'WNW': 292.5, 'NW': 315, 'NNW': 337.5
    }
    if isinstance(direction, str):
        return direction_map.get(direction.strip().upper())
    return None


def parse_value_with_unit(value_str: str) -> Tuple[Optional[float], str]:
    if pd.isna(value_str):
        return None, ''
    if isinstance(value_str, (int, float)):
        return float(value_str), ''

    value_str = str(value_str).strip()
    parts = value_str.split()
    if len(parts) == 0:
        return None, ''

    try:
        value = float(parts[0])
        unit = ' '.join(parts[1:]) if len(parts) > 1 else ''
        return value, unit
    except ValueError:
        return None, value_str


def calculate_interval_accumulation(daily_accum: np.ndarray) -> np.ndarray:
    """Convert daily-reset cumulative rainfall to per-interval accumulation."""
    interval_accum = np.zeros_like(daily_accum)
    interval_accum[0] = daily_accum[0]

    for i in range(1, len(daily_accum)):
        if np.isnan(daily_accum[i]) or np.isnan(daily_accum[i - 1]):
            interval_accum[i] = np.nan
        elif daily_accum[i] >= daily_accum[i - 1]:
            interval_accum[i] = daily_accum[i] - daily_accum[i - 1]
        else:
            interval_accum[i] = daily_accum[i]

    return interval_accum


def read_pws_csv(filepath: str, timezone: str = 'America/New_York',
                 chunksize: int = None) -> pd.DataFrame:
    """Read PWS CSV file and parse data."""
    logger.info(f"Reading: {Path(filepath).name}")

    if chunksize:
        chunks = []
        for chunk in pd.read_csv(filepath, chunksize=chunksize):
            chunk['Datetime'] = pd.to_datetime(chunk['Datetime'])
            chunks.append(chunk)
        df = pd.concat(chunks, ignore_index=True)
    else:
        df = pd.read_csv(filepath)

    # Validate
    if 'Datetime' not in df.columns:
        raise ValueError("Missing 'Datetime' column")

    # Parse datetime with DST handling
    df['Datetime'] = pd.to_datetime(df['Datetime'])
    if df['Datetime'].dt.tz is None:
        df['Datetime'] = df['Datetime'].dt.tz_localize(
            timezone, ambiguous='infer', nonexistent='shift_forward'
        ).dt.tz_convert('UTC')
    else:
        df['Datetime'] = df['Datetime'].dt.tz_convert('UTC')

    df = df.set_index('Datetime').sort_index()
    logger.info(f"  {len(df)} records")
    return df


def process_pws_data(df: pd.DataFrame, station_id: str) -> Dict:
    """Process PWS dataframe and convert units."""
    data = {'time': df.index, 'station_id': station_id}

    # Rainfall rate
    if 'Precip. Rate.' in df.columns:
        precip_rate = []
        for val in df['Precip. Rate.']:
            num_val, unit = parse_value_with_unit(val)
            if num_val is not None and '°in' in unit:
                precip_rate.append(inches_to_mm(num_val))
            else:
                precip_rate.append(np.nan)
        data['rainfall_rate'] = np.array(precip_rate, dtype=np.float64)

    # Rainfall accumulation
    if 'Precip. Accum.' in df.columns:
        precip_accum = []
        for val in df['Precip. Accum.']:
            num_val, unit = parse_value_with_unit(val)
            if num_val is not None and '°in' in unit:
                precip_accum.append(inches_to_mm(num_val))
            else:
                precip_accum.append(np.nan)
        daily_accum_array = np.array(precip_accum, dtype=np.float64)
        data['rainfall_accumulation'] = calculate_interval_accumulation(daily_accum_array)

    # Temperature
    if 'Temperature' in df.columns:
        temp = []
        for val in df['Temperature']:
            num_val, unit = parse_value_with_unit(val)
            if num_val is not None and '°F' in unit:
                temp.append(fahrenheit_to_celsius(num_val))
            else:
                temp.append(np.nan)
        data['temperature'] = np.array(temp, dtype=np.float64)

    # Humidity
    if 'Humidity' in df.columns:
        humidity = []
        for val in df['Humidity']:
            num_val, unit = parse_value_with_unit(val)
            if num_val is not None:
                humidity.append(num_val)
            else:
                humidity.append(np.nan)
        data['relative_humidity'] = np.array(humidity, dtype=np.float64)

    # Wind speed
    if 'Speed' in df.columns:
        wind_speed = []
        for val in df['Speed']:
            num_val, unit = parse_value_with_unit(val)
            if num_val is not None and 'mph' in unit:
                wind_speed.append(mph_to_ms(num_val))
            else:
                wind_speed.append(np.nan)
        data['wind_velocity'] = np.array(wind_speed, dtype=np.float64)

    # Wind direction
    if 'Wind' in df.columns:
        wind_dir = []
        for val in df['Wind']:
            deg = direction_to_degrees(val)
            wind_dir.append(deg if deg is not None else np.nan)
        data['wind_direction'] = np.array(wind_dir, dtype=np.float64)

    # Air pressure
    if 'Pressure' in df.columns:
        pressure = []
        for val in df['Pressure']:
            num_val, unit = parse_value_with_unit(val)
            if num_val is not None and '°in' in unit:
                pressure.append(inhg_to_hpa(num_val))
            else:
                pressure.append(np.nan)
        data['air_pressure'] = np.array(pressure, dtype=np.float64)

    return data


def read_station_metadata(csv_path: str) -> Dict[str, Dict]:
    """Read station metadata from CSV."""
    logger.info(f"Reading metadata: {Path(csv_path).name}")
    df = pd.read_csv(csv_path)

    if 'Station ID' not in df.columns:
        raise ValueError("Metadata must have 'Station ID' column")

    metadata = {}
    for _, row in df.iterrows():
        station_id = str(row['Station ID'])
        metadata[station_id] = {
            'lat': float(row['Latitude']) if 'Latitude' in row and pd.notna(row['Latitude']) else None,
            'lon': float(row['Longitude']) if 'Longitude' in row and pd.notna(row['Longitude']) else None,
            'elev': float(row['Elevation']) if 'Elevation' in row and pd.notna(row['Elevation']) else None,
            'hardware': str(row['Hardware']) if 'Hardware' in row and pd.notna(row['Hardware']) else None,
            'height_above_ground': float(row['Height']) if 'Height' in row and pd.notna(row['Height']) else None,
            'environmental_class': int(row['Class']) if 'Class' in row and pd.notna(row['Class']) else None,
        }

    logger.info(f"  Loaded {len(metadata)} stations")
    return metadata


def extract_station_id(filename: str) -> str:
    """Extract station ID from filename."""
    name = filename.replace('.csv', '')
    return name.split('_')[0]


def create_netcdf_with_groups(
        all_station_data: Dict[str, Dict],
        station_metadata: Dict[str, Dict] = None,
        output_path: str = None
) -> nc.Dataset:
    """Create netCDF with groups. Returns dataset object."""

    if station_metadata is None:
        station_metadata = {}

    # Create dataset
    if output_path:
        logger.info(f"Saving to: {output_path}")
        ds = nc.Dataset(output_path, 'w', format='NETCDF4')
    else:
        logger.info("Creating in-memory dataset")
        # Create truly in-memory dataset without touching filesystem
        try:
            # Try method 1: empty string (some netCDF versions)
            ds = nc.Dataset('', 'w', format='NETCDF4', diskless=True, persist=False)
        except:
            try:
                # Try method 2: temp file
                import tempfile
                import os
                temp_fd, temp_name = tempfile.mkstemp(suffix='.nc')
                os.close(temp_fd)
                os.unlink(temp_name)
                ds = nc.Dataset(temp_name, 'w', format='NETCDF4', diskless=True, persist=False)
            except:
                # Fallback: use actual temp file
                import tempfile
                temp_name = tempfile.mktemp(suffix='.nc')
                ds = nc.Dataset(temp_name, 'w', format='NETCDF4')

    # Global attributes
    ds.Conventions = 'CF-1.8'
    ds.title = 'Personal Weather Station Network Data - OpenSense Format'
    ds.institution = 'PWS Network'
    ds.source = 'Personal Weather Station'
    ds.history = f'Created {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC'

    # Create groups
    for station_id, data in all_station_data.items():
        grp = ds.createGroup(station_id)
        metadata = station_metadata.get(station_id, {})

        # ===================================================================
        # DIMENSIONS
        # ===================================================================
        grp.createDimension('time', None)  # Unlimited
        grp.createDimension('id', 1)  # Single station per group

        # ===================================================================
        # COORDINATE VARIABLES
        # ===================================================================

        # Time coordinate (time)
        time_var = grp.createVariable('time', 'f8', ('time',))
        time_var.units = 'seconds since 1970-01-01 00:00:00 UTC'
        time_var.long_name = 'time_utc'
        time_var.calendar = 'gregorian'
        time_seconds = [(t.tz_localize('UTC') if t.tz is None else t).timestamp() for t in data['time']]
        time_var[:] = time_seconds

        # ID coordinate (id)
        id_var = grp.createVariable('id', str, ('id',))
        id_var.long_name = 'personal_weather_station_identifier'
        id_var[0] = station_id

        # ===================================================================
        # AUXILIARY COORDINATE VARIABLES (all dimension id)
        # ===================================================================

        if metadata.get('lat') is not None:
            lat_var = grp.createVariable('lat', 'f8', ('id',))
            lat_var.units = 'degrees_in_WGS84_projection'
            lat_var.long_name = 'latitude'
            lat_var[0] = metadata['lat']

        if metadata.get('lon') is not None:
            lon_var = grp.createVariable('lon', 'f8', ('id',))
            lon_var.units = 'degrees_in_WGS84_projection'
            lon_var.long_name = 'longitude'
            lon_var[0] = metadata['lon']

        if metadata.get('elev') is not None:
            elev_var = grp.createVariable('elev', 'f8', ('id',))
            elev_var.units = 'metres_above_sea'
            elev_var.long_name = 'ground_elevation_above_sea_level'
            elev_var[0] = metadata['elev']

        if metadata.get('height_above_ground') is not None:
            height_var = grp.createVariable('height_above_ground_level', 'f8', ('id',))
            height_var.units = 'metres'
            height_var.long_name = 'height_above_ground_level'
            height_var[0] = metadata['height_above_ground']

        if metadata.get('environmental_class') is not None:
            env_var = grp.createVariable('environmental_class', 'i4', ('id',))
            env_var.long_name = 'environmental_classification'
            env_var[0] = metadata['environmental_class']

        if metadata.get('hardware') is not None:
            hw_var = grp.createVariable('hardware', str, ('id',))
            hw_var.long_name = 'manufacturer_and_model_type'
            hw_var[0] = metadata['hardware']

        # ===================================================================
        # DATA VARIABLES (all dimension: id, time)
        # ===================================================================

        coord_str = 'lat lon' if metadata.get('lat') and metadata.get('lon') else ''

        if 'rainfall_rate' in data:
            var = grp.createVariable('rainfall_rate', 'f8', ('id', 'time'), fill_value=np.nan)
            var.long_name = 'rainfall_rate'
            var.units = 'mm h-1'
            if coord_str:
                var.coordinates = coord_str
            var[0, :] = data['rainfall_rate']

        if 'rainfall_accumulation' in data:
            var = grp.createVariable('rainfall_accumulation', 'f8', ('id', 'time'), fill_value=np.nan)
            var.long_name = 'rainfall_amount_per_time_interval'
            var.units = 'mm'
            if coord_str:
                var.coordinates = coord_str
            var[0, :] = data['rainfall_accumulation']

        if 'temperature' in data:
            var = grp.createVariable('temperature', 'f8', ('id', 'time'), fill_value=np.nan)
            var.long_name = 'air_temperature'
            var.units = 'degrees_celsius'
            if coord_str:
                var.coordinates = coord_str
            var[0, :] = data['temperature']

        if 'relative_humidity' in data:
            var = grp.createVariable('relative_humidity', 'f8', ('id', 'time'), fill_value=np.nan)
            var.long_name = 'relative_humidity'
            var.units = '%'
            if coord_str:
                var.coordinates = coord_str
            var[0, :] = data['relative_humidity']

        if 'wind_velocity' in data:
            var = grp.createVariable('wind_velocity', 'f8', ('id', 'time'), fill_value=np.nan)
            var.long_name = 'wind_speed'
            var.units = 'ms-1'
            if coord_str:
                var.coordinates = coord_str
            var[0, :] = data['wind_velocity']

        if 'wind_direction' in data:
            var = grp.createVariable('wind_direction', 'f8', ('id', 'time'), fill_value=np.nan)
            var.long_name = 'wind_from_direction'
            var.units = 'degrees'
            if coord_str:
                var.coordinates = coord_str
            var[0, :] = data['wind_direction']

        if 'air_pressure' in data:
            var = grp.createVariable('air_pressure', 'f8', ('id', 'time'), fill_value=np.nan)
            var.long_name = 'air_pressure'
            var.units = 'hPa'
            if coord_str:
                var.coordinates = coord_str
            var[0, :] = data['air_pressure']

    # Verify dataset before returning
    logger.info(f"✓ Created dataset with {len(ds.groups)} groups")
    return ds


def process_all_csv_files(
        input_dir: str,
        metadata_csv: str,
        output_path: str = 'all_stations.nc',
        save: bool = False,
        timezone: str = 'America/New_York',
        chunksize: int = None
) -> nc.Dataset:
    """
    Process PWS CSV files and return netCDF dataset.

    Parameters:
    -----------
    input_dir : str
        Directory with CSV files
    metadata_csv : str
        Path to metadata CSV
    output_path : str
        Output file path (default: 'all_stations.nc')
    save : bool
        If True, saves file (default: False - in-memory only)
    timezone : str
        Input timezone (default: 'America/New_York')
    chunksize : int
        Read CSV in chunks (default: None)

    Returns:
    --------
    nc.Dataset or None
    """
    input_path = Path(input_dir)

    logger.info("=" * 70)
    logger.info("PWS TO NETCDF CONVERTER")
    logger.info("=" * 70)
    logger.info(f"Input: {input_dir}")
    logger.info(f"Metadata: {metadata_csv}")
    if save:
        logger.info(f"Save to: {output_path}")
    else:
        logger.info("Mode: In-memory (no file saved)")
    logger.info("=" * 70)

    # Create output directory if saving
    if save:
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

    # Read metadata
    try:
        station_metadata = read_station_metadata(metadata_csv)
    except Exception as e:
        logger.error(f"Metadata error: {str(e)}")
        return None

    # Find CSV files
    csv_files = [f for f in input_path.glob('*.csv')
                 if f.name != Path(metadata_csv).name]

    if len(csv_files) == 0:
        logger.error(f"No CSV files found in {input_dir}")
        return None

    logger.info(f"\nFound {len(csv_files)} files\n")

    # Process files
    all_station_data = {}
    successful = 0
    failed = 0
    errors = []

    for idx, csv_file in enumerate(csv_files, 1):
        logger.info(f"[{idx}/{len(csv_files)}] {csv_file.name}")

        try:
            station_id = extract_station_id(csv_file.name)
            df = read_pws_csv(csv_file, timezone=timezone, chunksize=chunksize)
            data = process_pws_data(df, station_id)
            all_station_data[station_id] = data

            successful += 1
            logger.info("  ✓ Done\n")

        except Exception as e:
            failed += 1
            error_msg = f"{csv_file.name}: {str(e)}"
            errors.append(error_msg)
            logger.error(f"  ✗ {error_msg}\n")
            continue

    # Summary
    logger.info("=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Processed: {successful}/{len(csv_files)}")
    logger.info(f"Failed: {failed}")

    if errors:
        logger.info("\nErrors:")
        for error in errors:
            logger.info(f"  • {error}")

    logger.info("=" * 70)

    # Create dataset
    if len(all_station_data) == 0:
        logger.error("No stations processed")
        return None

    try:
        file_path = output_path if save else None
        ds = create_netcdf_with_groups(
            all_station_data=all_station_data,
            station_metadata=station_metadata,
            output_path=file_path
        )

        # Verify dataset is valid
        if ds is None:
            logger.error("Dataset creation returned None")
            return None

        if len(ds.groups) == 0:
            logger.error("Dataset has no groups")
            ds.close()
            return None

        logger.info(f"✓ Dataset ready ({len(ds.groups)} stations)")
        logger.info(f"✓ Groups: {list(ds.groups.keys())}")
        return ds

    except Exception as e:
        logger.error(f"Failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def convert_groups_to_xarray_dict(ds):
    """Convert all station groups to dictionary of xarray Datasets."""
    stations = {}

    for station_id in ds.groups.keys():
        grp = ds.groups[station_id]

        # Get time as datetime (copy to memory)
        time_vals = grp.variables['time'][:].copy()
        times = pd.to_datetime(time_vals, unit='s')

        # Build coordinates
        coords = {
            'time': times,
            'id': grp.variables['id'][:].copy(),
        }

        if 'lat' in grp.variables:
            coords['latitude'] = ('id', grp.variables['lat'][:].copy())
        if 'lon' in grp.variables:
            coords['longitude'] = ('id', grp.variables['lon'][:].copy())
        if 'elev' in grp.variables:
            coords['elevation'] = ('id', grp.variables['elev'][:].copy())

        # Extract data variables
        data_vars = {}
        skip_vars = ['time', 'id', 'lat', 'lon', 'elev',
                     'height_above_ground_level', 'environmental_class', 'hardware']

        for var_name in grp.variables:
            if var_name not in skip_vars:
                data_vars[var_name] = (['id', 'time'], grp.variables[var_name][:].copy())

        # Create xarray Dataset
        stations[station_id] = xr.Dataset(data_vars=data_vars, coords=coords)

    return stations


def check_pws_format(ds, station_id="UNKNOWN"):
    """
    Check if single PWS Dataset conforms to OpenSense PWS spec.

    Parameters:
    -----------
    ds : xarray.Dataset
        Single PWS dataset to check
    station_id : str
        Station identifier for reporting

    Returns:
    --------
    dict
        Issues found with explanations
    """

    issues = {}

    print(f"\n{'=' * 80}")
    print(f"CHECKING PWS FORMAT: {station_id}")
    print(f"{'=' * 80}\n")

    # ========================================================================
    # CHECK DIMENSIONS
    # ========================================================================
    print("1️⃣  DIMENSIONS")
    print("-" * 80)

    if 'time' not in ds.dims:
        issues['dimension_time'] = "Missing 'time' dimension"
        print("❌ Missing 'time' dimension")
    else:
        print(f"✓ Has 'time' dimension: {len(ds.time)} records")

    if 'id' not in ds.dims:
        issues['dimension_id'] = "Missing 'id' dimension (or named differently)"
        print("❌ Missing 'id' dimension")
        print(f"   Found dimensions: {list(ds.dims.keys())}")
    else:
        print(f"✓ Has 'id' dimension: {len(ds.id)} values")

    # ========================================================================
    # CHECK COORDINATES
    # ========================================================================
    print("\n2️⃣  COORDINATE VARIABLES")
    print("-" * 80)

    # Check time coordinate
    if 'time' in ds.coords:
        print("✓ 'time' coordinate exists")
        time_dtype = str(ds.time.dtype)
        print(f"  dtype: {time_dtype}")

        # Check time attributes
        time_attrs = ds.time.attrs
        if 'units' not in time_attrs:
            issues['time_units'] = "Missing 'units' attribute on time"
            print("  ❌ Missing 'units' attribute")
        else:
            print(f"  ✓ units: {time_attrs['units']}")

        if 'long_name' not in time_attrs:
            issues['time_long_name'] = "Missing 'long_name' attribute on time"
            print("  ❌ Missing 'long_name' attribute")
        else:
            print(f"  ✓ long_name: {time_attrs['long_name']}")

    # Check id coordinate
    if 'id' in ds.coords:
        print("✓ 'id' coordinate exists")
        if 'long_name' not in ds.id.attrs:
            issues['id_long_name'] = "Missing 'long_name' on id"
            print("  ❌ Missing 'long_name' attribute")
        else:
            print(f"  ✓ long_name: {ds.id.attrs['long_name']}")

    # ========================================================================
    # CHECK AUXILIARY COORDINATES
    # ========================================================================
    print("\n3️⃣  AUXILIARY COORDINATE VARIABLES")
    print("-" * 80)


    # Check what's in current dataset
    current_coords = set(ds.coords.keys()) - {'time', 'id'}
    print(f"Current auxiliary coords: {current_coords}")

    for coord_name in ['latitude', 'longitude', 'elevation']:
        if coord_name in ds.coords:
            print(f"✓ Found '{coord_name}'")
            print(f"  Shape: {ds[coord_name].shape}")
            print(f"  Attributes: {ds[coord_name].attrs}")
        else:
            print(f"⚠️  Missing '{coord_name}'")

    # ========================================================================
    # CHECK DATA VARIABLES
    # ========================================================================
    print("\n4️⃣  REQUIRED DATA VARIABLES")
    print("-" * 80)

    # Rainfall
    if 'rainfall_amount' in ds.data_vars:
        print("✓ Has 'rainfall_amount'")
        print(f"  Attributes: {ds['rainfall_amount'].attrs}")
    elif 'rainfall_accumulation' in ds.data_vars:
        print("⚠️  Has 'rainfall_accumulation' (should be 'rainfall_amount')")
        issues['rainfall_name'] = "Should rename 'rainfall_accumulation' to 'rainfall_amount'"
    else:
        print("❌ Missing rainfall data (rainfall_amount or rainfall_accumulation)")
        issues['rainfall_missing'] = "No rainfall data found"

    # ========================================================================
    # CHECK OPTIONAL DATA VARIABLES
    # ========================================================================
    print("\n5️⃣  OPTIONAL DATA VARIABLES")
    print("-" * 80)

    optional_vars = {
        'temperature': {'units': 'degrees_celsius'},
        'relative_humidity': {'units': '%'},
        'wind_velocity': {'units': 'ms-1'},
        'wind_direction': {'units': 'degrees'},
        'air_pressure': {'units': 'hPa'},
    }

    for var_name, spec in optional_vars.items():
        if var_name in ds.data_vars:
            print(f"✓ Has '{var_name}'")
            attrs = ds[var_name].attrs
            if 'units' in attrs:
                print(f"  units: {attrs['units']}")
            else:
                print("  ⚠️  Missing 'units' attribute")
                issues[f'{var_name}_units'] = f"Missing 'units' on {var_name}"
        else:
            print(f"- '{var_name}' (optional, not present)")

    # ========================================================================
    # SUMMARY
    # ========================================================================
    print("\n" + "=" * 80)
    if issues:
        print(f"❌ ISSUES FOUND: {len(issues)}")
        for issue_key, issue_msg in issues.items():
            print(f"  • {issue_msg}")
    else:
        print("✅ FORMAT COMPLIANT - No issues found!")
    print("=" * 80 + "\n")

    return issues


def align_pws_to_spec(ds, station_id="UNKNOWN"):
    """
    Fix PWS Dataset to align with OpenSense spec.

    Parameters:
    -----------
    ds : xarray.Dataset
        Single PWS dataset to fix
    station_id : str
        Station identifier

    Returns:
    --------
    xarray.Dataset
        Fixed dataset aligned to OpenSense spec
    """

    print(f"\n{'=' * 80}")
    print(f"ALIGNING PWS TO OPENSENSE SPEC: {station_id}")
    print(f"{'=' * 80}\n")

    ds_aligned = ds.copy(deep=True)

    # 1. Rename dimensions if needed
    print("1️⃣  FIXING DIMENSIONS & COORDINATES")
    print("-" * 80)

    # Handle id dimension/coordinate
    if 'id' not in ds_aligned.dims:
        # If not named 'id', find the non-time dimension
        non_time_dims = [d for d in ds_aligned.dims if d != 'time']
        if non_time_dims:
            old_dim = non_time_dims[0]
            ds_aligned = ds_aligned.rename({old_dim: 'id'})
            print(f"✓ Renamed '{old_dim}' → 'id'")

    # Set id coordinate attributes
    if 'id' in ds_aligned.coords:
        ds_aligned['id'].attrs['long_name'] = 'personal_weather_station_identifier'
        print("✓ Set 'id' long_name")

    # Set time coordinate attributes
    if 'time' in ds_aligned.coords:
        ds_aligned['time'].attrs['units'] = 'seconds since 1970-01-01 00:00:00 UTC'
        ds_aligned['time'].attrs['long_name'] = 'time_utc'
        print("✓ Set 'time' attributes")

    # 2. Fix auxiliary coordinates (lat, lon, elev)
    print("\n2️⃣  FIXING AUXILIARY COORDINATES")
    print("-" * 80)

    # Rename to standard names and add attributes
    rename_map = {
        'latitude': 'lat',
        'longitude': 'lon',
        'elevation': 'elev'
    }

    for old_name, new_name in rename_map.items():
        if old_name in ds_aligned.coords:
            if old_name != new_name:
                ds_aligned = ds_aligned.rename({old_name: new_name})
                print(f"✓ Renamed '{old_name}' → '{new_name}'")

            # Add attributes
            if new_name == 'lat':
                ds_aligned[new_name].attrs['units'] = 'degrees_in_WGS84_projection'
                ds_aligned[new_name].attrs['long_name'] = 'latitude'
            elif new_name == 'lon':
                ds_aligned[new_name].attrs['units'] = 'degrees_in_WGS84_projection'
                ds_aligned[new_name].attrs['long_name'] = 'longitude'
            elif new_name == 'elev':
                ds_aligned[new_name].attrs['units'] = 'metres_above_sea'
                ds_aligned[new_name].attrs['long_name'] = 'ground_elevation_above_sea_level'

            print(f"  ✓ Set attributes for '{new_name}'")

    # 3. Fix data variables
    print("\n3️⃣  FIXING DATA VARIABLES")
    print("-" * 80)

    # Rename rainfall_accumulation → rainfall_amount
    if 'rainfall_accumulation' in ds_aligned.data_vars:
        ds_aligned = ds_aligned.rename({'rainfall_accumulation': 'rainfall_amount'})
        print("✓ Renamed 'rainfall_accumulation' → 'rainfall_amount'")

    # Add attributes to rainfall_amount
    if 'rainfall_amount' in ds_aligned.data_vars:
        ds_aligned['rainfall_amount'].attrs['units'] = 'mm'
        ds_aligned['rainfall_amount'].attrs['long_name'] = 'rainfall_amount_per_time_unit'
        print("✓ Set 'rainfall_amount' attributes")

    # 4. Add attributes to optional variables
    print("\n4️⃣  FIXING OPTIONAL VARIABLES")
    print("-" * 80)

    var_specs = {
        'temperature': 'degrees_celsius',
        'relative_humidity': '%',
        'wind_velocity': 'ms-1',
        'wind_direction': 'degrees',
        'air_pressure': 'hPa',
    }

    for var_name, units in var_specs.items():
        if var_name in ds_aligned.data_vars:
            ds_aligned[var_name].attrs['units'] = units
            print(f"✓ Set units for '{var_name}': {units}")

    print("\n" + "=" * 80)
    print("✅ ALIGNMENT COMPLETE")
    print("=" * 80 + "\n")

    return ds_aligned


def check_missing_rainfall(stations_aligned):
    """
    Check which PWS stations have >50% missing rainfall values.

    Parameters:
    -----------
    stations_aligned : dict
        Dictionary of aligned PWS Datasets

    Returns:
    --------
    dict
        Stations with >50% missing rainfall (station_id: % missing)
    """

    print(f"\n{'=' * 80}")
    print("CHECKING MISSING RAINFALL VALUES")
    print(f"{'=' * 80}\n")

    problematic_stations = {}

    for station_id, ds in stations_aligned.items():

        # Get rainfall data (use rainfall_amount or rainfall_accumulation)
        rainfall_var = None
        if 'rainfall_amount' in ds.data_vars:
            rainfall_var = 'rainfall_amount'
        elif 'rainfall_accumulation' in ds.data_vars:
            rainfall_var = 'rainfall_accumulation'
        else:
            print(f"{station_id}: ⚠️  No rainfall variable found")
            continue

        # Get rainfall data
        rainfall_data = ds[rainfall_var].values

        # Count total values and missing values
        total_values = rainfall_data.size
        missing_count = np.isnan(rainfall_data).sum()
        missing_percent = (missing_count / total_values) * 100

        # Print all stations
        if missing_percent > 50:
            status = "❌ PROBLEMATIC"
            problematic_stations[station_id] = missing_percent
        else:
            status = "✓"

        print(f"{station_id}")
        print(f"  Total records: {total_values}")
        print(f"  Missing values: {missing_count}")
        print(f"  Missing: {missing_percent:.1f}% {status}\n")

    # Summary
    print(f"{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}\n")

    if problematic_stations:
        print(f"❌ Stations with >50% missing rainfall: {len(problematic_stations)}\n")
        for station_id in sorted(problematic_stations.keys(),
                                 key=lambda x: problematic_stations[x],
                                 reverse=True):
            pct = problematic_stations[station_id]
            print(f"  • {station_id}: {pct:.1f}% missing")
    else:
        print("✅ All stations have <50% missing rainfall data")

    print(f"\n{'=' * 80}\n")

    return problematic_stations


def filter_and_rename_pws_stations(stations_xr,
                                   start_date='2023-10-29',
                                   end_date='2024-07-01'):
    """
    Filter each PWS station to date range and rename rainfall_accumulation.
    Keeps dict structure - each station remains separate Dataset.

    Parameters:
    -----------
    stations_xr : dict
        Dictionary of xarray Datasets, one per station
    start_date : str
        Start date (YYYY-MM-DD)
    end_date : str
        End date (YYYY-MM-DD)

    Returns:
    --------
    dict
        Same structure, but each Dataset filtered by time and renamed
    """

    stations_filtered = {}

    print(f"\n{'=' * 70}")
    print("FILTERING AND RENAMING PWS STATIONS")
    print(f"{'=' * 70}\n")

    for station_id, ds in stations_xr.items():
        # Get original time range
        time_start_orig = ds.time.values[0]
        time_end_orig = ds.time.values[-1]
        n_orig = len(ds.time)

        # Slice to date range
        ds_filtered = ds.sel(time=slice(start_date, end_date))

        # Rename rainfall_accumulation → rainfall_amount
        if 'rainfall_accumulation' in ds_filtered.data_vars:
            ds_filtered = ds_filtered.rename({'rainfall_accumulation': 'rainfall_amount'})

        stations_filtered[station_id] = ds_filtered

        # Report
        n_filtered = len(ds_filtered.time)
        print(f"{station_id}")
        print(f"  Before: {n_orig} records ({time_start_orig} to {time_end_orig})")
        print(f"  After:  {n_filtered} records (filtered to {start_date} to {end_date})")
        print("  ✓ Renamed: rainfall_accumulation → rainfall_amount\n")

    print(f"{'=' * 70}")
    print(f"✓ Filtered {len(stations_filtered)} stations")
    print(f"{'=' * 70}\n")

    return stations_filtered


# ---- from pws_to_netcdf.ipynb ----

def set_global_attributes(ds,
                         title="Weather Underground PWS Data",
                         file_authors="Your Name",
                         institution="Cellular Environmental Monitoring (CellEnMon) Lab, School of Electrical Engineering, Tel-Aviv University; Wireless and Mobile Networking (WiMNet) Lab, Department of Electrical Engineering, Columbia University",
                         date="2025-11-01",
                         source="Weather Underground Personal Weather Station Network",
                         history="2025-11-01: Converted to OpenSense-PWS-1.0 netCDF4 format. Data obtained from Weather Underground.",
                         naming_convention="OpenSense-PWS-1.0",
                         license_restrictions="CC-BY-NC 4.0 – https://creativecommons.org/licenses/by-nc/4.0/",
                         reference="https://github.com/OpenSenseAction/OS_data_format_conventions/blob/main/netCDF_PWS.adoc",
                         comment="Personal Weather Station data from Weather Underground network. Non-commercial use approved for academic research. Each station stored in separate netCDF4 group. Period: 2025-10-29 to 2025-07-01 (UTC). All timestamps in UTC.",
                         conventions="OpenSense-PWS-v1.0"):
    """Set OpenSense-PWS global attributes"""

    # Clear all existing attributes
    for attr in ds.ncattrs():
        ds.delncattr(attr)

    # Set required attributes
    ds.setncattr("title", title)
    ds.setncattr("file_author", file_authors)
    ds.setncattr("institution", institution)
    ds.setncattr("date", date)
    ds.setncattr("source", source)
    ds.setncattr("history", history)
    ds.setncattr("naming_convention", naming_convention)
    ds.setncattr("license_restrictions", license_restrictions)
    ds.setncattr("reference", reference)
    ds.setncattr("comment", comment)
    ds.setncattr("Conventions", conventions)

    print("✓ Set OpenSense-PWS global attributes")

    return ds


def save_pws_groups(stations_dict, output_file='pws_opensense.nc'):
    """
    Save dict of xarray Datasets as netCDF4 groups with global attributes.
    Cleans encoding conflicts before saving.
    """

    import netCDF4 as nc
    from pathlib import Path

    print(f"\n{'=' * 70}")
    print("SAVING PWS TO NETCDF4 GROUPS")
    print(f"{'=' * 70}\n")

    # Create file first
    ds = nc.Dataset(output_file, 'w', format='NETCDF4')

    # Set global attributes
    ds = set_global_attributes(ds)
    ds.close()

    # Add each station as group
    for i, (station_id, station_data) in enumerate(stations_dict.items(), 1):
        try:
            # Clean encoding conflicts
            station_clean = _plain_strings(station_data.copy(deep=True))

            # Remove conflicting attrs from time
            if 'time' in station_clean.coords:
                station_clean['time'].attrs.pop('units', None)
                station_clean['time'].attrs.pop('calendar', None)

            # Save as group
            station_clean.to_netcdf(
                output_file,
                mode='a',
                group=station_id,
                format='NETCDF4'
            )
            print(f"  [{i:2d}] ✓ {station_id}")
        except Exception as e:
            print(f"  [{i:2d}] ❌ {station_id}: {e}")
            return None

    file_size = Path(output_file).stat().st_size / 1e6
    print(f"\n✅ SAVED: {output_file} ({file_size:.1f} MB)")
    print(f"{'=' * 70}\n")

    return output_file


def _plain_strings(ds):
    """Object-dtype variables -> numpy str (pandas >= 3 yields Arrow-backed strings that
    netCDF4 cannot write). Values are unchanged; added for this port."""
    for name in list(ds.variables):
        if ds[name].dtype == object:
            fixed = ds[name].astype(str)
            ds = ds.assign_coords({name: fixed}) if name in ds.coords else ds.assign({name: fixed})
    return ds


# ---- pipeline (the notebook's cell order) ----

def convert(input_dir, metadata_csv, output_nc, start='2023-10-29', end='2024-07-01',
            drop_missing_rain: bool = True):
    """CSVs in `input_dir` + station metadata -> OpenSense PWS netCDF at `output_nc`.
    Returns (output path, {station: % missing rain} of dropped stations)."""
    with tempfile.TemporaryDirectory() as tmp:
        raw_nc = str(Path(tmp) / 'pws_wu.nc')
        ds = process_all_csv_files(input_dir=str(input_dir), metadata_csv=str(metadata_csv),
                                   output_path=raw_nc, save=True)
        if not ds:
            raise RuntimeError('CSV -> netCDF step failed (see log)')
        ds.close()
        ds = nc.Dataset(raw_nc, 'r')
        stations_xr = convert_groups_to_xarray_dict(ds)
        ds.close()
    stations = filter_and_rename_pws_stations(stations_xr, start_date=start, end_date=end)
    stations = {sid: align_pws_to_spec(d, sid) for sid, d in stations.items()}
    problematic = check_missing_rainfall(stations) if drop_missing_rain else {}
    stations = {k: v for k, v in stations.items() if k not in (problematic or {})}
    out = save_pws_groups(stations, str(output_nc))
    if out is None:
        raise RuntimeError('saving the groups failed (see log)')
    return Path(out), problematic or {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input_dir', help='folder of WU PWS CSVs')
    ap.add_argument('metadata_csv', help='station metadata (as data/netCDF/meta/wu_pws.csv)')
    ap.add_argument('output_nc')
    ap.add_argument('--start', default='2023-10-29')
    ap.add_argument('--end', default='2024-07-01')
    ap.add_argument('--keep-missing-rain', action='store_true',
                    help='do not drop stations with too much missing rain')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    convert(a.input_dir, a.metadata_csv, a.output_nc, a.start, a.end, not a.keep_missing_rain)


if __name__ == '__main__':
    main()
