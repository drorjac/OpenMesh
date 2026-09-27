"""
Convert an OpenMesh CML dataset (xarray, dims cml_id × sublink_id × time with rsl and
link metadata) to OpenSense-CML-v1.0 — the converter behind the published Zenodo
file `ds_openmesh.nc` (record 15287692, dataset/raw/openmesh/ds_openmesh.nc).
DEFAULT OpenSense CML converter of this project.

Ported from ~/PycharmProjects/OpenMesh/data/netCDF/temp.py (`convert_to_opensense_cml`
and its steps; plotting helpers left out), driven there by read_os_example.ipynb.
Steps: collapse per-sublink site coordinates to per-cml, fill empty polarization with
'v', add OpenSense attributes, move link metadata to coordinates, reorder, set the
global attributes, save.

For the streaming full-record builder (raw nycmesh_data_*.nc + link table, used for
the 2023-2026 paper file) use `nycmesh_to_opensense_cml.py`.

Usage (CLI):
    python openmesh_to_opensense_cml.py <input.nc> <output.nc> [--encoded]
Usage (import):
    from openmesh_to_opensense_cml import convert_to_opensense_cml
    ds_os = convert_to_opensense_cml(ds_openmesh, "ds_openmesh.nc")
"""
import argparse
from pathlib import Path

import xarray as xr


def collapse_dimensions(ds):
    """Collapse (cml_id, sublink_id) → (cml_id) for site coordinates"""
    coords_to_collapse = [
        'site_0_lat', 'site_0_lon', 'site_0_elev', 'site_0_alt',
        'site_1_lat', 'site_1_lon', 'site_1_elev', 'site_1_alt',
        'length'
    ]

    for var in coords_to_collapse:
        if var in ds.data_vars and 'sublink_id' in ds[var].dims:
            ds[var] = ds[var].isel(sublink_id=0, drop=True)
            print(f"✓ Collapsed '{var}': (cml_id, sublink_id) → (cml_id)")

    return ds


def fill_polarization_gaps(ds):
    """Fill empty polarization values with 'v'"""
    if 'polarization' in ds.data_vars:
        polarization_data = ds['polarization'].values
        polarization_data[polarization_data == ''] = 'v'
        ds['polarization'].values = polarization_data
        print("✓ Filled polarization empty values with 'v'")

    return ds


def add_cml_attributes(ds):
    """Add OpenSense CML attributes to coordinates and variables"""

    dict_attributes = {
        "time": {"long_name": "time_utc"},
        "cml_id": {"long_name": "commercial_microwave_link_identifier"},
        'sublink_id': {"long_name": "sublink_identifier"},
        'site_0_lat': {
            "units": "degrees_in_WGS84_projection",
            "long_name": "site_0_latitude",
        },
        'site_0_lon': {
            "units": "degrees_in_WGS84_projection",
            "long_name": "site_0_longitude",
        },
        'site_0_elev': {
            "units": "metres_above_sea",
            "long_name": "ground_elevation_above_sea_level_at_site_0",
        },
        'site_0_alt': {
            "units": "metres_above_sea",
            "long_name": "antenna_altitude_above_sea_level_at_site_0",
        },
        'site_1_lat': {
            "units": "degrees_in_WGS84_projection",
            "long_name": "site_1_latitude",
        },
        'site_1_lon': {
            "units": "degrees_in_WGS84_projection",
            "long_name": "site_1_longitude",
        },
        'site_1_elev': {
            "units": "metres_above_sea",
            "long_name": "ground_elevation_above_sea_level_at_site_1",
        },
        'site_1_alt': {
            "units": "metres_above_sea",
            "long_name": "antenna_altitude_above_sea_level_at_site_1",
        },
        'length': {
            "units": "m",
            "long_name": "distance_between_pair_of_antennas",
        },
        'frequency': {
            "units": "MHz",
            "long_name": "sublink_frequency",
        },
        'rsl': {
            "units": "dBm",
            "long_name": "received_signal_level",
        },
        'polarization': {
            "units": "no units",
            "long_name": "sublink_polarization",
        }
    }

    # Add attributes
    for var_name, attrs in dict_attributes.items():
        if var_name in ds.variables:
            for attr_key, attr_val in attrs.items():
                ds[var_name].attrs[attr_key] = attr_val
            print(f"✓ Added attributes to '{var_name}'")

    return ds


