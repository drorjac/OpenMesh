# OpenMesh Software Development Branch

**Branch:** `openmesh-software`  
**Purpose:** OpenSense methods integration, Quality Control (QC), and rainfall field reconstruction

## Overview

This branch focuses on software development for applying OpenSense standard methods to Commercial Microwave Link (CML) data. It includes Quality Control (QC) methods, rainfall map generation, field reconstruction, and integration with PyNNcml and other analysis tools.

## Key Features

### OpenSense Integration

Implementation of OpenSense v1.0 standard methods:
- **Signal processing** – RSL (Received Signal Level) analysis and attenuation calculation
- **Data standardization** – OpenSense-compliant data formats and metadata
- **Standard compliance** – Follows OpenSense v1.0 conventions

### Quality Control (QC) Methods

- **Data validation** – Completeness and consistency checks
- **Outlier detection** – Identify and handle anomalous values
- **Signal quality assessment** – Evaluate link reliability
- **Gap filling** – Handle missing data appropriately

### Rainfall Analysis

- **Rainfall estimation** – Convert CML attenuation to rainfall
- **Spatial interpolation** – Generate rainfall maps from link network
- **Field reconstruction** – Reconstruct rainfall fields using multiple methods

### PyNNcml Integration

- **Neural network methods** – Deep learning approaches for rainfall estimation
- **Model training** – Train custom models on OpenMesh data
- **Tool integration** – Seamless integration with existing workflows

## Repository Structure

```
openmesh-software/
├── src/
│   ├── analysis/
│   │   ├── opensense/           # OpenSense methods
│   │   ├── qc/                   # Quality Control
│   │   ├── rainfall/             # Rainfall analysis
│   │   └── pynncml/              # PyNNcml integration
│   └── tools/                    # Analysis tools
└── notebooks/                     # Example notebooks
```

## Usage

### OpenSense Methods

```python
from src.analysis.opensense import process_cml_signal

# Process CML signal according to OpenSense standard
processed_data = process_cml_signal(rsl_data)
```

### Quality Control

```python
from src.analysis.qc import validate_cml_data

# Validate CML data quality
qc_results = validate_cml_data(cml_data)
```

### Rainfall Field Reconstruction

```python
from src.analysis.rainfall import reconstruct_rainfall_field

# Reconstruct rainfall field from CML network
rainfall_field = reconstruct_rainfall_field(cml_network, attenuation_data)
```

## OpenSense Standard

All methods follow the OpenSense v1.0 standard:
- NetCDF format with OpenSense conventions
- Standard metadata attributes
- WGS84 coordinate systems
- UTC timestamps
- SI units

## Related Documentation

- [Main README](../README.md) – Overall repository structure
- [Data Fetching Branch](README-openmesh-fetch.md) – Data acquisition
- [OpenSense Standard](https://github.com/OpenSenseAction) – Official documentation

