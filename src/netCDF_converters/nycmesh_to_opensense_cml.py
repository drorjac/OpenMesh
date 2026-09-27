"""
OPTIONAL converter — the default OpenSense CML converter is openmesh_to_opensense_cml.py
(the one behind the published Zenodo file). Use this one for the full 2023-2026 record.

Convert the raw NYC Mesh netCDF (nycmesh_data_*.nc, from nycmesh_to_netcdf.py) plus a
link table into an OpenSense-CML-v1.0 netCDF: dims (cml_id, sublink_id, time),
rsl float32 (dBm), site coordinates, length, frequency, polarisation, device_name.

Ported from ~/openmesh-opensense-builder (helpers_inspect/build_opensense.py, run by
temp_output/regen_nc.py), which produced dataset/raw/full/paper/ds_opensense_cml.nc.
Output format unchanged. Written in time slabs, so the dense cube (hundreds of GB
uncompressed for the full record) never sits in RAM.

Each raw channel (rsl, rsl_remote, rsl_60g, rsl_60g_remote of one raw cml_id =
`cml_api`) becomes one (cml_id, sublink_id) row, as listed in the link table — e.g.
final_metadata/links_metadata_map_reduced.csv of the builder (the link selection:
filters, co-located merges, renumbering to cml_id 1..N and dense sublink ids).

Usage (CLI):
    python nycmesh_to_opensense_cml.py <raw.nc> <links.csv> <out.nc> [--filters "step1,..."]
Usage (import):
    from nycmesh_to_opensense_cml import build_opensense_nc
"""
from __future__ import annotations

import argparse
import os
import time as _time
from pathlib import Path
from typing import Dict, Optional

import netCDF4
import numpy as np
import pandas as pd

# raw-file channels, each mapped to one OpenSense sublink by the link table
CHANNELS = ["rsl", "rsl_remote", "rsl_60g", "rsl_60g_remote"]

_POL_MAP = {
    "v": "vertical", "h": "horizontal",
    "V": "vertical", "H": "horizontal",
    "vertical": "vertical", "horizontal": "horizontal",
}


def _epoch_offset_seconds(units: str) -> int:
    """`seconds since YYYY-MM-DD…` → offset from 1970-01-01 UTC in seconds."""
    assert units.startswith("seconds since "), f"unsupported time units: {units!r}"
    origin = pd.Timestamp(units.removeprefix("seconds since ").strip())
    if origin.tz is None:
        origin = origin.tz_localize("UTC")
    return int((origin - pd.Timestamp("1970-01-01", tz="UTC")).total_seconds())


