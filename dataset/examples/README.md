# Example Notebooks

Examples that show how to read and plot the sample data from the OpenMesh Zenodo record
([10.5281/zenodo.15287692](https://doi.org/10.5281/zenodo.15287692)).

Versions of these notebooks are in the Zenodo archive; the copies here use repository paths.

- `openmesh_dataset_example.ipynb` – read and plot the wireless link data (`ds_openmesh.nc`)
- `read_pws_sample.ipynb` – read and plot the PWS sample (`pws_opensense_sample_jan.nc`, 2024-01-15 → 2024-01-30)

To get the data, run `python src/fetch_data/main.py openmesh` or the notebook
`src/fetch_data/OpenMesh/download_and_read_openmesh.ipynb`.