def set_coordinates(ds):
    """Move auxiliary variables to coordinates section"""

    coords_to_set = [
        'site_0_lat', 'site_0_lon', 'site_0_elev', 'site_0_alt',
        'site_1_lat', 'site_1_lon', 'site_1_elev', 'site_1_alt',
        'length', 'frequency', 'polarization'
    ]

    for var_name in coords_to_set:
        if var_name in ds.data_vars:
            ds = ds.set_coords(var_name)
            print(f"✓ Moved '{var_name}' to coordinates")

    return ds


def reorder_coordinates(ds):
    """Reorder coordinates per OpenSense convention"""

    coords_final_order = [
        'time', 'cml_id', 'sublink_id',
        'site_0_lat', 'site_0_lon', 'site_0_elev', 'site_0_alt',
        'site_1_lat', 'site_1_lon', 'site_1_elev', 'site_1_alt',
        'length', 'frequency', 'polarization'
    ]

    # Filter to only existing coordinates
    coords_final_order = [c for c in coords_final_order if c in ds.coords]

    # Reorder
    ds = ds[coords_final_order + sorted(set(ds.data_vars))]
    print("✓ Reordered coordinates per OpenSense spec")

    return ds


def set_global_attributes(ds,
                         title="OpenMesh",
                         file_authors="Dror Jacoby",
                         institution="Cellular Environmental Monitoring (CellEnMon) Lab, School of Electrical Engineering, Tel-Aviv University; Wireless and Mobile Networking (WiMNet) Lab, Department of Electrical Engineering, Columbia University",
                         date="2025-11-01",
                         source="Community NYC Mesh Wireless Network",
                         history="2025-11-01: Updated metadata, converted netCDF → OpenSense-1.0 CML format",
                         naming_convention="OpenSense-1.0",
                         license_restrictions="CC BY 4.0 – https://creativecommons.org/licenses/by/4.0/",
                         reference="https://doi.org/10.5281/zenodo.15287692",
                         comment="OpenMesh: Wireless Signal Dataset for Opportunistic Urban Weather Sensing in New York City. Data covers the period 2023-10-29 to 2024-07-01 (UTC). All timestamps are in UTC. Signal levels are in dBm. This dataset is described in the associated publication: https://essd.copernicus.org/preprints/essd-2025-238/",
                         conventions="OpenSense-CML-v1.0"):
    """Set ONLY OpenSense-required global attributes"""

    # Clear all existing attributes
    ds.attrs.clear()

    # Set required attributes (with netCDF-safe names)
    ds.attrs["title"] = title
    ds.attrs["file_author"] = file_authors
    ds.attrs["institution"] = institution
    ds.attrs["date"] = date
    ds.attrs["source"] = source
    ds.attrs["history"] = history
    ds.attrs["naming_convention"] = naming_convention
    ds.attrs["license_restrictions"] = license_restrictions
    ds.attrs["reference"] = reference
    ds.attrs["comment"] = comment
    ds.attrs["Conventions"] = conventions

    print("✓ Set global attributes (OpenSense-required only)")

    return ds


def print_summary(ds):
    """Print dataset summary"""
    print("\n" + "="*80)
    print("CONVERSION SUMMARY")
    print("="*80)
    print(f"\nCoordinates ({len(ds.coords)}):")
    for coord in ds.coords:
        dims = ds[coord].dims
        print(f"  • {coord:25s} {str(dims)}")

    print(f"\nData variables ({len(ds.data_vars)}):")
    for var in ds.data_vars:
        dims = ds[var].dims
        size_mb = ds[var].nbytes / 1e6
        print(f"  • {var:25s} {str(dims):45s} {size_mb:7.1f} MB")

    print(f"\nGlobal attributes ({len(ds.attrs)}):")
    for key in sorted(ds.attrs.keys()):
        val_str = str(ds.attrs[key])[:60] + "..." if len(str(ds.attrs[key])) > 60 else str(ds.attrs[key])
        print(f"  • {key:25s}: {val_str}")

    print("="*80 + "\n")


