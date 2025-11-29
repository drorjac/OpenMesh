# Software Development Branch

**Branch:** `feature/pynncml-integration`  
**Purpose:** OpenSense methods implementation, Quality Control (QC), and rainfall field reconstruction

## Overview

This branch focuses on software development for applying OpenSense standard methods to Commercial Microwave Link (CML) data. It includes Quality Control (QC) methods, rainfall map generation, field reconstruction, and integration with PyNNcml and other analysis tools.

## Key Features

### 1. OpenSense Standard Methods

Implementation of OpenSense v1.0 standard methods for CML data processing:
- **Signal processing** – RSL (Received Signal Level) analysis
- **Attenuation calculation** – Baseline estimation and rain attenuation
- **Data standardization** – OpenSense-compliant data formats
- **Metadata handling** – Standard metadata structures

### 2. Quality Control (QC) Methods

Quality control and validation tools for CML data:
- **Data validation** – Check data completeness and consistency
- **Outlier detection** – Identify and handle anomalous values
- **Signal quality assessment** – Evaluate link reliability
- **Gap filling** – Handle missing data appropriately

### 3. Rainfall Maps and Field Reconstruction

- **Rainfall estimation** – Convert CML attenuation to rainfall
- **Spatial interpolation** – Generate rainfall maps from link network
- **Field reconstruction** – Reconstruct rainfall fields using multiple methods
- **Visualization** – Interactive maps and time-series plots

### 4. PyNNcml Integration

Integration with PyNNcml package for advanced analysis:
- **Neural network methods** – Deep learning approaches for rainfall estimation
- **Model training** – Train custom models on OpenMesh data
- **Evaluation** – Compare different methods and approaches
- **Tool integration** – Seamless integration with existing workflows

## Repository Structure

```
feature/pynncml-integration/
├── src/
│   ├── analysis/
│   │   ├── opensense/           # OpenSense methods
│   │   │   ├── signal_processing.py
│   │   │   ├── attenuation.py
│   │   │   └── standardization.py
│   │   ├── qc/                   # Quality Control
│   │   │   ├── validation.py
│   │   │   ├── outlier_detection.py
│   │   │   └── gap_filling.py
│   │   ├── rainfall/             # Rainfall analysis
│   │   │   ├── estimation.py
│   │   │   ├── interpolation.py
│   │   │   └── field_reconstruction.py
│   │   └── pynncml/              # PyNNcml integration
│   │       ├── integration.py
│   │       ├── model_training.py
│   │       └── evaluation.py
│   └── tools/                    # Analysis tools
│       ├── visualization/
│       └── utilities/
└── notebooks/                     # Example notebooks
    ├── opensense_example.ipynb
    ├── qc_workflow.ipynb
    ├── rainfall_maps.ipynb
    └── pynncml_integration.ipynb
```

## Usage Examples

### OpenSense Signal Processing

```python
from src.analysis.opensense.signal_processing import process_cml_signal

# Process CML signal according to OpenSense standard
processed_data = process_cml_signal(
    rsl_data,
    baseline_method='rolling_quantile',
    window_size='3H'
)
```

### Quality Control

```python
from src.analysis.qc.validation import validate_cml_data

# Validate CML data quality
qc_results = validate_cml_data(
    cml_data,
    check_completeness=True,
    check_outliers=True,
    check_consistency=True
)
```

### Rainfall Field Reconstruction

```python
from src.analysis.rainfall.field_reconstruction import reconstruct_rainfall_field

# Reconstruct rainfall field from CML network
rainfall_field = reconstruct_rainfall_field(
    cml_network,
    attenuation_data,
    method='kriging',  # or 'idw', 'neural_network'
    resolution=0.01  # degrees
)
```

### PyNNcml Integration

```python
from src.analysis.pynncml.integration import train_rainfall_model

# Train PyNNcml model on OpenMesh data
model = train_rainfall_model(
    training_data,
    model_type='neural_network',
    epochs=100
)
```

## OpenSense Standard Compliance

All methods follow the OpenSense v1.0 standard:
- **Data format** – NetCDF with OpenSense conventions
- **Metadata** – Standard metadata attributes
- **Coordinate systems** – WGS84 for spatial data
- **Time handling** – UTC timestamps
- **Units** – Standard SI units

## Quality Control Workflow

1. **Data validation** – Check format and completeness
2. **Outlier detection** – Identify and flag anomalies
3. **Signal quality** – Assess link reliability
4. **Gap analysis** – Identify and handle missing data
5. **Consistency checks** – Validate across links

## Rainfall Estimation Methods

Multiple methods available:
- **Power-law** – Traditional attenuation-rainfall relationship
- **Neural networks** – PyNNcml deep learning approach
- **Machine learning** – Custom ML models
- **Hybrid methods** – Combination approaches

## Development Roadmap

- [ ] Complete OpenSense v1.0 implementation
- [ ] Advanced QC methods
- [ ] Real-time rainfall maps
- [ ] Multi-method field reconstruction
- [ ] PyNNcml model optimization
- [ ] Performance benchmarking
- [ ] Documentation and examples

## Dependencies

Key packages:
- `pynncml` – Neural network methods for CML
- `scikit-learn` – Machine learning tools
- `scipy` – Spatial interpolation
- `xarray` – NetCDF handling
- `numpy`, `pandas` – Data processing

## Contributing

When adding new methods:
1. Follow OpenSense v1.0 standard
2. Include QC validation
3. Add unit tests
4. Update documentation
5. Provide example notebooks

## Related Documentation

- [Main README](../README.md) – Overall repository structure
- [Data Fetching Branch](README-openmesh-fetch.md) – Data acquisition
- [OpenSense Standard](https://github.com/OpenSenseAction) – Official OpenSense documentation
- [PyNNcml Documentation](https://pynncml.readthedocs.io/) – PyNNcml package docs

