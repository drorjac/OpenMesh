"""
OpenMesh Dataset Tools

Functions to download, extract, and load the OpenMesh dataset from Zenodo.
"""

import requests
import zipfile
from pathlib import Path
import xarray as xr
import pandas as pd
import netCDF4 as nc
import matplotlib.pyplot as plt
from tqdm.auto import tqdm
import numpy as np

# =============================================================================
# Configuration
# =============================================================================

ZENODO_RECORD_ID = "15287692"
ZENODO_URL = f"https://zenodo.org/records/{ZENODO_RECORD_ID}/files/OpenMesh.zip?download=1"

# Default paths (relative to project root)
# Structure:
#   dataset/archived/openmesh/  - Downloaded zip files
#   dataset/raw/openmesh/       - Extracted raw data (NetCDF)
#   dataset/meta/openmesh/      - Extracted metadata (CSV)
#   dataset/examples/           - Example notebooks

DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent.parent / "dataset"
DEFAULT_ARCHIVED_DIR = DEFAULT_DATA_DIR / "archived" / "openmesh"
DEFAULT_RAW_DIR = DEFAULT_DATA_DIR / "raw" / "openmesh"
DEFAULT_META_DIR = DEFAULT_DATA_DIR / "meta" / "openmesh"
DEFAULT_EXAMPLES_DIR = DEFAULT_DATA_DIR / "examples"
DEFAULT_MAPS_DIR = DEFAULT_DATA_DIR / "meta" / "maps"


# =============================================================================
# Download Functions
# =============================================================================

def download_file(url, output_path, chunk_size=8192):
    """
    Download a file with progress bar
    """
    output_path = Path(output_path)

    if output_path.exists():
        print(f"✓ File already exists: {output_path.name}")
        return True

    print(f"Downloading from Zenodo...")

    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'wb') as f:
            with tqdm(total=total_size, unit='B', unit_scale=True, desc=output_path.name) as pbar:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))

        print(f"✓ Download complete: {output_path.name}")
        return True

    except Exception as e:
        print(f"✗ Download failed: {e}")
        if output_path.exists():
            output_path.unlink()
        return False


def extract_zip(zip_path, extract_to):
    """
    Extract ZIP archive with progress.
    Strips 'dataset/' prefix from ZIP paths.
    """
    zip_path = Path(zip_path)
    extract_to = Path(extract_to)

    # Check if main data file already exists (in new or old structure)
    if (extract_to / "ds_openmesh.nc").exists() or (extract_to / "links" / "ds_openmesh.nc").exists():
        print(f"✓ Data already extracted to: {extract_to}")
        return True

    print(f"Extracting {zip_path.name}...")

    extracted = 0
    overwritten = 0

    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            members = zip_ref.namelist()

            with tqdm(total=len(members), desc="Extracting") as pbar:
                for member in members:
                    # Strip 'dataset/' prefix if present
                    if member.startswith('dataset/'):
                        target = member[8:]  # remove 'dataset/'
                    else:
                        target = member

                    if not target:  # skip empty (the dataset/ folder itself)
                        pbar.update(1)
                        continue

                    target_path = extract_to / target

                    if member.endswith('/'):
                        target_path.mkdir(parents=True, exist_ok=True)
                    else:
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        if target_path.exists():
                            overwritten += 1
                        else:
                            extracted += 1
                        with zip_ref.open(member) as src:
                            target_path.write_bytes(src.read())

                    pbar.update(1)

        print(f"✓ Extraction complete: {extracted} new files")
        if overwritten > 0:
            print(f"  (overwrote {overwritten} existing files)")
        return True

    except Exception as e:
        print(f"✗ Extraction failed: {e}")
        return False


