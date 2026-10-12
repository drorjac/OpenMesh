"""
Merge airport_wu_dates.nc into pws_wu_merged_*_qc.nc.

Strategy:
  - For KJFK / KLGA: prepend new observations (time < existing start) from
    airport_wu_dates.nc, keeping all existing QC data intact.
  - All other groups: copied as-is.
  - New condition strings not in the existing lookup are appended to it.

Inputs: the merged PWS QC netCDF, its condition lookup JSON (default: the QC file
name with `_condition_lookup.json`), and airport_wu_dates.nc (from
airport_wu_csv_to_netcdf.py). Output: a new merged QC netCDF plus its lookup JSON.

Usage (CLI):
    python merge_airport_wu_to_pws.py [--src-qc QC.nc] [--airport AIRPORT.nc]
        [--out OUT.nc] [--lookup-src SRC.json] [--lookup-out OUT.json]
"""

import argparse
import json
from pathlib import Path

import numpy as np
import netCDF4 as nc4

# ---------------------------------------------------------------------------
# Default paths (relative to the repository root)
# ---------------------------------------------------------------------------
DEFAULT_SRC_QC   = Path('dataset/raw/full/outputs/pws_wu_merged_2023-10-29_2026-04-24_qc.nc')
DEFAULT_AIRPORT  = Path('dataset/raw/full/airport_wu_dates.nc')
DEFAULT_OUT_FILE = Path('dataset/raw/full/outputs/pws_wu_merged_2023-06-07_2026-04-24_qc.nc')

AIRPORT_STATIONS = {'KJFK', 'KLGA'}


def _lookup_path(nc_path: Path) -> Path:
    return nc_path.with_name(nc_path.stem + '_condition_lookup.json')


# ---------------------------------------------------------------------------
# Condition lookup (string <-> integer code), extended as new strings appear
# ---------------------------------------------------------------------------
class ConditionLookup:
    def __init__(self, lookup: dict[str, str]):
        self.lookup = dict(lookup)                                  # {"0": "Cloudy", ...}
        self.str2code = {v: int(k) for k, v in self.lookup.items()}  # "Cloudy" → 0
        self.next_code = max((int(k) for k in self.lookup), default=-1) + 1

    def get_code(self, cond_str: str) -> int:
        """Return numeric code for a condition string, adding new ones to lookup."""
        s = cond_str.strip() if cond_str else ''
        if s not in self.str2code:
            self.str2code[s] = self.next_code
            self.lookup[str(self.next_code)] = s
            self.next_code += 1
        return self.str2code[s]


# ---------------------------------------------------------------------------
# Load new airport data (per station, filtered to pre-existing timestamps)
# ---------------------------------------------------------------------------
def load_new_data(qc_ds, airport_ds, sid: str, lookup: ConditionLookup) -> dict | None:
    """
    Return dict of arrays for rows in airport_ds[sid] where
    time < min(qc_ds[sid]['time']).
    Returns None if no such rows exist.
    """
    if sid not in airport_ds.groups:
        return None
    if sid not in qc_ds.groups:
        return None

    qc_t   = qc_ds.groups[sid].variables['time'][:].data.astype(float)
    new_t  = airport_ds.groups[sid].variables['time'][:].astype(float)
    existing_start = float(qc_t.min())

    mask = new_t < existing_start
    if not mask.any():
        print(f'  {sid}: no new timestamps before {existing_start:.0f} — nothing to prepend')
        return None

    print(f'  {sid}: prepending {mask.sum()} obs  '
          f'({_ts(new_t[mask][0])} → {_ts(new_t[mask][-1])})')

    ag = airport_ds.groups[sid]

    def _get(var, idx=None):
        arr = ag.variables[var][:]
        if hasattr(arr, 'data'):
            arr = arr.data
        if idx is not None:
            arr = arr[idx]
        return arr.astype(float)

    # condition: string in airport file → integer code
    cond_strs = ag.variables['condition'][:][mask]
    cond_codes = np.array([lookup.get_code(str(c)) for c in cond_strs], dtype=np.float32)

    return {
        'time':               new_t[mask],
        'rainfall_amount':    _get('rainfall_amount',    (0, mask)),
        'rainfall_rate':      _get('precip_rate_calculated', (0, mask)),
        'temperature':        _get('temperature',        (0, mask)),
        'dew_point':          _get('dew_point',          (0, mask)),
        'relative_humidity':  _get('relative_humidity',  (0, mask)),
        'wind_direction':     _get('wind_direction',     (0, mask)),
        'wind_velocity':      _get('wind_velocity',      (0, mask)),
        'wind_gust':          _get('wind_gust',          (0, mask)),
        'air_pressure':       _get('air_pressure',       (0, mask)),
        'condition':          cond_codes,
    }


def _ts(unix):
    import datetime
    return datetime.datetime.utcfromtimestamp(float(unix)).strftime('%Y-%m-%d %H:%M')


# ---------------------------------------------------------------------------
# Copy a group from src → dst, optionally prepending new data
# ---------------------------------------------------------------------------
SKIP_COPY = {'time'}  # handled explicitly; all others copied dynamically


