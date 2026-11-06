"""Checks of the record: the metadata tables against the netCDF files, and the OpenSense conventions."""
import netCDF4
import numpy as np
import pandas as pd

from . import io

CML_SPEC = {  # variable: (requisite, units, long_name), OpenSense CML
    "time": ("Required", "seconds since 1970-01-01 00:00:00 UTC", "time_utc"),
    "cml_id": ("Required", None, "commercial_microwave_link_identifier"),
    "sublink_id": ("Required", None, "sublink_identifier"),
    "site_0_lat": ("Required", "degrees_in_WGS84_projection", "site_0_latitude"),
    "site_0_lon": ("Required", "degrees_in_WGS84_projection", "site_0_longitude"),
    "site_0_alt": ("Recommended", "metres_above_sea", "antenna_altitude_above_sea_level_at_site_0"),
    "site_1_lat": ("Required", "degrees_in_WGS84_projection", "site_1_latitude"),
    "site_1_lon": ("Required", "degrees_in_WGS84_projection", "site_1_longitude"),
    "site_1_alt": ("Recommended", "metres_above_sea", "antenna_altitude_above_sea_level_at_site_1"),
    "length": ("Optional", "m", "distance_between_pair_of_antennas"),
    "frequency": ("Required", "MHz", "sublink_frequency"),
    "polarization": ("Recommended", "no units", "sublink_polarization"),
    "rsl": ("Required*", "dBm", "received_signal_level"),
    "rsl_avg": ("Optional", "dBm", "averaged_received_signal_level_over_time_window"),
    "rsl_max": ("Required*", "dBm", "maximum_received_signal_level_over_time_window"),
}
PWS_SPEC = {  # OpenSense PWS
    "time": ("Required", "seconds since 1970-01-01 00:00:00 UTC", "time_utc"),
    "id": ("Required", None, "personal_weather_station_identifier"),
    "lat": ("Required", "degrees_in_WGS84_projection", "latitude"),
    "lon": ("Required", "degrees_in_WGS84_projection", None),
    "elev": ("Recommended", "metres_above_sea", "ground_elevation_above_sea_level"),
    "rainfall_amount": ("Required", "mm", "rainfall_amount_per_time_unit"),
    "temperature": ("Optional", "degrees_celsius", None),
    "relative_humidity": ("Optional", "%", None),
    "wind_velocity": ("Optional", "ms-1", None),
    "wind_direction": ("Optional", "degrees", None),
}


def convention(kind="links"):
    """One row per variable of the OpenSense convention: present, units and long_name as specified."""
    path, spec = ((io.data_dir() / "data/links/openmesh_links.nc", CML_SPEC) if kind == "links"
                  else (io.data_dir() / "data/weather/asos/openmesh_asos.nc", PWS_SPEC))
    with netCDF4.Dataset(path) as nc:
        rows = []
        for v, (req, u, ln) in spec.items():
            x = nc[v] if v in nc.variables else None
            rows.append(dict(variable=v, requisite=req, present=x is not None,
                             units=(u is None) or (x is not None and getattr(x, "units", None) == u),
                             long_name=(ln is None) or (x is not None and getattr(x, "long_name", None) == ln)))
        extra = [v for v in nc.variables if v not in spec]
    t = pd.DataFrame(rows).set_index("variable")
    t.attrs["extra"] = extra
    return t


def record():
    """PASS / FAIL table: the metadata tables against the netCDF files, the OpenSense conventions, ASOS and radar."""
    ln, sm = io.open_links(), io.sublink_meta()
    res = []

    def check(name, ok, detail=""):
        res.append(dict(check=name, result="PASS" if ok else "FAIL", detail=detail))

    eq = {"ends": [], "frequency": [], "length": [], "polarization": []}
    for r in sm.itertuples():
        x = ln.sel(cml_id=r.cml_id, sublink_id=r.sublink_id)
        a, b = ("0", "1") if r.direction == "A" else ("1", "0")
        eq["ends"].append(np.allclose([r.site_0_lat, r.site_0_lon, r.site_1_lat, r.site_1_lon],
                                      [float(x[f"site_{a}_lat"]), float(x[f"site_{a}_lon"]), float(x[f"site_{b}_lat"]),
                                       float(x[f"site_{b}_lon"])], atol=1e-6))
        eq["frequency"].append(np.isclose(r.frequency, float(x.frequency)))
        eq["length"].append(np.isclose(r.length, float(x.length), rtol=0, atol=0.05))    # the CSV rounds to 0.1 m
        eq["polarization"].append(r.polarization == str(x.polarization.values))
    for k, v in eq.items():
        check(f"links_metadata.csv = netCDF: {k}", all(v), f"{sum(v)} of {len(v)} sublinks")
    used = set(zip(sm.cml_id, sm.sublink_id))
    f = ln.frequency.to_series().dropna()
    check("frequency set exactly on the sublinks of the table", set(f.index) == used, f"{len(used)} sublinks")
    n = (ln.rsl.notnull().any("time") | ln.rsl_avg.notnull().any("time")).to_series()
    check("every sublink of the table has values, no other slot has any",
          int(n[n].index.isin(list(used)).sum()) == len(used) and int((n & ~n.index.isin(list(used))).sum()) == 0)
    check("no empty position, length or frequency",
          int(sm[["site_0_lat", "site_0_lon", "site_1_lat", "site_1_lon", "frequency", "length"]].isna().sum().sum()) == 0)
    t = pd.DatetimeIndex(ln.time.values)
    check("time axis sorted and unique", bool(t.is_monotonic_increasing and t.is_unique), f"{len(t):,} stamps")
    for kind in ("links", "asos"):
        c = convention(kind)
        ok = c[c.requisite.str.startswith("Required") & ~c.index.isin(["rsl", "rsl_max"])]
        check(f"OpenSense {'CML' if kind == 'links' else 'PWS'}: required variables, units, long names",
              bool(ok.present.all() and c[c.present].units.all() and c[c.present].long_name.all()),
              f"{int(c.present.sum())} of {len(c)} spec variables present")
    a, st = io.asos(only_ok=False), io.asos_stations()
    ids = list(a.id.values)
    check("asos_stations.csv = netCDF (stations, positions)",
          sorted(ids) == sorted(st.index) and all(np.allclose(a[v].values, st.loc[ids, c].values)
                                                  for v, c in [("lat", "Latitude"), ("lon", "Longitude"), ("elev", "Elevation")]))
    ev = io.radar_events()
    ok = []
    for e in ev.itertuples():
        r = io.radar(e.kind, e.day)
        ok.append(abs(float(r.rainfall_amount_1h.sum("time_1h").mean()) - e.radar_mean_mm) < 0.06
                  and (r.sizes["lat"], r.sizes["lon"]) == (e.n_lat, e.n_lon))
    check("radar files = radar_events.csv (totals, grid)", all(ok), f"{len(ok)} days")
    return pd.DataFrame(res).set_index("check")