def download_openmesh(archive_dir=None):
    """
    Download the OpenMesh dataset ZIP from Zenodo.
    
    Downloads to: dataset/archived/openmesh/OpenMesh.zip
    
    Use extract_openmesh() to extract and organize files.

    Parameters
    ----------
    archive_dir : Path, optional
        Directory to save ZIP. Default: dataset/archived/openmesh/

    Returns
    -------
    Path
        Path to the downloaded ZIP file

    Example
    -------
    >>> zip_path = download_openmesh()
    >>> extract_openmesh()  # Extract and organize
    """
    if archive_dir is None:
        archive_dir = DEFAULT_ARCHIVED_DIR
    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)

    zip_file = archive_dir / "OpenMesh.zip"

    print(f"Archive directory: {archive_dir.absolute()}")

    # Download
    if not download_file(ZENODO_URL, zip_file):
        return None

    file_size_mb = zip_file.stat().st_size / (1024 * 1024)
    print(f"✓ File size: {file_size_mb:.2f} MB")
    print(f"\nNext: Run extract_openmesh() to extract and organize files")

    return zip_file


def extract_openmesh(zip_path=None, organize=True, verbose=True):
    """
    Extract OpenMesh ZIP and optionally organize files into proper locations.
    
    Default behavior (organize=True):
    - Raw data (*.nc) → dataset/raw/openmesh/
    - Metadata (*.csv) → dataset/meta/openmesh/
    - Notebooks (*.ipynb) → dataset/examples/ (only if not already exists)
    - Maps (*.html) → dataset/meta/maps/
    
    As-is extraction (organize=False):
    - All files extracted to same folder as ZIP (dataset/archived/openmesh/)
    - Note: Not recommended - files will be mixed together

    Parameters
    ----------
    zip_path : Path, optional
        Path to ZIP file. Default: dataset/archived/openmesh/OpenMesh.zip
    organize : bool, default True
        If True, organize files into proper locations. If False, extract as-is.
        Note: organize=False is not recommended - files will be mixed together.
    verbose : bool, default True
        Print progress messages

    Returns
    -------
    dict
        Dictionary with paths to extracted files by category
    """
    import shutil
    import tempfile
    
    if zip_path is None:
        zip_path = DEFAULT_ARCHIVED_DIR / "OpenMesh.zip"
    zip_path = Path(zip_path)
    
    if not zip_path.exists():
        print(f"✗ ZIP not found: {zip_path}")
        print("  Run download_openmesh() first.")
        return None
    
    # As-is extraction (not recommended)
    if not organize:
        extract_dir = zip_path.parent
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        if verbose:
            print(f"⚠ Extracting as-is to: {extract_dir}")
            print("  Note: Files will be mixed together (not recommended)")
            print()
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            members = zip_ref.namelist()
            with tqdm(total=len(members), desc="Extracting", disable=not verbose) as pbar:
                for member in members:
                    zip_ref.extract(member, extract_dir)
                    pbar.update(1)
        
        if verbose:
            print(f"✓ Extracted {len(members)} files to {extract_dir}")
        
        return {'extracted': extract_dir}
    
    # Organized extraction (default, recommended)
    # Create output directories
    DEFAULT_RAW_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_META_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_MAPS_DIR.mkdir(parents=True, exist_ok=True)
    
    results = {'raw': [], 'meta': [], 'examples': [], 'maps': [], 'other': []}
    existing = {'raw': [], 'meta': [], 'examples': [], 'maps': [], 'other': []}  # Track existing files by category
    
    if verbose:
        print(f"Extracting: {zip_path.name}")
        print(f"  Raw data → {DEFAULT_RAW_DIR}")
        print(f"  Metadata → {DEFAULT_META_DIR}")
        print(f"  Examples → {DEFAULT_EXAMPLES_DIR} (skips if exists)")
        print()
    
    # Extract to temp directory first
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Extract ZIP
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            members = zip_ref.namelist()
            
            with tqdm(total=len(members), desc="Extracting", disable=not verbose) as pbar:
                for member in members:
                    zip_ref.extract(member, temp_path)
                    pbar.update(1)
        
        # Find and organize files
        for file in temp_path.rglob("*"):
            if not file.is_file():
                continue
            
            dest = None
            category = None
            
            # Raw data (NetCDF)
            if file.suffix == '.nc':
                dest = DEFAULT_RAW_DIR / file.name
                category = 'raw'
            
            # Metadata CSVs
            elif file.suffix == '.csv':
                dest = DEFAULT_META_DIR / file.name
                category = 'meta'
            
            # Example notebooks (NEVER overwrite existing)
            elif file.suffix == '.ipynb':
                dest = DEFAULT_EXAMPLES_DIR / file.name
                category = 'examples'
                # Skip if already exists (don't replace user's notebooks)
                if dest.exists():
                    existing[category].append(dest)
                    if verbose:
                        print(f"  ⊘ {file.name} (notebook exists - not replaced)")
                    continue
            
            # HTML maps
            elif file.suffix == '.html':
                dest = DEFAULT_MAPS_DIR / file.name
                category = 'maps'
            
            # README
            elif file.name == 'README.txt':
                dest = DEFAULT_DATA_DIR / file.name
                category = 'other'
            
            # Copy file if doesn't exist
            if dest and category:
                if dest.exists():
                    existing[category].append(dest)
                else:
                    shutil.copy2(file, dest)
                    results[category].append(dest)
                    if verbose:
                        size_mb = file.stat().st_size / (1024 * 1024)
                        print(f"  ✓ {file.name} ({size_mb:.1f} MB) → {dest.parent.name}/")
    
    if verbose:
        print()
        total_new = sum(len(v) for v in results.values())
        total_existing = sum(len(v) for v in existing.values())
        
        if total_new > 0:
            print(f"✓ Extracted {total_new} NEW files:")
            if results['raw']:
                print(f"  Raw:      {len(results['raw'])} → raw/openmesh/")
            if results['meta']:
                print(f"  Metadata: {len(results['meta'])} → meta/openmesh/")
            if results['examples']:
                print(f"  Examples: {len(results['examples'])} → examples/")
            if results['maps']:
                print(f"  Maps:     {len(results['maps'])} → meta/maps/")
            if existing['examples']:
                print(f"  Skipped:  {len(existing['examples'])} existing notebooks (not replaced)")
        
        if total_existing > 0:
            if total_new > 0:
                print()
            print(f"✓ Already exist ({total_existing} files):")
            if existing['raw']:
                names = [p.name for p in existing['raw']]
                print(f"  raw/openmesh/: {', '.join(names)}")
            if existing['meta']:
                names = [p.name for p in existing['meta']]
                print(f"  meta/openmesh/: {', '.join(names)}")
            if existing['examples']:
                names = [p.name for p in existing['examples']]
                print(f"  examples/: {', '.join(names)}")
            if existing['maps']:
                names = [p.name for p in existing['maps']]
                print(f"  meta/maps/: {', '.join(names)}")
            if existing['other']:
                names = [p.name for p in existing['other']]
                print(f"  dataset/: {', '.join(names)}")
        
        if total_new == 0 and total_existing == 0:
            print("✓ No files to extract")
    
    # Return clean summary (just file names, not full paths)
    output = {}
    if any(results.values()):
        output['extracted'] = {k: [p.name for p in v] for k, v in results.items() if v}
    if any(existing.values()):
        output['existing'] = {k: [p.name for p in v] for k, v in existing.items() if v}
    
    return output if output else None