def build_opensense_nc(
    *,
    reduced_main: pd.DataFrame,
    src_nc_path: Path,
    out_nc_path: Path,
    filters_applied: str = "",
    ts_dropped: int = 0,
    apis_dropped: int = 0,
    time_slab: int = 50_000,
    complevel: int = 1,
    shuffle: bool = False,
    extra_global_attrs: Optional[Dict] = None,
    verbose: bool = True,
) -> dict:
    """Write a spec-compliant OpenSense CML netCDF in time-slabs.

    `reduced_main` must carry the contiguous `cml_id_new` (1..N) column and densely
    renumbered `sublink_id` (1..k per cml), plus cml_api (the raw file's cml_id),
    data_channel (one of CHANNELS), site_0/1_lat/lon, length (m), frequency (MHz),
    polarization, device_name. The dataset shape is derived from
    `reduced_main.cml_id_new.max()` and `reduced_main.sublink_id.max()`.

    Returns a dict with timing + shape info.
    """
    t_start = _time.time()
    out_nc_path = Path(out_nc_path)
    src_nc_path = Path(src_nc_path)

    n_cml       = int(reduced_main["cml_id_new"].max())
    max_sublink = int(reduced_main["sublink_id"].max())

    # --- map cml_api → source NC position --------------------------------
    src = netCDF4.Dataset(str(src_nc_path), "r")
    src_apis_raw = src.variables["cml_id"][:]
    if src_apis_raw.dtype.kind == "S":
        src_apis = np.array([s.decode() for s in src_apis_raw])
    elif src_apis_raw.dtype == object:
        src_apis = np.array([str(s) for s in src_apis_raw])
    else:
        src_apis = src_apis_raw
    api2pos = {a: i for i, a in enumerate(src_apis)}

    # --- time conversion --------------------------------------------------
    src_time_var = src.variables["time"]
    src_time = src_time_var[:]
    n_time = len(src_time)
    epoch_offset = _epoch_offset_seconds(src_time_var.units)
    out_time = src_time.astype("int64") + epoch_offset

    if verbose:
        print(f"  src    : {src_nc_path.name}  ({n_time} time × {len(src_apis)} cml × 4 channels)")
        print(f"  target : {n_cml} cml × {max_sublink} sublink × {n_time} time")
        n_slabs = (n_time + time_slab - 1) // time_slab
        print(f"  slabs  : {n_slabs}  (slab={time_slab} time-steps, complevel={complevel}, shuffle={shuffle})")

    # --- per-cml + per-(cml,sublink) coordinate arrays --------------------
    first_per_cml = reduced_main.drop_duplicates("cml_id_new").set_index("cml_id_new")
    site_0_lat = first_per_cml.loc[range(1, n_cml + 1), "site_0_lat"].to_numpy(dtype="float32")
    site_0_lon = first_per_cml.loc[range(1, n_cml + 1), "site_0_lon"].to_numpy(dtype="float32")
    site_1_lat = first_per_cml.loc[range(1, n_cml + 1), "site_1_lat"].to_numpy(dtype="float32")
    site_1_lon = first_per_cml.loc[range(1, n_cml + 1), "site_1_lon"].to_numpy(dtype="float32")
    length_arr = first_per_cml.loc[range(1, n_cml + 1), "length"].to_numpy(dtype="float32")

    frequency    = np.full((n_cml, max_sublink), np.nan, dtype="float32")
    polarisation = np.full((n_cml, max_sublink), "",     dtype=object)
    device_name  = np.full((n_cml, max_sublink), "",     dtype=object)
    for _, r in reduced_main.iterrows():
        ci, si = int(r["cml_id_new"]) - 1, int(r["sublink_id"]) - 1
        frequency[ci, si] = r["frequency"]
        raw = r.get("polarization")
        polarisation[ci, si] = _POL_MAP.get(str(raw).strip(), "") if pd.notna(raw) else ""
        device_name[ci, si]  = "" if pd.isna(r.get("device_name")) else str(r["device_name"])

    # --- row-arrays for the fast rsl fill loop ----------------------------
    ci_arr    = (reduced_main["cml_id_new"].to_numpy() - 1).astype(int)
    si_arr    = (reduced_main["sublink_id"].to_numpy()  - 1).astype(int)
    apis_arr  = reduced_main["cml_api"].to_numpy()
    chans_arr = reduced_main["data_channel"].to_numpy()
    pos_arr   = np.array([api2pos[a] for a in apis_arr], dtype=np.int64)
    chan_rows = {ch: np.where(chans_arr == ch)[0] for ch in CHANNELS}

    # --- write the output netCDF ------------------------------------------
    # Write to a temp file then atomically replace, so a reader holding the
    # final path open (e.g. a notebook with xr.open_dataset) can never cause a
    # write-mode truncation of the good file.
    out_nc_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_nc_path.with_suffix(out_nc_path.suffix + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    t_fill = 0.0
    with netCDF4.Dataset(str(tmp_path), "w", format="NETCDF4") as nc:
        nc.createDimension("time", None)               # unlimited
        nc.createDimension("cml_id", n_cml)
        nc.createDimension("sublink_id", max_sublink)

        tv = nc.createVariable("time", "i8", ("time",), zlib=complevel > 0,
                               complevel=max(1, complevel) if complevel > 0 else 1)
        tv[:] = out_time
        tv.units    = "seconds since 1970-01-01 00:00:00 UTC"
        tv.calendar = "standard"
        tv.long_name = "time_utc"

        cidv = nc.createVariable("cml_id", str, ("cml_id",))
        cidv[:] = np.array([str(i) for i in range(1, n_cml + 1)])
        cidv.long_name = "commercial_microwave_link_identifier"

        sidv = nc.createVariable("sublink_id", str, ("sublink_id",))
        sidv[:] = np.array([f"sublink_{s}" for s in range(1, max_sublink + 1)])
        sidv.long_name = "sublink_identifier"

        def _addvar_f4(name, dims, data, attrs):
            v = nc.createVariable(name, "f4", dims, zlib=True, complevel=complevel,
                                  shuffle=shuffle, fill_value=np.float32(np.nan))
            v[:] = data
            for k, val in attrs.items():
                setattr(v, k, val)

        _addvar_f4("site_0_lat", ("cml_id",), site_0_lat,
                   {"units": "degrees_in_WGS84_projection", "long_name": "site_0_latitude"})
        _addvar_f4("site_0_lon", ("cml_id",), site_0_lon,
                   {"units": "degrees_in_WGS84_projection", "long_name": "site_0_longitude"})
        _addvar_f4("site_1_lat", ("cml_id",), site_1_lat,
                   {"units": "degrees_in_WGS84_projection", "long_name": "site_1_latitude"})
        _addvar_f4("site_1_lon", ("cml_id",), site_1_lon,
                   {"units": "degrees_in_WGS84_projection", "long_name": "site_1_longitude"})
        _addvar_f4("length", ("cml_id",), length_arr,
                   {"units": "m", "long_name": "distance_between_pair_of_antennas"})
        _addvar_f4("frequency", ("cml_id", "sublink_id"), frequency,
                   {"units": "MHz", "long_name": "sublink_frequency"})

        polv = nc.createVariable("polarisation", str, ("cml_id", "sublink_id"))
        polv[:] = polarisation
        polv.units    = "no units"
        polv.long_name = "sublink_polarization"

        dnv = nc.createVariable("device_name", str, ("cml_id", "sublink_id"))
        dnv[:] = device_name
        dnv.long_name = "device_name_at_sublink"
        dnv.comment   = "non-spec extra carried from links_metadata_map.csv"

        rsl_v = nc.createVariable(
            "rsl", "f4", ("cml_id", "sublink_id", "time"),
            zlib=complevel > 0, complevel=max(1, complevel) if complevel > 0 else 1,
            shuffle=shuffle,
            chunksizes=(min(n_cml, 64), min(max_sublink, 16), min(n_time, time_slab)),
            fill_value=np.float32(np.nan),
        )
        rsl_v.units       = "dBm"
        rsl_v.long_name   = "received_signal_level"
        rsl_v.sampling    = "instantaneous"
        rsl_v.coordinates = "site_0_lat site_0_lon site_1_lat site_1_lon length frequency polarisation"

        src_vars = {ch: src.variables[ch] for ch in CHANNELS if ch in src.variables}
        n_slabs  = (n_time + time_slab - 1) // time_slab
        for s_idx, t0 in enumerate(range(0, n_time, time_slab), start=1):
            t1 = min(t0 + time_slab, n_time)
            slab_len = t1 - t0
            t_slab0 = _time.time()
            slab = np.full((n_cml, max_sublink, slab_len), np.nan, dtype="float32")
            for ch, srcv in src_vars.items():
                rows = chan_rows[ch]
                if rows.size == 0:
                    continue
                ch_data = srcv[t0:t1, :]                   # (slab_len, n_cml_raw)
                slab[ci_arr[rows], si_arr[rows], :] = ch_data[:, pos_arr[rows]].T
            rsl_v[:, :, t0:t1] = slab
            dt = _time.time() - t_slab0
            t_fill += dt
            if verbose:
                print(f"    slab {s_idx:>3}/{n_slabs}  rows {t0:>9}..{t1:<9}  {dt:5.2f}s", flush=True)

        # --- global attrs --------------------------------------------------
        utc_today = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
        attrs = {
            "title": "OpenMesh",
            "file_author": "Dror Jacoby",
            "institution": ("Cellular Environmental Monitoring (CellEnMon) Lab, School of Electrical "
                            "Engineering, Tel-Aviv University; Wireless and Mobile Networking (WiMNet) "
                            "Lab, Department of Electrical Engineering, Columbia University"),
            "date": utc_today,
            "source": "Community NYC Mesh Wireless Network",
            "history": (f"{utc_today}: filtered ({filters_applied}); "
                        "converted netCDF → OpenSense-1.0 CML format"),
            "naming_convention": "OpenSense-1.0",
            "license_restrictions": "CC BY 4.0 – https://creativecommons.org/licenses/by/4.0/",
            "reference": "https://doi.org/10.5281/zenodo.15287692",
            "comment": ("OpenMesh: Wireless Signal Dataset for Opportunistic Urban Weather Sensing in "
                        "NYC. TSL omitted (constant) per OpenSense-CML spec note."),
            "Conventions": "OpenSense-CML-v1.0",
            "source_nc": src_nc_path.name,
            "filters_applied": filters_applied,
            "ts_dropped": int(ts_dropped),
            "apis_dropped": int(apis_dropped),
        }
        if extra_global_attrs:
            attrs.update(extra_global_attrs)
        for k, v in attrs.items():
            setattr(nc, k, v)

    src.close()
    # atomic replace — final path only ever flips to a complete file
    os.replace(str(tmp_path), str(out_nc_path))
    total = _time.time() - t_start
    if verbose:
        print(f"  done in {total:5.1f}s  (rsl fill {t_fill:5.1f}s, other {total-t_fill:.1f}s)")
        print(f"  wrote {out_nc_path}  ({out_nc_path.stat().st_size/1e6:.1f} MB)")
    return {
        "total_seconds": total,
        "fill_seconds": t_fill,
        "out_path": str(out_nc_path),
        "n_cml": n_cml,
        "max_sublink": max_sublink,
        "n_time": n_time,
        "file_bytes": out_nc_path.stat().st_size,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw_nc", help="nycmesh_data_*.nc (raw, time x cml_id)")
    ap.add_argument("links_csv", help="link table with cml_id (renumbered 1..N), sublink_id, cml_api, "
                                      "data_channel, site_0/1_lat/lon, length, frequency, polarization, device_name")
    ap.add_argument("out_nc")
    ap.add_argument("--filters", default="", help="text recorded in the filters_applied / history attrs")
    ap.add_argument("--time-slab", type=int, default=50_000)
    ap.add_argument("--complevel", type=int, default=1)
    a = ap.parse_args()
    links = pd.read_csv(a.links_csv)
    if "cml_id_new" not in links:
        links["cml_id_new"] = links["cml_id"]       # table already renumbered 1..N
    build_opensense_nc(reduced_main=links, src_nc_path=a.raw_nc, out_nc_path=a.out_nc,
                       filters_applied=a.filters, time_slab=a.time_slab, complevel=a.complevel)


if __name__ == "__main__":
    main()
