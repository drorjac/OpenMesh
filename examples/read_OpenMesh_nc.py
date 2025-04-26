#!/usr/bin/env python
"""
read_OpenMesh_nc.py

Quickstart for exploring the OpenMesh CML NetCDF.

This script demonstrates:
  - Loading the OpenSense‐compliant NetCDF file
  - Inspecting global attributes and dataset structure
  - Plotting distributions of link frequencies and lengths
  - Mapping the network topology
  - Visualizing RSL time series and rain-induced attenuation
"""

import xarray as xr
import matplotlib.pyplot as plt
from pathlib import Path

# 0) Dependencies check
#    pip install xarray matplotlib

#
# # 1) Load the dataset

DATA_DIR = Path("dataset")                # project root / current folder
nc_file  = DATA_DIR / "sample_OpenMesh.nc"

# Safety check
if not nc_file.exists():
    raise FileNotFoundError(f"Dataset not found → {nc_file}")

ds = xr.open_dataset(nc_file)       # xarray accepts Path objects
print("Loaded dataset:", nc_file)# DATA_DIR = Path("path/to/your/data")         # ← update to your folder
# nc_file  = DATA_DIR / "OpenMesh.nc"
# ds = xr.open_dataset(str(nc_file))
# print("Loaded dataset:", nc_file)

# -----------------------------------------------------------------------------
# 2) Examine global attributes
# -----------------------------------------------------------------------------
print("\nGlobal attributes:")
for k, v in ds.attrs.items():
    print(f"  {k}: {v}")

# -----------------------------------------------------------------------------
# 3) Inspect dataset structure
# -----------------------------------------------------------------------------
print("\nDimensions:", ds.dims)
print("Coordinates:", list(ds.coords))
print("Data variables:", list(ds.data_vars))

# -----------------------------------------------------------------------------
# 4) Variable metadata
# -----------------------------------------------------------------------------
print("\nRSL attributes:", ds["rsl"].attrs)

# -----------------------------------------------------------------------------
# 5) Quick stats on link geometry
# -----------------------------------------------------------------------------
lengths = ds.length.values
print(f"\nLink lengths (m): min={lengths.min():.1f}, max={lengths.max():.1f}, mean={lengths.mean():.1f}")
plt.figure()
plt.hist(lengths, bins=20)
plt.title("Distribution of Link Lengths")
plt.xlabel("Length (m)")
plt.ylabel("Count")
plt.tight_layout()
plt.show()

# -----------------------------------------------------------------------------
# 5b) Distribution of link frequencies
# -----------------------------------------------------------------------------
freqs = ds.frequency.values
print(f"Link frequencies (MHz): min={freqs.min():.1f}, max={freqs.max():.1f}, mean={freqs.mean():.1f}")
plt.figure()
plt.hist(freqs, bins=20)
plt.title("Distribution of Link Frequencies")
plt.xlabel("Frequency (MHz)")
plt.ylabel("Count")
plt.tight_layout()
plt.show()

# -----------------------------------------------------------------------------
# 6) Map the network topology (simple scatter)
# -----------------------------------------------------------------------------
lats0, lons0 = ds.site_0_lat.values, ds.site_0_lon.values
lats1, lons1 = ds.site_1_lat.values, ds.site_1_lon.values
plt.figure(figsize=(6,6))
plt.scatter(lons0, lats0, s=10, label="Site 0")
plt.scatter(lons1, lats1, s=10, label="Site 1")
for i in range(len(lats0)):
    plt.plot([lons0[i], lons1[i]], [lats0[i], lats1[i]], color="gray", alpha=0.3)
plt.legend()
plt.title("NYC Mesh Link Topology")
plt.xlabel("Longitude")
plt.ylabel("Latitude")
plt.tight_layout()
plt.show()

# -----------------------------------------------------------------------------
# 7) Time‐series for a sample link
# -----------------------------------------------------------------------------
slink    = 20
rsl       = ds.rsl.sel(sublink_id=slink)
baseline  = float(rsl.median(dim="time"))
atten     = baseline - rsl

plt.figure(figsize=(12,4))
rsl.plot(label="RSL (dBm)", alpha=0.6)
plt.axhline(baseline, ls="--", color="k", label=f"Baseline = {baseline:.1f} dBm")
atten.plot(label="Attenuation (baseline − RSL)", alpha=0.8)
plt.title(f"Sublink {slink}: RSL & Rain-Induced Attenuation")
plt.xlabel("Time")
plt.ylabel("dBm")
plt.legend()
plt.tight_layout()
plt.show()
