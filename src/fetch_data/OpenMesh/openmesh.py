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
#   dataset/archived/openmesh/       - Downloaded zip files
#   dataset/archived/openmesh/extracted/ - Extracted as-is (organize=False) or docs/other (organize=True)
#   dataset/raw/openmesh/            - Extracted raw data (NetCDF)
#   dataset/meta/                    - Extracted metadata (CSV)
#   dataset/examples/                - Example notebooks

DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent.parent / "dataset"
DEFAULT_ARCHIVED_DIR = DEFAULT_DATA_DIR / "archived" / "openmesh"
DEFAULT_EXTRACTED_DIR = DEFAULT_ARCHIVED_DIR / "extracted"
DEFAULT_RAW_DIR = DEFAULT_DATA_DIR / "raw" / "openmesh"
DEFAULT_META_DIR = DEFAULT_DATA_DIR / "meta"
DEFAULT_EXAMPLES_DIR = DEFAULT_DATA_DIR / "examples"
DEFAULT_MAPS_DIR = DEFAULT_DATA_DIR / "meta" / "maps"

# PWS: only two files (both in raw/openmesh/)
PWS_SAMPLE_FILE = "pws_opensense_sample_jan.nc"
PWS_FULL_FILE = "pws_wu_os.nc"

ZENODO_PWS_WU_RECORD_ID = "17508286"
ZENODO_PWS_WU_URL = f"https://zenodo.org/records/{ZENODO_PWS_WU_RECORD_ID}/files/PWS_NYC_WU.zip?download=1"



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


    return zip_file


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

