# Tutorials

Follow these in order. Each builds on the previous.

## 1. **`1_radar.ipynb`** — Radar Data Fetching (30 min)

Learn to fetch and visualize MRMS and KOKX NEXRAD radar data.

**What you'll learn:**
- Fetch MRMS quantitative precipitation (QPE) from AWS
- Fetch KOKX NEXRAD hydrometeor classification
- Understand caching (local vs. cloud)
- Plot rainfall with OpenSense-style colormaps

**Prerequisites:** None. Just environment setup.

**Output:** Cached radar files in `dataset/raw/radar/`

---

## 2. **`asos_gauge_melt_qc.ipynb`** — ASOS Quality Control (20 min)

Learn about ASOS weather station data and quality checks.

**What you'll learn:**
- Load 1-minute precipitation from ASOS
- Apply gauge-melt QC to remove artifacts
- Understand precipitation flags and types

**Prerequisites:** Radar tutorial (optional but recommended)

**Output:** QC-cleaned weather station data

---

## 3. **`analysis.ipynb`** (in src/analysis/) — Full Analysis Pipeline (1-2 hours)

End-to-end workflow: fetch, merge sensors, compare with radar.

**What you'll learn:**
- Download OpenMesh CML and sensor data (v1 or v2)
- Fetch ASOS, MRMS, KOKX for a precipitation event
- Merge all data into one table (sensors + radar)
- Compare CML attenuation with precipitation

**Prerequisites:** Tutorials 1 & 2

**Output:** Event analysis with sensor/radar comparison

---

## Tips

- **Run in order** — each tutorial sets up data the next one uses
- **First run slower** — fetching from AWS takes time; cached data is instant
- **Change dates** — modify `start`/`end` to explore other events
- **Check radar_events.csv** — dates with actual rain/snow for better viz

## Need Help?

- **Fetch issues?** See [FETCHING.md](../FETCHING.md)
- **Setup issues?** See [SETUP.md](../SETUP.md)
- **Advanced config?** See [DETAILS.md](../DETAILS.md)
