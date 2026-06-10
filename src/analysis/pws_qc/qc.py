"""
WU PWS quality control pipeline.

Pyramid filter over `rainfall_amount`:
    sample  > MAX_SAMPLE_MM       → NaN that sample
    hour    sum > MAX_HOURLY_MM   → NaN every sample in that hour
    day     sum > MAX_DAILY_MM    → NaN every sample in that day
    30-day  sum > MAX_30D_MM      → NaN every sample in that 30-day window
    station — after all masking, if total or coverage is out of range,
              flag qc_status='dropped' and NaN-fill every precip-related
              variable (rainfall_amount, rainfall_rate, precip_rate) so
              downstream network means don't get poisoned by a broken gauge.
              Non-precip vars (temperature, humidity, …) are preserved.

Upstream of the pyramid:
    - Stations in ASOS_STATIONS bypass cumulative-counter detection (NWS
      airport gauges, 0.1-inch resolution; structurally different).
    - Consumer PWS that look like cumulative counters
      (`mono_frac ≥ MONO_FRAC_DETECT` AND `max > MONO_MIN_MAX`) get
      diff().clip(lower=0) applied so per-interval rain is recovered.

Other variables (temperature, condition, etc.) are passed through. Strings
(only `condition` in this dataset) get encoded to numeric codes plus a
JSON sidecar in :func:`encode_condition` so `save_grouped_pws` accepts them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Set, Tuple

import numpy as np
import pandas as pd
import xarray as xr
import netCDF4 as nc4

from ..netcdf_utils import save_grouped_pws


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Known NWS airport stations exposed through the WU API. They use 0.1-inch
# resolution gauges (not 0.01-inch like consumer PWS), so their mono_frac
# can climb above 0.97 just because most samples are zero — but the data is
# NOT a cumulative counter. Bypass the detector for them.
ASOS_STATIONS: Set[str] = {'KJFK', 'KLGA', 'KNYC', 'KEWR', 'KTEB'}

# Variables that carry rainfall signal — NaN'd out for `dropped` stations so
# a broken gauge can't poison downstream rate/accumulation analyses.
_PRECIP_VARS = ('rainfall_amount', 'rainfall_rate', 'precip_rate')


@dataclass
class QCConfig:
    """Tunable thresholds for the pyramid QC."""
    max_sample_mm     : float = 80.0
    max_hourly_mm     : float = 80.0
    max_daily_mm      : float = 200.0
    max_30d_mm        : float = 500.0
    min_total_mm      : float = 200.0
    max_total_mm      : float = 5000.0
    min_obs_hours     : int   = 1000
    mono_frac_detect  : float = 0.97
    mono_min_max      : float = 20.0
    asos_stations     : Set[str] = field(default_factory=lambda: set(ASOS_STATIONS))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STATION_META = ('lat', 'lon', 'elev', 'id',
                 'Height_above_ground_level', 'Environmental_class', 'hardware')


def _promote_station_meta(ds: xr.Dataset) -> xr.Dataset:
    """Move station-level scalars (lat/lon/elev/...) from data_vars → coords.

    `save_grouped_pws` iterates `data_vars` and treats every 1D variable as
    time-axis. Static per-station scalars must live in `coords` to avoid
    being mis-written.
    """
    for n in _STATION_META:
        if n in ds.data_vars:
            ds = ds.set_coords(n)
    return ds


def _to_da(series_values: np.ndarray, like_da: xr.DataArray) -> xr.DataArray:
    """Wrap a 1D numpy array back into a DataArray shaped like `like_da`."""
    v = np.asarray(series_values, dtype=np.float32)
    if like_da.ndim == 2:
        v = v.reshape(like_da.shape)
    return xr.DataArray(v, dims=like_da.dims, coords=like_da.coords,
                        attrs=like_da.attrs)


def _mask_by_period(
    ra_ser: pd.Series,
    bad_starts: pd.DatetimeIndex,
    period_end_fn,
) -> Tuple[pd.Series, int]:
    """Set ra_ser values to NaN for any timestamp inside [bad_start, period_end_fn(bad_start))."""
    if len(bad_starts) == 0:
        return ra_ser, 0
    mask = np.zeros(len(ra_ser), dtype=bool)
    idx_values = ra_ser.index.values
    for bs in bad_starts:
        end = period_end_fn(bs)
        mask |= (idx_values >= np.datetime64(bs)) & (idx_values < np.datetime64(end))
    out = ra_ser.where(~pd.Series(mask, index=ra_ser.index))
    return out, int(mask.sum())


# ---------------------------------------------------------------------------
# UTC time verification
# ---------------------------------------------------------------------------

def verify_utc_time(pws_dict: Dict[str, xr.Dataset], verbose: bool = True) -> bool:
    """Check that every group's time variable is UTC-decoded.

    Returns True iff all groups have a tz-aware or naive UTC datetime64 index.
    Prints a per-station summary if `verbose`.
    """
    bad = []
    for sid, ds in pws_dict.items():
        if 'time' not in ds:
            bad.append((sid, 'no time'))
            continue
        t = ds['time']
        # After xarray's CF decode, the units string lives in t.encoding (not
        # t.attrs). The reliable check is dtype: datetime64[ns] means xarray
        # parsed a CF-compliant 'X since Y' string and produced UTC-naive
        # datetime64. Fall back to encoding/attrs string just in case.
        is_dt64 = np.issubdtype(t.dtype, np.datetime64)
        units = t.encoding.get('units', '') or t.attrs.get('units', '')
        ok = is_dt64 or 'UTC' in units or 'utc' in units or 'since 1970' in units
        if not ok:
            bad.append((sid, f'dtype={t.dtype}, units={units!r}'))
    if verbose:
        if bad:
            print(f'UTC check: {len(bad)} groups have non-standard time units:')
            for sid, why in bad[:5]:
                print(f'  {sid}: {why}')
        else:
            sample = next(iter(pws_dict.values()))
            t0 = pd.Timestamp(sample['time'].values[0])
            t1 = pd.Timestamp(sample['time'].values[-1])
            print(f'UTC check: all {len(pws_dict)} groups OK '
                  f'(sample range: {t0} → {t1})')
    return len(bad) == 0


# ---------------------------------------------------------------------------
# Pyramid QC
# ---------------------------------------------------------------------------

def pyramid_qc(
    pws_dict: Dict[str, xr.Dataset],
    cfg: QCConfig | None = None,
) -> Tuple[Dict[str, xr.Dataset], pd.DataFrame]:
    """Run the pyramid QC across every station.

    Parameters
    ----------
    pws_dict : dict
        {station_id: xr.Dataset}  as returned by `load_pws_grouped`.
    cfg : QCConfig, optional
        Thresholds. Defaults to module-level constants.

    Returns
    -------
    cleaned : dict
        Same keys as pws_dict (ALL stations preserved). Each Dataset has
        `attrs['qc_status']` ∈ {as_is, as_is_asos, differentiated, dropped, no_rainfall}
        and `attrs['qc_reason']`. For 'dropped' stations every precip-related
        variable is NaN-filled (rainfall_amount / rainfall_rate / precip_rate);
        non-precip variables (temperature, humidity, condition, …) are kept.
    qc_log : pd.DataFrame
        One row per station with mono_frac, n_mask_* counts, final total/coverage.
    """
    cfg = cfg or QCConfig()
    cleaned: Dict[str, xr.Dataset] = {}
    log_rows = []

    for sid, ds in pws_dict.items():
        # --- no-rainfall passthrough ---
        if 'rainfall_amount' not in ds:
            new_ds = _promote_station_meta(ds.copy())
            new_ds.attrs['qc_status'] = 'no_rainfall'
            new_ds.attrs['qc_reason'] = 'no rainfall_amount in group'
            cleaned[sid] = new_ds
            log_rows.append({
                'station': sid, 'qc_status': 'no_rainfall',
                'qc_reason': 'no rainfall_amount',
                'is_asos': sid in cfg.asos_stations,
                'cumulative': False, 'mono_frac': 0.0,
                'n_mask_sample': 0, 'n_mask_hour': 0, 'n_mask_day': 0, 'n_mask_30d': 0,
                'final_total_mm': 0.0, 'final_n_hours': 0,
            })
            continue

        ra_da   = ds['rainfall_amount']
        ra_orig = ra_da.copy()
        ra_ser  = ra_da.squeeze(drop=True).to_series()
        ra_ser.index = pd.to_datetime(ra_ser.index)

        is_asos = sid in cfg.asos_stations

        # --- Step 0: cumulative-counter detection (skipped for ASOS) ---
        nona = ra_ser.dropna()
        mono = (nona.diff() >= 0).mean() if len(nona) > 1 else 0.0
        is_cumulative = (not is_asos) \
            and (mono >= cfg.mono_frac_detect) \
            and (nona.max() > cfg.mono_min_max)
        if is_cumulative:
            ra_ser = ra_ser.diff().clip(lower=0)
            if len(ra_ser):
                ra_ser.iloc[0] = 0.0

        # --- Step 1: sample-level clip ---
        sample_bad = ra_ser > cfg.max_sample_mm
        n_mask_sample = int(sample_bad.sum())
        ra_ser = ra_ser.where(~sample_bad)

        # --- Step 2: hour-level mask ---
        h = ra_ser.resample('1h').sum(min_count=1)
        bad_hours = h.index[h > cfg.max_hourly_mm]
        ra_ser, n_mask_hour = _mask_by_period(
            ra_ser, bad_hours, lambda t: t + pd.Timedelta(hours=1))

        # --- Step 3: day-level mask ---
        d = ra_ser.resample('1D').sum(min_count=1)
        bad_days = d.index[d > cfg.max_daily_mm]
        ra_ser, n_mask_day = _mask_by_period(
            ra_ser, bad_days, lambda t: t + pd.Timedelta(days=1))

        # --- Step 4: rolling 30-day window mask ---
        d = ra_ser.resample('1D').sum(min_count=1)
        roll30 = d.rolling('30D').sum()
        bad_30d = roll30.index[roll30 > cfg.max_30d_mm]
        ra_ser, n_mask_30d = _mask_by_period(
            ra_ser, bad_30d, lambda t: t + pd.Timedelta(days=1))

        # --- Step 5: station-level verdict ---
        h_final = ra_ser.resample('1h').sum(min_count=1)
        total   = float(h_final.sum())
        n_hours = int(h_final.notna().sum())

        if total > cfg.max_total_mm or total < cfg.min_total_mm \
                or n_hours < cfg.min_obs_hours:
            qc_status = 'dropped'
            qc_reason = (f'final total={total:.0f}mm '
                         f'(MIN={cfg.min_total_mm:.0f},MAX={cfg.max_total_mm:.0f}), '
                         f'n_hours={n_hours}(MIN={cfg.min_obs_hours})')
            # NaN-fill rainfall_amount; other precip-related vars get nulled
            # via _PRECIP_VARS in the per-station write below.
            working_da = _to_da(np.full_like(ra_orig.values, np.nan, dtype=float), ra_da)
        elif is_asos:
            qc_status = 'as_is_asos'
            qc_reason = '0.1-inch ASOS airport gauge (bypassed cumulative-counter detection)'
            working_da = _to_da(ra_ser.values, ra_da)
        elif is_cumulative:
            qc_status = 'differentiated'
            qc_reason = f'cumulative counter recovered (mono_frac={mono:.3f})'
            working_da = _to_da(ra_ser.values, ra_da)
        else:
            qc_status = 'as_is'
            qc_reason = ''
            working_da = _to_da(ra_ser.values, ra_da)

        new_ds = ds.copy()
        new_ds['rainfall_amount'] = working_da

        # For dropped stations, also null out the other precip-derived vars
        # so a broken gauge can't contaminate downstream rate / accumulation
        # analyses. Non-precip channels (temperature, humidity, …) stay.
        if qc_status == 'dropped':
            for pv in _PRECIP_VARS:
                if pv in new_ds.data_vars:
                    da = new_ds[pv]
                    new_ds[pv] = xr.DataArray(
                        np.full(da.shape, np.nan, dtype=float),
                        dims=da.dims, coords=da.coords, attrs=da.attrs,
                    )

        new_ds.attrs['qc_status'] = qc_status
        new_ds.attrs['qc_reason'] = qc_reason
        new_ds = _promote_station_meta(new_ds)
        cleaned[sid] = new_ds

        log_rows.append({
            'station'         : sid,
            'qc_status'       : qc_status,
            'qc_reason'       : qc_reason,
            'is_asos'         : is_asos,
            'cumulative'      : is_cumulative,
            'mono_frac'       : round(mono, 3),
            'n_mask_sample'   : n_mask_sample,
            'n_mask_hour'     : n_mask_hour,
            'n_mask_day'      : n_mask_day,
            'n_mask_30d'      : n_mask_30d,
            'final_total_mm'  : round(total, 1),
            'final_n_hours'   : n_hours,
        })

    return cleaned, pd.DataFrame(log_rows)


# ---------------------------------------------------------------------------
# Condition string encoding (so save_grouped_pws can write it as float32)
# ---------------------------------------------------------------------------

def _clean_label(v):
    if v is None:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    s = str(v).strip()
    if s == '' or s.lower() == 'nan':
        return None
    return s


def encode_condition(
    pws_clean: Dict[str, xr.Dataset],
    lookup_path: Path | None,
    var_name: str = 'condition',
) -> Dict[str, int]:
    """Replace `var_name` (string) in each station with float32 integer codes.

    Writes a JSON sidecar `{code: label}` to `lookup_path`. Returns the
    {label: code} map.
    """
    # Pass 1 — collect every unique label
    all_labels = set()
    for ds in pws_clean.values():
        if var_name not in ds:
            continue
        for v in ds[var_name].values.flat:
            lab = _clean_label(v)
            if lab is not None:
                all_labels.add(lab)

    lookup = {lab: i for i, lab in enumerate(sorted(all_labels))}

    # Pass 2 — replace each station's string DataArray with numeric codes
    for sid, ds in list(pws_clean.items()):
        if var_name not in ds:
            continue
        cond_da = ds[var_name]
        codes = np.array([
            float(lookup[lab]) if (lab := _clean_label(v)) is not None else np.nan
            for v in cond_da.values.flat
        ], dtype=np.float32).reshape(cond_da.shape)
        attrs = {**cond_da.attrs,
                 'description': 'integer-coded; decode via condition_lookup_json (file-level attr) or sidecar JSON'}
        if lookup_path is not None:
            attrs['lookup_file'] = Path(lookup_path).name
        pws_clean[sid][var_name] = xr.DataArray(
            codes, dims=cond_da.dims, coords=cond_da.coords,
            attrs=attrs,
        )

    code_to_label = {str(v): k for k, v in lookup.items()}
    if lookup_path is not None:
        with open(lookup_path, 'w') as f:
            json.dump(code_to_label, f, indent=2, sort_keys=True)
    # Stash the lookup on the dict so save_qc can embed it as a global attr
    pws_clean.setdefault('_condition_lookup', code_to_label)
    return lookup


# ---------------------------------------------------------------------------
# Write QC'd file
# ---------------------------------------------------------------------------

def save_qc(
    pws_clean: Dict[str, xr.Dataset],
    output_path: Path,
    qc_log: pd.DataFrame | None = None,
    extra_global_attrs: Dict[str, str] | None = None,
) -> Path:
    """Write `pws_clean` to a netCDF4 grouped file, plus per-group
    qc_status / qc_reason attributes.

    Calls `save_grouped_pws` (which only writes float32 variables), then
    re-opens the file in append mode to write the attributes that the
    saver doesn't carry.
    """
    output_path = Path(output_path)
    # Pull out any non-Dataset entries (like '_condition_lookup' from encode_condition)
    embed_lookup = pws_clean.pop('_condition_lookup', None)
    save_grouped_pws(pws_clean, output_path)

    with nc4.Dataset(output_path, 'a') as f:
        f.qc_pipeline = 'pws_qc.pyramid_qc (sample → hour → day → 30d → station)'
        if embed_lookup is not None:
            # JSON-stringify the lookup so the file is self-contained (no sidecar)
            f.condition_lookup_json = json.dumps(embed_lookup)
        for k, v in (extra_global_attrs or {}).items():
            setattr(f, k, v)
        for sid, ds in pws_clean.items():
            if sid not in f.groups:
                continue
            g = f.groups[sid]
            g.qc_status = ds.attrs.get('qc_status', '')
            g.qc_reason = ds.attrs.get('qc_reason', '')

            # save_grouped_pws only writes data_vars; lat/lon/elev were promoted
            # to coords during QC so they need to be written here. They live
            # along the singleton 'id' dim and so don't have a 'time' axis.
            for vname in ('lat', 'lon', 'elev'):
                if vname not in ds.coords and vname not in ds.data_vars:
                    continue
                if vname in g.variables:
                    continue  # already there
                try:
                    val = float(ds[vname].values.flat[0])
                except Exception:
                    continue
                v_meta = {
                    'lat':  ('degrees_in_WGS84_projection', 'latitude'),
                    'lon':  ('degrees_in_WGS84_projection', 'longitude'),
                    'elev': ('metres_above_sea',             'ground_elevation_above_sea_level'),
                }[vname]
                ncv = g.createVariable(vname, 'f8', ('id',))
                ncv.units, ncv.long_name = v_meta
                ncv[:] = val
    return output_path


def read_qc_status(path: Path) -> pd.DataFrame:
    """Return per-station qc_status / qc_reason from a written QC file."""
    rows = []
    with nc4.Dataset(path) as f:
        for sid in f.groups:
            g = f.groups[sid]
            rows.append({
                'station'   : sid,
                'qc_status' : getattr(g, 'qc_status', ''),
                'qc_reason' : getattr(g, 'qc_reason', ''),
            })
    return pd.DataFrame(rows)
