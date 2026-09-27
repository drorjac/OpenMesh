"""
Write NOAA GHCN-Daily station data as a grouped OpenSense-PWS-v1.0 netCDF
(one netCDF4 group per station, dims time and id=1).

Moved from src/fetch_data/noaa_daily/daily_fetch.py (`to_xarray_dict`, `save_netcdf`,
which still work and call this module). Output reads with
`analysis.netcdf_utils.load_pws_grouped`.

Input: {station_id: DataFrame} with a `datetime` column, station `lat` / `lon` /
`elev` columns and daily variables (precip_amount mm, snowfall cm, snow_depth cm,
temperature_max / _min / temperature degC), as produced by daily_fetch.py — or,
from the command line, the combined CSV it writes (noaa_daily_*_combined.csv).

Usage (CLI):
    python noaa_daily_to_netcdf.py <combined.csv> <output.nc>
Usage (import):
    from noaa_daily_to_netcdf import noaa_daily_to_netcdf
    noaa_daily_to_netcdf({sid: df}, output_path)
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


def to_xarray_dict(processed_data):
    """Convert {sid: DataFrame} → {sid: xr.Dataset} suitable for
    `save_grouped_pws()` in `analysis.netcdf_utils`.

    Each Dataset has a 'time' dim and station scalars (lat, lon, elev) as
    coordinates — same shape as the WU PWS / Mesonet groups already in the
    project, so `load_pws_grouped()` and `load_weather_networks()` work
    against the output without modification.
    """
    out = {}
    for sid, df in processed_data.items():
        if df.empty:
            continue
        df = df.set_index('datetime').sort_index()
        lat  = float(df['lat'].iloc[0])  if 'lat'  in df else float('nan')
        lon  = float(df['lon'].iloc[0])  if 'lon'  in df else float('nan')
        elev = float(df['elev'].iloc[0]) if 'elev' in df else float('nan')
        time_vars = [c for c in df.columns
                     if c not in ('station_id', 'lat', 'lon', 'elev')]
        ds = xr.Dataset(
            {v: (('time',), df[v].astype(np.float32).values) for v in time_vars},
            coords={'time': df.index.values},
        )
        ds = ds.assign_coords(lat=lat, lon=lon, elev=elev)
        ds.attrs['station_id'] = sid
        out[sid] = ds
    return out


def noaa_daily_to_netcdf(processed_data, output_path, verbose=True):
    """Write a grouped netCDF compatible with `analysis.netcdf_utils.load_pws_grouped`.

    Layout (per station group):
        dims  : time=N, id=1
        coords: time (seconds since 1970-01-01 UTC)
        vars  : id (str, dim=id), lat, lon, elev (f4, dim=id),
                <data vars> (f4, dim=time)
    """
    import netCDF4 as nc4
    output_path = Path(output_path)
    epoch = np.datetime64('1970-01-01T00:00:00')
    xr_dict = to_xarray_dict(processed_data)
    with nc4.Dataset(output_path, 'w', format='NETCDF4') as root:
        root.Conventions = 'OpenSense-PWS-v1.0'
        root.source = 'NOAA GHCN-Daily via src/netCDF_converters/noaa_daily_to_netcdf.py'
        root.title = 'NOAA GHCN-Daily station data'
        for sid, ds in xr_dict.items():
            grp = root.createGroup(sid)
            grp.createDimension('time', len(ds.time))
            grp.createDimension('id', 1)
            # time
            tv = grp.createVariable('time', 'f8', ('time',))
            tv.units = 'seconds since 1970-01-01 00:00:00 UTC'
            tv.calendar = 'standard'
            tv[:] = (ds.time.values.astype('datetime64[s]') - epoch).astype(float)
            # station scalars (id, lat, lon, elev) — written as (id,) so they
            # round-trip through `load_pws_grouped` as data_vars.
            sid_v = grp.createVariable('id', str, ('id',))
            sid_v[0] = sid
            for coord in ('lat', 'lon', 'elev'):
                val = float(ds.coords[coord].values) if coord in ds.coords else np.nan
                v = grp.createVariable(coord, 'f4', ('id',))
                v[:] = np.array([val], dtype=np.float32)
            # time-varying vars
            for vname in ds.data_vars:
                arr = ds[vname].values.astype(np.float32)
                v = grp.createVariable(vname, 'f4', ('time',),
                                       zlib=True, complevel=4,
                                       fill_value=np.float32(np.nan))
                v[:] = arr
    if verbose:
        size_mb = output_path.stat().st_size / 1e6
        print(f"Saved: {output_path}  ({size_mb:.1f} MB)")


def csv_to_netcdf(combined_csv, output_path, verbose=True):
    """Combined NOAA daily CSV (one row per station-day) -> grouped netCDF."""
    df = pd.read_csv(combined_csv, parse_dates=['datetime'], dtype={'station_id': str})
    processed = {sid: g.reset_index(drop=True) for sid, g in df.groupby('station_id')}
    noaa_daily_to_netcdf(processed, output_path, verbose=verbose)
    return Path(output_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('combined_csv', help='noaa_daily_*_combined.csv from daily_fetch.py')
    ap.add_argument('output_nc')
    a = ap.parse_args()
    csv_to_netcdf(a.combined_csv, a.output_nc)


if __name__ == '__main__':
    main()