def copy_group(src_grp, dst_ds, gname: str, prepend: dict | None = None):
    dst_grp = dst_ds.createGroup(gname)

    src_t   = src_grp.variables['time'][:].data.astype(float)
    n_exist = len(src_t)
    n_new   = len(prepend['time']) if prepend else 0
    n_total = n_new + n_exist

    # Mirror all source dimensions; update 'time' size for the merge
    for dim_name, dim in src_grp.dimensions.items():
        size = n_total if dim_name == 'time' else len(dim)
        dst_grp.createDimension(dim_name, size)

    # time
    tv = dst_grp.createVariable('time', 'f8', ('time',))
    tv.units    = 'seconds since 1970-01-01 00:00:00 UTC'
    tv.calendar = 'standard'
    tv[:] = np.concatenate([prepend['time'], src_t]) if prepend else src_t

    # All other variables — copy whatever exists in the source group
    for vname, src_v in src_grp.variables.items():
        if vname in SKIP_COPY:
            continue

        fill  = getattr(src_v, '_FillValue', np.nan)
        dims  = src_v.dimensions
        has_time = 'time' in dims

        if has_time and src_v.ndim > 1:
            # 2-D variable (id/station × time)
            dv = dst_grp.createVariable(vname, 'f4', dims, fill_value=fill)
            dv.units = getattr(src_v, 'units', '')
            src_arr = src_v[:].data.astype(np.float32)  # (1, n_exist)
            if prepend and vname in prepend:
                pre = prepend[vname].astype(np.float32)
                dv[0, :] = np.concatenate([pre, src_arr[0]])
            elif prepend:
                nan_pad = np.full(n_new, np.nan, dtype=np.float32)
                dv[0, :] = np.concatenate([nan_pad, src_arr[0]])
            else:
                dv[0, :] = src_arr[0]
        elif has_time and src_v.ndim == 1:
            # 1-D time-only variable
            dv = dst_grp.createVariable(vname, 'f4', dims, fill_value=fill)
            dv.units = getattr(src_v, 'units', '')
            src_arr = src_v[:].data.astype(np.float32)
            if prepend and vname in prepend:
                pre = prepend[vname].astype(np.float32)
                dv[:] = np.concatenate([pre, src_arr])
            elif prepend:
                nan_pad = np.full(n_new, np.nan, dtype=np.float32)
                dv[:] = np.concatenate([nan_pad, src_arr])
            else:
                dv[:] = src_arr
        else:
            # Scalar / station-only variable (lat, lon, elev, …)
            dv = dst_grp.createVariable(vname, src_v.dtype, dims, fill_value=fill)
            dv.units = getattr(src_v, 'units', '')
            dv[:] = src_v[:]

    # copy group attributes
    for attr in src_grp.ncattrs():
        setattr(dst_grp, attr, getattr(src_grp, attr))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description='Prepend WU airport observations '
                                 '(KJFK, KLGA) to a merged PWS QC netCDF.')
    ap.add_argument('--src-qc', type=Path, default=DEFAULT_SRC_QC,
                    help=f'merged PWS QC netCDF (default {DEFAULT_SRC_QC})')
    ap.add_argument('--airport', type=Path, default=DEFAULT_AIRPORT,
                    help=f'airport netCDF from airport_wu_csv_to_netcdf.py (default {DEFAULT_AIRPORT})')
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT_FILE,
                    help=f'output netCDF (default {DEFAULT_OUT_FILE})')
    ap.add_argument('--lookup-src', type=Path, default=None,
                    help='condition lookup JSON of --src-qc (default: <src-qc stem>_condition_lookup.json)')
    ap.add_argument('--lookup-out', type=Path, default=None,
                    help='lookup JSON to write (default: <out stem>_condition_lookup.json)')
    args = ap.parse_args(argv)
    lookup_src = args.lookup_src or _lookup_path(args.src_qc)
    lookup_out = args.lookup_out or _lookup_path(args.out)

    missing = [(n, p) for n, p in (('--src-qc', args.src_qc), ('--airport', args.airport),
                                   ('--lookup-src', lookup_src)) if not p.exists()]
    if missing:
        raise SystemExit('Input file(s) not found:\n' + '\n'.join(
            f'  {n}: {p}' for n, p in missing) + '\nPass the paths explicitly (see --help).')

    with open(lookup_src) as f:
        lookup = ConditionLookup(json.load(f))

    print(f'Source QC : {args.src_qc}')
    print(f'Airport NC: {args.airport}')
    print(f'Output    : {args.out}')
    print()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    src_ds  = nc4.Dataset(str(args.src_qc),  'r')
    air_ds  = nc4.Dataset(str(args.airport), 'r')
    dst_ds  = nc4.Dataset(str(args.out), 'w', format='NETCDF4')

    # Copy global attributes (update the date range label)
    for attr in src_ds.ncattrs():
        setattr(dst_ds, attr, getattr(src_ds, attr))
    # Will update condition_lookup_json after processing all groups

    print('Processing groups...')
    for gname in src_ds.groups:
        src_grp = src_ds.groups[gname]
        if gname in AIRPORT_STATIONS:
            prepend = load_new_data(src_ds, air_ds, gname, lookup)
        else:
            prepend = None
            print(f'  {gname}: copy as-is ({src_grp.dimensions["time"].size} obs)')
        copy_group(src_grp, dst_ds, gname, prepend=prepend)

    # Update condition lookup in global attribute
    dst_ds.condition_lookup_json = json.dumps(lookup.lookup)
    dst_ds.qc_condition_lookup   = lookup_out.name

    src_ds.close()
    air_ds.close()
    dst_ds.close()

    # Write updated lookup JSON
    with open(lookup_out, 'w') as f:
        json.dump(lookup.lookup, f, indent=2)

    print(f'\nDone → {args.out}')
    print(f'Lookup  → {lookup_out}')


if __name__ == '__main__':
    main()