# =============================================================================
# Load Functions
# =============================================================================

def load_links(raw_dir=None):
    """
    Load the microwave links dataset.

    Parameters
    ----------
    raw_dir : Path, optional
        Raw data directory. Default: dataset/raw/openmesh/

    Returns
    -------
    xarray.Dataset
        Links dataset
    """
    if raw_dir is None:
        raw_dir = DEFAULT_RAW_DIR
    raw_dir = Path(raw_dir)

    # New structure: dataset/raw/openmesh/ds_openmesh.nc
    links_file = raw_dir / "ds_openmesh.nc"
    
    # Fallback: check old locations
    if not links_file.exists():
        links_file = DEFAULT_DATA_DIR / "links" / "ds_openmesh.nc"
    if not links_file.exists():
        links_file = DEFAULT_DATA_DIR / "raw" / "openmesh" / "links" / "ds_openmesh.nc"

    if not links_file.exists():
        raise FileNotFoundError(
            f"Links file not found.\n"
            f"Expected: {DEFAULT_RAW_DIR / 'ds_openmesh.nc'}\n"
            f"Run download_openmesh() and extract_openmesh() first."
        )

    ds = xr.open_dataset(links_file)
    print(f"✓ Loaded links data: {links_file}")
    return ds


def load_links_metadata(meta_dir=None):
    """
    Load CML links metadata.

    Parameters
    ----------
    meta_dir : Path, optional
        Metadata directory. Default: dataset/meta/openmesh/

    Returns
    -------
    pandas.DataFrame
        Links metadata
    """
    if meta_dir is None:
        meta_dir = DEFAULT_META_DIR
    meta_dir = Path(meta_dir)

    # New structure: dataset/meta/openmesh/links_metadata.csv
    csv_file = meta_dir / "links_metadata.csv"
    
    # Fallback: check old locations
    if not csv_file.exists():
        csv_file = DEFAULT_DATA_DIR / "meta" / "links_metadata.csv"
    if not csv_file.exists():
        csv_file = DEFAULT_DATA_DIR / "links" / "links_metadata.csv"
    
    return pd.read_csv(csv_file)


