# Data Analysis Pipeline

**This folder** — Examples of **using** the data: you can **fetch directly** or **load** from files; processing and plots use simple **pandas** operations. For **saving** and the full **fetch-and-save** pipeline, use **`src/fetch_data/`**.
**Data** — Lives in `dataset/` (meta + raw fetched files). **`src/fetch_data/`** — Fetches from APIs (ASOS, WU, OpenMesh) and saves under `dataset/`.

## Project layout (needed folders)

```
OpenMesh-fresh/
├── dataset/                  # Data used by this notebook
│   ├── meta/                 # Station/link metadata (CSV), maps
│   └── raw/fetched/          # Fetched outputs (asos/, wu/, etc.)
├── src/
│   ├── fetch_data/           # Fetches and saves data (ASOS, WU, OpenMesh)
│   └── analysis/             # This folder: load + use data
│       ├── pipeline.py       # Load/fetch + process
│       ├── plotting.py       # Visualization
│       ├── analysis_functions.py
│       ├── analysis.ipynb    # Main analysis notebook
│       └── README.md
└── requirements.txt
```

## Contents of this folder

- **`pipeline.py`** — Load from files or fetch into memory; prepare unified analysis data (pandas); `get_default_paths`, `map_all_sensors`.
- **`plotting.py`** — All plots (CML, rain detection, weather, maps).
- **`analysis_functions.py`** — Rain detection, CML prep, ground-truth rainfall, link filtering.
- **`analysis.ipynb`** — End-to-end workflow using the above.

**Load/fetch:** `load_all_datasets()`, `fetch_asos_data()`, `fetch_wu_data()`  
**Process:** `prepare_analysis_data(datasets, parameters='all')`  
**Helpers:** `load_openmesh_cml`, `load_pws_from_netcdf`, `get_default_paths`, `map_all_sensors`

**Analysis:** `prepare_cml_data_for_detection`, `detect_rain_rolling_std`, `prepare_ground_truth_rainfall`, `prepare_combined_ground_truth`, `filter_links_by_features`, `match_links_to_pws`, `calculate_db_per_km_for_links`, `create_scatter_plot_db_vs_rainfall`

**Plotting:** `plot_all_datasets`, `plot_cml_rsl_attenuation`, `plot_rain_detection`, `plot_rolling_baseline_detection`, `plot_detection_with_periods`, `plot_weather_params`, `plot_links_scatter`; maps via `map_all_sensors` in pipeline.

Full workflow and examples: **`analysis.ipynb`**.
