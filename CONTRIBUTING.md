# Contributing to OpenMesh

## Branches

| Branch | Status | Description |
|--------|--------|-------------|
| `main` | Stable | Current release |
| `dev` | Active | Development branch |

## How to Contribute

1. Fork the repo
2. Branch from `dev`:
   ```bash
   git checkout dev && git checkout -b feature/your-feature
   ```
3. Commit, push, open PR to `dev`

Ideas: OpenSenseAction algorithms, cleaning functions, new data sources, NetCDF utilities.

## Roadmap

Upcoming in `dev` branch:

- **Unified Data Format** – All sources standardized to NetCDF (xarray-compatible)
- **Cleaning Functions** – Data QC, outlier detection, gap filling, sensor validation
- **OpenSenseAction Integration** – Run [OpenSenseAction](https://github.com/OpenSenseAction) algorithms directly (RAINLINK, CML wet/dry classification, pypwsqc)
- **End-to-End Pipelines** – Fetch → Clean → Process → Analyze in single workflow
- **Applied Examples** – Ready-to-use notebooks for rainfall estimation

## Contact

- **Issues:** https://github.com/drorjac/OpenMesh/issues
- **ESSD Discussion:** https://essd.copernicus.org/preprints/essd-2025-238/#discussion
- **Affiliations:** Tel Aviv University, Columbia University