def convert_to_opensense_cml(ds_input, output_file=None, save="notebook"):
    """
    Complete conversion workflow: OpenMesh → OpenSense CML v1.0

    Parameters:
    -----------
    ds_input : xarray.Dataset
        Input dataset (original OpenMesh data)
    output_file : str
        Output filename (None: return the dataset only)
    save : "notebook" (default) — plain `to_netcdf`, exactly how the published
        Zenodo file was written (read_os_example.ipynb); "encoded" — this function's
        own compressed encoding (rsl zlib 5, int64 time).

    Returns:
    --------
    xarray.Dataset
        Converted dataset (also saved to file)
    """

    print("\n" + "="*80)
    print("OPENMESH → OPENSENSE CML v1.0 CONVERSION")
    print("="*80 + "\n")

    # Copy to avoid modifying original
    ds = ds_input.copy(deep=True)

    # Step 1: Collapse dimensions
    print("STEP 1: Collapse dimensions")
    print("-" * 80)
    ds = collapse_dimensions(ds)

    # Step 2: Fill polarization gaps
    print("\nSTEP 2: Fill polarization gaps")
    print("-" * 80)
    ds = fill_polarization_gaps(ds)

    # Step 3: Add CML attributes
    print("\nSTEP 3: Add CML attributes")
    print("-" * 80)
    ds = add_cml_attributes(ds)

    # Step 4: Set coordinates
    print("\nSTEP 4: Set coordinates")
    print("-" * 80)
    ds = set_coordinates(ds)

    # Step 5: Reorder coordinates
    print("\nSTEP 5: Reorder coordinates")
    print("-" * 80)
    ds = reorder_coordinates(ds)

    # Step 6: Set global attributes
    print("\nSTEP 6: Set global attributes")
    print("-" * 80)
    ds = set_global_attributes(ds)

    # Step 7: Print summary
    print("\nSTEP 7: Dataset summary")
    print("-" * 80)
    print_summary(ds)

    # Step 8: Save
    print("STEP 8: Saving to file")
    print("-" * 80)

    encoding = {
        'time': {'units': 'seconds since 1970-01-01 00:00:00 UTC', 'dtype': 'int64'},
        'cml_id': {'dtype': 'int32'},
        'sublink_id': {'dtype': object},
        'rsl': {'zlib': True, 'complevel': 5, 'dtype': 'float32'},
        'frequency': {'dtype': 'float32'},
        'polarization': {'dtype': object},
        'site_0_lat': {'dtype': 'float32'},
        'site_0_lon': {'dtype': 'float32'},
        'site_1_lat': {'dtype': 'float32'},
        'site_1_lon': {'dtype': 'float32'},
        'length': {'dtype': 'float32'}
    }
    if output_file:
        ds = _plain_strings(ds)
        try:
            if save == "encoded":
                ds.to_netcdf(output_file, encoding=encoding, format='NETCDF4')
            else:
                ds.to_netcdf(output_file, format='NETCDF4', engine='netcdf4')

            # Verify file
            file_size = Path(output_file).stat().st_size / 1e6
            print(f"✓ Saved: {output_file}")
            print(f"✓ File size: {file_size:.1f} MB")

            # Verify by loading
            ds_verify = xr.open_dataset(output_file)
            print("✓ Verified: File is readable")
            print(f"✓ Variables: {len(ds_verify.data_vars)}")
            print(f"✓ Coordinates: {len(ds_verify.coords)}")

        except Exception as e:
            print(f"❌ Error saving: {e}")
            return None

    print("\n" + "="*80)
    print("✓ CONVERSION COMPLETE!")
    print("="*80 + "\n")

    return ds


def _plain_strings(ds):
    """Object-dtype variables -> numpy str (pandas >= 3 yields Arrow-backed strings that
    netCDF4 cannot write). Values are unchanged; added for this port."""
    for name in list(ds.variables):
        if ds[name].dtype == object:
            fixed = ds[name].astype(str)
            ds = ds.assign_coords({name: fixed}) if name in ds.coords else ds.assign({name: fixed})
    return ds


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_nc", help="OpenMesh CML netCDF (cml_id, sublink_id, time)")
    ap.add_argument("output_nc")
    ap.add_argument("--encoded", action="store_true",
                    help="compressed encoding (default: plain, as the Zenodo file)")
    a = ap.parse_args()
    ds = xr.open_dataset(a.input_nc)
    convert_to_opensense_cml(ds, a.output_nc, save="encoded" if a.encoded else "notebook")


if __name__ == "__main__":
    main()
