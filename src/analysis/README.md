# Analysis pipeline

End-to-end load/fetch and analysis live in:

- **`analysis.ipynb`** — run this from the repo root (or set the notebook working directory to the project root). Configure **MODE** (`load` / `fetch`) and **PWS_OPENMESH_SOURCE** in the notebook.
- **`pipeline.py`** — `load_or_fetch_*` helpers, path resolution, and unified data loading used by the notebook.
- **`plotting.py`**, **`analysis_functions.py`** — plots and metrics.

For CLI and data layout, see the root [README.md](../../README.md) and [dataset/README.md](../../dataset/README.md).