def extract_openmesh(zip_path=None, organize=True, verbose=True):
    """
    Extract OpenMesh ZIP and optionally organize files into proper locations.
    
    Default behavior (organize=True):
    - Raw data (*.nc) → dataset/raw/openmesh/
    - Metadata (*.csv) → dataset/meta/
    - Notebooks (*.ipynb) → dataset/examples/ (only if not already exists)
    - Maps (*.html) → dataset/meta/maps/
    - README.txt and any other unclassified files → dataset/archived/openmesh/extracted/
    
    As-is extraction (organize=False):
    - All files → dataset/archived/openmesh/extracted/
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
    
    # As-is extraction → archived/openmesh/extracted/
    if not organize:
        extract_dir = DEFAULT_EXTRACTED_DIR
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        if verbose:
            print(f"Extracting to: {extract_dir}")
            print()
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            members = zip_ref.namelist()
            
            with tqdm(total=len(members), desc="Extracting", disable=not verbose) as pbar:
                for member in members:
                    # Strip 'dataset/' prefix if present
                    if member.startswith('dataset/'):
                        target = member[8:]
                    else:
                        target = member
                    
                    if not target or member.endswith('/'):
                        pbar.update(1)
                        continue
                    
                    target_path = extract_dir / target
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_bytes(zip_ref.read(member))
                    pbar.update(1)
            
            if verbose:
                print()
                files = [m for m in members if not m.endswith('/')]
                total_size = sum(zip_ref.getinfo(m).file_size for m in files)
                print(f"✓ Extracted {len(files)} files ({total_size / 1e6:.1f} MB):")
                for m in files:
                    size_mb = zip_ref.getinfo(m).file_size / (1024 * 1024)
                    name = Path(m).name
                    print(f"    {name} ({size_mb:.1f} MB)")
        
        return {'extracted': extract_dir}
    
    # Organized extraction (default, recommended)
    DEFAULT_RAW_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_META_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_MAPS_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    
    results = {'raw': [], 'meta': [], 'examples': [], 'maps': [], 'extracted': []}
    existing = {'raw': [], 'meta': [], 'examples': [], 'maps': [], 'extracted': []}
    
    if verbose:
        print(f"Extracting: {zip_path.name}")
        print(f"  Raw data → {DEFAULT_RAW_DIR}")
        print(f"  Metadata → {DEFAULT_META_DIR}")
        print(f"  Examples → {DEFAULT_EXAMPLES_DIR} (skips if exists)")
        print(f"  Extracted (docs/other) → {DEFAULT_EXTRACTED_DIR}")
        print()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            members = zip_ref.namelist()
            
            with tqdm(total=len(members), desc="Extracting", disable=not verbose) as pbar:
                for member in members:
                    zip_ref.extract(member, temp_path)
                    pbar.update(1)
        
        for file in temp_path.rglob("*"):
            if not file.is_file():
                continue
            
            dest = None
            category = None
            
            if file.suffix == '.nc':
                dest = DEFAULT_RAW_DIR / file.name
                category = 'raw'
            
            elif file.suffix == '.csv':
                dest = DEFAULT_META_DIR / file.name
                category = 'meta'
            
            elif file.suffix == '.ipynb':
                dest = DEFAULT_EXAMPLES_DIR / file.name
                category = 'examples'
                if dest.exists():
                    existing[category].append(dest)
                    continue
            
            elif file.suffix == '.html':
                dest = DEFAULT_MAPS_DIR / file.name
                category = 'maps'
            
            else:
                # README.txt and any other unclassified files → archived/openmesh/extracted/
                dest = DEFAULT_EXTRACTED_DIR / file.name
                category = 'extracted'
                        
            if dest and category:
                if dest.exists():
                    existing[category].append(dest)
                else:
                    shutil.copy2(file, dest)
                    results[category].append(dest)
    
    if verbose:
        print()
        total_new = sum(len(v) for v in results.values())
        total_existing = sum(len(v) for v in existing.values())
        
        if total_new > 0:
            new_size = sum(p.stat().st_size for v in results.values() for p in v)
            print(f"✓ Extracted {total_new} new files ({new_size / 1e6:.1f} MB):")
            for files in results.values():
                for p in files:
                    size_mb = p.stat().st_size / (1024 * 1024)
                    print(f"    {p.name} ({size_mb:.1f} MB)")
        
        if total_existing > 0:
            exist_size = sum(p.stat().st_size for v in existing.values() for p in v)
            print(f"✓ Already exist: {total_existing} files ({exist_size / 1e6:.1f} MB):")
            for files in existing.values():
                for p in files:
                    size_mb = p.stat().st_size / (1024 * 1024)
                    print(f"    {p.name} ({size_mb:.1f} MB)")
        
        if total_new == 0 and total_existing == 0:
            print("✓ No files to extract")
    
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
    Tries dataset/meta/ first, then legacy meta/openmesh/ and links/.

    Parameters
    ----------
    meta_dir : Path, optional
        Metadata directory. Default: dataset/meta/

    Returns
    -------
    pandas.DataFrame
        Links metadata
    """
    base = DEFAULT_DATA_DIR
    candidates = [
        base / "meta" / "links_metadata.csv",
        base / "meta" / "openmesh" / "links_metadata.csv",  # legacy
        base / "links" / "links_metadata.csv",
    ]
    if meta_dir is not None:
        candidates.insert(0, Path(meta_dir) / "links_metadata.csv")
    csv_file = None
    for p in candidates:
        if p.exists():
            csv_file = p
            break
    if csv_file is None:
        raise FileNotFoundError(
            "links_metadata.csv not found. Check dataset/meta/."
        )
    return pd.read_csv(csv_file)




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
        True = pws_opensense_sample_jan.nc (from OpenMesh.zip)
        False = pws_wu_os.nc (requires download_pws_wu + extract_pws_wu)

    Returns
    -------
    dict
        Dictionary mapping station_id to xarray.Dataset
    """
    if raw_dir is None:
        raw_dir = DEFAULT_RAW_DIR
    raw_dir = Path(raw_dir)

    filename = PWS_SAMPLE_FILE if sample else PWS_FULL_FILE
    pws_file = raw_dir / filename

    if not pws_file.exists():
        raise FileNotFoundError(
            f"PWS file not found: {pws_file}\n"
            f"Sample: included in OpenMesh.zip\n"
            f"Full: run download_pws_wu() and extract_pws_wu() first"
        )

    print(f"Loading: {filename}")

    with nc.Dataset(pws_file, 'r') as nc_file:
        group_names = list(nc_file.groups.keys())

    pws_data = {}
    if group_names:
        for station_id in group_names:
            ds = xr.open_dataset(pws_file, group=station_id, engine='netcdf4')
            pws_data[station_id] = _normalize_pws_dataset(ds)
    else:
        ds_all = xr.open_dataset(pws_file, engine='netcdf4')
        pws_data = _pws_flat_to_per_station(ds_all, pws_file)
        ds_all.close()

    print(f"✓ Loaded {len(pws_data)} stations")
    return pws_data


def _normalize_pws_dataset(ds):
    """
    Ensure a single-station PWS xr.Dataset has a consistent interface for downstream:
    - coordinate 'time' (rename from 'datetime' or 't' if needed)
    - at least one of 'rainfall_amount' or 'rainfall_rate' (alias common names)
    """
    ds = ds.copy(deep=False)
    # Normalize time coordinate name
    for name in ['datetime', 't']:
        if name in ds.coords and 'time' not in ds.coords:
            ds = ds.rename({name: 'time'})
            break
    if 'time' not in ds.coords and 'time' not in ds.dims:
        for d in list(ds.dims):
            if d not in ('station', 'station_id', 'id') and ds.dims[d] > 1:
                ds = ds.rename({d: 'time'})
                break
    # Alias rainfall variable names so downstream always finds one
    for alias, preferred in [('precip', 'rainfall_amount'), ('rainfall', 'rainfall_amount'),
                             ('precipitation', 'rainfall_amount'), ('rainfall_mm', 'rainfall_amount')]:
        if alias in ds.data_vars and 'rainfall_amount' not in ds.data_vars:
            ds = ds.rename({alias: 'rainfall_amount'})
            break
    # Squeeze singleton dims so time and precip are 1D (e.g. from flat file per-station slice)
    ds = ds.squeeze()
    return ds


def _pws_flat_to_per_station(ds_all, pws_file):
    """
    Convert a flat PWS dataset (all stations in one Dataset with a station dimension)
    into the same format as group-based: dict[station_id, xr.Dataset] with normalized datasets.
    """
    station_dim = None
    for cand in ('station', 'station_id', 'id', 'sensor_id'):
        if cand in ds_all.dims or cand in ds_all.coords:
            station_dim = cand
            break
    if station_dim is None:
        raise ValueError(
            "PWS file has no groups and no station dimension. "
            "Expected one of: station, station_id, id, sensor_id. "
            f"Dimensions: {list(ds_all.dims)}; coords: {list(ds_all.coords)}."
        )
    if station_dim in ds_all.coords:
        station_ids = [str(x) for x in ds_all.coords[station_dim].values]
    else:
        station_ids = [str(i) for i in range(ds_all.dims[station_dim])]
    time_dim = None
    for name in ('time', 'datetime', 't'):
        if name in ds_all.dims or name in ds_all.coords:
            time_dim = name
            break
    if time_dim is None:
        for d in ds_all.dims:
            if d != station_dim and ds_all.dims[d] > 1:
                time_dim = d
                break
    if time_dim is None:
        raise ValueError("Could not find time dimension in flat PWS file.")
    pws_data = {}
    for i, station_id in enumerate(station_ids):
        sel = {station_dim: i if station_dim in ds_all.dims else station_id}
        ds_one = ds_all.isel(**sel).drop_vars([station_dim], errors='ignore')
        if time_dim != 'time':
            ds_one = ds_one.rename({time_dim: 'time'})
        ds_one = _normalize_pws_dataset(ds_one).load()
        pws_data[station_id] = ds_one
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



def download_pws_wu(archive_dir=None):
    """
    Download PWS Weather Underground dataset ZIP from Zenodo.
    
    Returns
    -------
    Path
        Path to downloaded ZIP file
    """
    if archive_dir is None:
        archive_dir = DEFAULT_ARCHIVED_DIR  # archived/openmesh/
    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)

    zip_file = archive_dir / "PWS_NYC_WU.zip"
    
    if not download_file(ZENODO_PWS_WU_URL, zip_file):
        return None
    
    print(f"✓ Downloaded: {zip_file}")
    print(f"Next: Run extract_pws_wu() to extract data")
    return zip_file


def extract_pws_wu(zip_path=None, raw_dir=None):
    """
    Extract pws_wu_os.nc (full PWS data) from PWS_NYC_WU.zip into raw/openmesh/.
    
    Parameters
    ----------
    zip_path : Path, optional
        Path to ZIP. Default: archived/openmesh/PWS_NYC_WU.zip
    raw_dir : Path, optional
        Output directory. Default: dataset/raw/openmesh/
    
    Returns
    -------
    Path
        Path to extracted NetCDF file (pws_wu_os.nc)
    """
    if zip_path is None:
        zip_path = DEFAULT_ARCHIVED_DIR / "PWS_NYC_WU.zip"
    if raw_dir is None:
        raw_dir = DEFAULT_RAW_DIR
    
    zip_path = Path(zip_path)
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    if not zip_path.exists():
        print(f"✗ ZIP not found: {zip_path}")
        print("  Run download_pws_wu() first.")
        return None
    
    output_path = raw_dir / PWS_FULL_FILE
    
    if output_path.exists():
        print(f"✓ Already extracted: {output_path}")
        return output_path
    
    print(f"Extracting {PWS_FULL_FILE}...")
    
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for name in zf.namelist():
            if name.endswith(PWS_FULL_FILE):
                data = zf.read(name)
                output_path.write_bytes(data)
                size_mb = len(data) / (1024 * 1024)
                print(f"✓ Extracted: {PWS_FULL_FILE} ({size_mb:.1f} MB) → {raw_dir}")
                return output_path
    
    print(f"✗ {PWS_FULL_FILE} not found in ZIP")
    return None




def run_pws_wu_pipeline():
    """Download PWS_NYC_WU.zip, extract pws_wu_os.nc, and load. Returns load_pws(sample=False)."""
    zip_path = download_pws_wu()
    if zip_path is None:
        return None
    nc_path = extract_pws_wu()
    if nc_path is None:
        return None
    return load_pws(sample=False)
