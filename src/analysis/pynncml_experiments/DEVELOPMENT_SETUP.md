# PyNNcml Development Setup

## Editable Install (Development Mode)

When you install PyNNcml with `pip install -e .`, it creates an **editable install**. This means:

✅ **Changes to PyNNcml source files are immediately reflected**  
✅ **No need to reinstall after each code change**  
✅ **Perfect for active development**

## How It Works

1. **Install in editable mode:**
   ```bash
   cd PyNNcml
   pip install -e .
   ```

2. **Make changes to PyNNcml:**
   - Edit any file in `PyNNcml/pynncml/`
   - Add new functions, modify existing ones, etc.

3. **Use in your code:**
   ```python
   import pynncml
   # Your changes are immediately available!
   ```

## Verification

Test scripts are located in `src/analysis/pynncml_experiments/` folder:
- `test_editable_install.py` - Demonstrates editable install concept
- `test_pynncml_changes.py` - Basic import test
- `test_pynncml_live.py` - Full live change verification

We've made test changes to verify this works:

- ✅ Added `__test_marker__` to `PyNNcml/pynncml/__init__.py`
- ✅ Added `test_function_for_openmesh()` to `PyNNcml/pynncml/utils.py`
- ✅ Exported the function in `__init__.py`

These changes are in the source files and will be available when you:
1. Install dependencies: `pip install -r PyNNcml/requirements.txt`
2. Install PyNNcml: `cd PyNNcml && pip install -e .`
3. Import and use: `import pynncml`

## Current Status

- **PyNNcml location:** `/Users/drorjac/PycharmProjects/OpenMesh-fresh/PyNNcml`
- **Installation:** Editable mode (when dependencies are installed)
- **Git status:** Separate repository with upstream tracking

## Workflow

1. **Develop in PyNNcml:**
   - Make changes to `PyNNcml/pynncml/` source files
   - Test your changes immediately (no reinstall needed)

2. **Use in OpenMesh analysis:**
   - Import `pynncml` in your analysis scripts
   - Changes are live!

3. **Commit changes:**
   - Commit to PyNNcml repo: `cd PyNNcml && git commit ...`
   - Or commit to OpenMesh repo if you want to track PyNNcml as submodule

## Notes

- Some dependencies may need to be installed separately (e.g., `utm`, `matplotlib`, etc.)
- If you get import errors, check that all dependencies from `PyNNcml/requirements.txt` are installed
- The editable install creates a link, so Python imports directly from the source directory

