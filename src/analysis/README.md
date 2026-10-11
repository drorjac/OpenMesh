# Analysis pipeline

**Start here:** open `analysis.ipynb`, set `MODE = 'fetch'`, and run all cells. This downloads all data and runs the full analysis in one go.

End-to-end load/fetch and analysis live in:

- **`analysis.ipynb`** — run this from the repo root (or set the notebook working directory to the project root). Configure **MODE** (`load` / `fetch`) and **PWS_OPENMESH_SOURCE** in the notebook.
- **`pipeline.py`** — `load_or_fetch_*` helpers, path resolution, and unified data loading used by the notebook.
- **`plotting.py`**, **`analysis_functions.py`** — plots and metrics.
- **`datasets.py`** — which OpenMesh dataset every loader reads: v1 (default) or Zenodo v2
  (`DATASET` knob in `analysis.ipynb`), and one reader for both CML layouts (`open_cml`,
  `signal_level`, `sublink_table`). See [dataset/README.md](../../dataset/README.md#choosing-the-dataset-v1-default-or-zenodo-v2).

For CLI and data layout, see the root [README.md](../../README.md) and [dataset/README.md](../../dataset/README.md).