# Backwards compatibility alias
load_metadata = load_links_metadata


def print_summary(ds):
    """Print dataset summary."""
    print("=" * 60)
    print(f"Dataset: {ds.attrs.get('title', 'N/A')}")
    print("=" * 60)
    print(f"\nTime range: {ds.time.min().values} to {ds.time.max().values}")
    if 'cml_id' in ds.dims:
        print(f"Number of links: {len(ds.cml_id)}")
    if 'sublink_id' in ds.dims:
        print(f"Number of sublinks: {len(ds.sublink_id)}")
    print(f"Number of timesteps: {len(ds.time)}")
    print(f"Temporal resolution: {pd.Timedelta(ds.time.diff('time').median().values)}")


def load_pws(raw_dir=None, sample=True):
    """
    Load PWS (Personal Weather Stations) dataset.

    Parameters
    ----------
    raw_dir : Path, optional
        Raw data directory. Default: dataset/raw/openmesh/
    sample : bool, default True
        If True, load sample file (Jan 2024). If False, load full file.

    Returns
    -------
    dict
        Dictionary mapping station_id to xarray.Dataset

    Examples
    --------
    >>> # Load sample (2 weeks: Jan 15-30, 2024)
    >>> pws_data = load_pws(sample=True)
    
    >>> # Load full dataset (Oct 2023 - Jul 2024)
    >>> pws_data = load_pws(sample=False)
    """
    if raw_dir is None:
        raw_dir = DEFAULT_RAW_DIR
    raw_dir = Path(raw_dir)

    filename = "pws_opensense_sample_jan.nc" if sample else "pws_opensense_os.nc"
    
    # New structure: dataset/raw/openmesh/pws_opensense_os.nc
    pws_file = raw_dir / filename
    
    # Fallback: check old locations
    if not pws_file.exists():
        pws_file = DEFAULT_DATA_DIR / "weather_station" / "samples" / filename
    if not pws_file.exists():
        pws_file = DEFAULT_DATA_DIR / "raw" / "openmesh" / filename

    if not pws_file.exists():
        raise FileNotFoundError(
            f"PWS file not found.\n"
            f"Expected: {DEFAULT_RAW_DIR / filename}\n"
            f"Run download_openmesh() and extract_openmesh() first."
        )

    print(f"Loading PWS data: {pws_file.name}")

    # Get station groups
    with nc.Dataset(pws_file, 'r') as nc_file:
        station_ids = list(nc_file.groups.keys())

    # Load each station
    pws_data = {}
    for station_id in station_ids:
        ds = xr.open_dataset(pws_file, group=station_id, engine='netcdf4')
        pws_data[station_id] = ds

    print(f"✓ Loaded {len(pws_data)} stations")
    return pws_data


def pws_to_dataframe(pws_data, station_id=None):
    """
    Convert PWS data to pandas DataFrame.

    Parameters
    ----------
    pws_data : dict
        PWS data from load_pws()
    station_id : str, optional
        Station to extract. If None, uses first station.

    Returns
    -------
    pandas.DataFrame
        DataFrame with time index and rainfall column
    """
    if station_id is None:
        station_id = list(pws_data.keys())[0]

    ds = pws_data[station_id]

    # Get rainfall variable (could be 'rainfall_amount' or 'rainfall_rate')
    if 'rainfall_amount' in ds:
        rainfall = ds['rainfall_amount'].values
    elif 'rainfall_rate' in ds:
        rainfall = ds['rainfall_rate'].values
    else:
        raise ValueError(f"No rainfall variable found. Available: {list(ds.data_vars)}")

    df = pd.DataFrame({
        'rainfall_mm': rainfall
    }, index=pd.to_datetime(ds.time.values))

    return df


def list_pws_stations(pws_data):
    """List all PWS station IDs and their record counts."""
    print(f"PWS Stations ({len(pws_data)} total):")
    for station_id, ds in pws_data.items():
        print(f"  {station_id}: {len(ds.time)} records")


def plot_pws_precipitation(pws_data, station_ids=None, max_stations=5, figsize=(12, 4)):
    """
    Plot precipitation time series for PWS stations.
    
    Parameters
    ----------
    pws_data : dict
        PWS data from load_pws()
    station_ids : list, optional
        List of station IDs to plot. If None, plots first stations (up to max_stations).
    max_stations : int, default 5
        Maximum number of stations to plot if station_ids is None.
    figsize : tuple, default (12, 4)
        Figure size (width, height).
    
    Examples
    --------
    >>> pws_data = load_pws(sample=True)
    >>> plot_pws_precipitation(pws_data, station_ids=['KNYNEWYO1805'])
    >>> plot_pws_precipitation(pws_data, max_stations=3)  # Plot first 3 stations
    """
    if station_ids is None:
        station_ids = list(pws_data.keys())[:max_stations]
    
    if len(station_ids) == 0:
        print("No stations to plot")
        return
    
    fig, ax = plt.subplots(figsize=figsize)
    
    colors = plt.cm.tab10.colors
    for i, station_id in enumerate(station_ids):
        if station_id not in pws_data:
            print(f"⚠ Station {station_id} not found in data")
            continue
        
        ds = pws_data[station_id]
        
        # Use rainfall_amount if available, otherwise rainfall_rate
        if 'rainfall_amount' in ds:
            precip = ds['rainfall_amount']
            label = f"{station_id} (amount, mm)"
        elif 'rainfall_rate' in ds:
            precip = ds['rainfall_rate']
            label = f"{station_id} (rate, mm/h)"
        else:
            print(f"⚠ No precipitation variable found for {station_id}")
            continue
        
        ax.plot(ds.time.values, precip.values, 
                color=colors[i % len(colors)], 
                label=label, 
                alpha=0.7, 
                linewidth=1)
    
    ax.set_xlabel("Time")
    ax.set_ylabel("Precipitation (mm)" if 'rainfall_amount' in ds else "Precipitation (mm/h)")
    ax.set_title(f"PWS Precipitation Time Series ({len(station_ids)} stations)")
    ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.show()


def plot_links_scatter(ds,
                       highlight_ids=None,        # list of cml_ids to highlight
                       highlight_pairs=None,      # list of (cml_id, sublink_id) tuples
                       length_range=None,         # (min, max) meters
                       freq_range=None,           # (min, max) GHz
                       sublink=None,              # 'sublink_1', 'sublink_2', etc.
                       return_filtered=False):    # return filtered cml_id, sublink pairs
    """
    Scatter plot of Frequency vs Length for NYC Mesh Network.
    """
    fig, ax = plt.subplots(figsize=(10, 7))

    all_points = []

    sublinks = [sublink] if sublink else ds.sublink_id.values

    for cml_id in ds.cml_id.values:
        for sl in sublinks:
            freq_mhz = float(ds['frequency'].sel(cml_id=cml_id, sublink_id=sl).values)
            freq_ghz = freq_mhz / 1000  # MHz to GHz
            length_m = float(ds['length'].sel(cml_id=cml_id).values)

            if np.isnan(freq_mhz):
                continue

            # Check if matches filter
            matches = False
            if highlight_ids or highlight_pairs or length_range or freq_range:
                matches = True
                if length_range and not (length_range[0] <= length_m <= length_range[1]):
                    matches = False
                if freq_range and not (freq_range[0] <= freq_ghz <= freq_range[1]):
                    matches = False
                if highlight_ids and cml_id not in highlight_ids:
                    matches = False
                if highlight_pairs and (cml_id, sl) not in highlight_pairs:
                    matches = False

            all_points.append((length_m, freq_ghz, cml_id, sl, matches))

    matched = [(l, f, c, s) for l, f, c, s, m in all_points if m]
    filter_active = highlight_ids or highlight_pairs or length_range or freq_range

    # Plot all in blue
    ax.scatter([p[1] for p in all_points], [p[0] for p in all_points],
               s=120, alpha=0.6, c='steelblue', edgecolors='darkblue',
               linewidth=0.5, label='NYC Mesh Network', zorder=1)

    # Overlay selected
    if filter_active and matched:
        from collections import Counter
        position_counts = Counter([(l, f) for l, f, c, s in matched])

        single = [(l, f) for (l, f), count in position_counts.items() if count == 1]
        dual = [(l, f) for (l, f), count in position_counts.items() if count >= 2]

        if single:
            ax.scatter([p[1] for p in single], [p[0] for p in single],
                       s=150, alpha=0.9, c='red', edgecolors='darkred',
                       linewidth=1, label='Selected', zorder=2)

        if dual:
            ax.scatter(
                [p[1] for p in dual],
                [p[0] for p in dual],
                s=150,
                alpha=0.9,
                c='red',
                edgecolors='black',          # <- black frame
                linewidth=1.5,               # <- thinner than before
                label='Selected (bidirectional)' if single else 'Selected',
                zorder=3
            )


    ax.set_xlabel("Frequency (GHz)", fontsize=14)
    ax.set_ylabel("Length (m)", fontsize=14)
    # ax.set_title("NYC Mesh Network - Link Characteristics", fontsize=16, fontweight='bold')
    ax.tick_params(axis='both', labelsize=12)
    ax.grid(True, alpha=0.3, linestyle='--')
    ax.legend(loc='upper left', fontsize=12)

    # Stats - move to bottom left since legend is top left
    stats_text = f"Total: {len(all_points)} sublinks"
    if filter_active:
        stats_text += f" | Selected: {len(matched)}"
    ax.text(0.02, 0.02, stats_text, transform=ax.transAxes, fontsize=12, va='bottom',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    plt.tight_layout()
    plt.show()

    if return_filtered:
        filtered_data = []
        for l, f, c, s in matched:
            filtered_data.append({
                'link_id': c,
                'sublink_id': s,
                'length_m': l,
                'freq_ghz': f
            })
        return pd.DataFrame(filtered_data)




def close_datasets(ds_links=None, pws_data=None):
    """
    Close xarray datasets to release file handles.
    
    Parameters
    ----------
    ds_links : xarray.Dataset, optional
        Links dataset from load_links()
    pws_data : dict, optional
        PWS data dictionary from load_pws()
    
    Examples
    --------
    >>> ds_links = load_links()
    >>> pws_data = load_pws()
    >>> # ... do analysis ...
    >>> close_datasets(ds_links, pws_data)
    
    >>> # Or close individually
    >>> close_datasets(ds_links=ds_links)
    >>> close_datasets(pws_data=pws_data)
    """
    closed_count = 0
    
    if ds_links is not None:
        try:
            ds_links.close()
            print("✓ Links dataset closed")
            closed_count += 1
        except Exception as e:
            print(f"⚠ Could not close links dataset: {e}")
    
    if pws_data is not None:
        try:
            for station_id, ds in pws_data.items():
                ds.close()
            print(f"✓ PWS datasets closed ({len(pws_data)} stations)")
            closed_count += len(pws_data)
        except Exception as e:
            print(f"⚠ Could not close PWS datasets: {e}")
    
    if closed_count == 0:
        print("ℹ No datasets to close")
    
    return closed_count


# =============================================================================
# Pipeline Wrapper Functions (for main.py)
# =============================================================================

def run_openmesh_pipeline(verbose=True):
    """
    Complete OpenMesh pipeline: download and extract.
    
    Wrapper function for use in main.py or scripts.
    
    Parameters
    ----------
    verbose : bool, default True
        Print progress messages
    
    Returns
    -------
    dict or None
        Results from extract_openmesh() or None if download failed
    """
    zip_path = download_openmesh()
    if zip_path is None:
        return None
    
    result = extract_openmesh(zip_path, verbose=verbose)
    return result

