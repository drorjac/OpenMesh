"""Offline tests for src/netCDF_converters (synthetic inputs, no network)."""
import json
import sys
import zipfile
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd
import pytest
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "netCDF_converters"))
import asos_flat_to_netcdf as AF          # noqa: E402
import noaa_daily_to_netcdf as ND         # noqa: E402
import nycmesh_to_netcdf as NM            # noqa: E402
import nycmesh_to_opensense_cml as OS     # noqa: E402
import wu_pws_csv_to_netcdf as WU         # noqa: E402


# ---------------------------------------------------------------- WU PWS

def test_wu_time_zone_any_year_and_fall_back_hour():
    t = pd.Series(["2024-07-01 12:00:00", "2023-01-15 12:00:00", "2023-11-05 01:30:00"])
    utc = pd.to_datetime(WU.eastern_to_utc(t), unit="s")
    assert list(utc) == list(pd.to_datetime(["2024-07-01 16:00", "2023-01-15 17:00",
                                             "2023-11-05 05:30"]))   # repeated hour = EDT


def test_wu_units_and_wind():
    assert WU.fahrenheit_to_celsius(pd.Series(["32 °F"])).iloc[0] == pytest.approx(0.0)
    assert WU.inches_to_mm(pd.Series(["1.00 in"])).iloc[0] == pytest.approx(25.4)
    assert WU.cardinal_to_degrees("SW") == 225.0 and np.isnan(WU.cardinal_to_degrees("VAR"))
    r = WU.calc_precip_rate_from_accum(np.array([0, 1800, 3600.0]), np.array([0, 1, 1.0]))
    assert np.isnan(r[0]) and r[1] == pytest.approx(2.0) and r[2] == 0.0


def test_wu_csv_dir_to_netcdf(tmp_path):
    (tmp_path / "in").mkdir()
    pd.DataFrame({"Datetime": ["2024-01-10 10:00:00", "2024-01-10 10:05:00"],
                  "Precip. Rate.": ["0.00 in", "0.10 in"], "Precip. Accum.": ["0.00 in", "0.01 in"],
                  "Temperature": ["32 °F", "50 °F"], "Dew Point": ["30 °F", "31 °F"],
                  "Humidity": ["90 %", "91 %"], "Wind": ["N", "SW"], "Speed": ["1 mph", "2 mph"],
                  "Gust": ["2 mph", "3 mph"], "Pressure": ["30.00 in", "30.01 in"],
                  "UV": ["0", "0"], "Solar": ["0 w/m²", "1 w/m²"]}
                 ).to_csv(tmp_path / "in" / "KNYNEWYO1_2024.csv", index=False)
    pd.DataFrame({"Station ID": ["KNYNEWYO1"], "Latitude": [40.7], "Longitude": [-73.9],
                  "Elevation": [10.0]}).to_csv(tmp_path / "meta.csv", index=False)
    out = WU.convert_wu_csv_dir(tmp_path / "in", tmp_path / "meta.csv", tmp_path / "o.nc",
                                elev_units="m", verbose=False)
    g = netCDF4.Dataset(out)["KNYNEWYO1"]
    assert float(g["temperature"][0, 0]) == pytest.approx(0.0)
    assert float(g["rainfall_amount"][0, 1]) == pytest.approx(0.254)
    assert float(g["elev"][0]) == pytest.approx(10.0)
    assert int(g["time"][0]) == int(pd.Timestamp("2024-01-10 15:00").timestamp())


# ---------------------------------------------------------------- ASOS flat

def test_asos_flat_keeps_weather_codes(tmp_path):
    t = pd.date_range("2024-01-10", periods=3, freq="min")
    df = pd.DataFrame({"precip_amount": [0, 0.3, 0], "temperature": [0.5, 0.5, 0.5],
                       "precip_type": ["NP", "NP", "S"], "precip_category": ["dry", "dry", "snow"]}, index=t)
    meta = pd.DataFrame({"Latitude": [40.7], "Longitude": [-73.9], "Elevation": [5.0]},
                        index=pd.Index(["KLGA"], name="Station ID"))
    out = AF.asos_flat_to_netcdf({"LGA": df}, meta, tmp_path / "a.nc", verbose=False)
    ds = xr.open_dataset(out)
    assert list(ds.precip_category.values[0]) == ["dry", "dry", "snow"]
    assert float(ds.lat.values[0]) == pytest.approx(40.7)            # KLGA metadata ↔ LGA data


# ---------------------------------------------------------------- NYC Mesh raw

def _zip(path, day, old):
    t0 = pd.Timestamp(day).value // 10**6
    pts = [{"x": t0 + i * 60000, "y": -50.0 - i} for i in range(3)]
    field = pts if old else {"avg": pts}
    with zipfile.ZipFile(path / f"nycmesh-data-{day}.zip", "w") as z:
        z.writestr(f"devA-from-{day}.json", json.dumps({"signal": field, "remoteSignal": field}))
        z.writestr(f"devX-from-{day}.json", json.dumps({"signal": field}))       # unmapped


def test_nycmesh_old_and_new_format(tmp_path):
    _zip(tmp_path, "2024-07-15", old=True)
    _zip(tmp_path, "2024-07-16", old=False)
    pd.DataFrame({"cml_id": [7], "rx_name": ["devA"], "tx_name": ["devB"], "frequency": [60000.0]}
                 ).to_csv(tmp_path / "meta.csv", index=False)
    out = NM.process_date_range("2024-07-15", "2024-07-16", tmp_path / "meta.csv", tmp_path,
                                zip_dir=tmp_path)
    ds = xr.open_dataset(out)
    assert ds.sizes == {"time": 6, "cml_id": 1} and sorted(ds.data_vars) == ["rsl", "rsl_remote"]
    assert list(ds.device_name.values) == ["devA"] and ds.rsl.dtype == np.float32
    assert float(ds.rsl.isel(time=0, cml_id=0)) == -50.0


def test_nycmesh_mapping_tx_fallback():
    meta = pd.DataFrame({"cml_id": [1, 2], "rx_name": ["d1", "d2"], "tx_name": ["x", "d2"],
                         "frequency": [np.nan, 5000.0]})
    m = NM.build_device_to_cml_id_mapping(meta)
    assert m["d2"] == 2 and m["d1"] is None


# ---------------------------------------------------------------- OpenSense CML

def test_opensense_places_channels_and_shifts_epoch(tmp_path):
    raw = xr.Dataset({"rsl": (("time", "cml_id"), np.array([[-40.0, -41.0], [-42.0, -43.0]], "f4")),
                      "rsl_remote": (("time", "cml_id"), np.array([[-60.0, -61.0], [-62.0, -63.0]], "f4"))},
                     coords={"time": ("time", [0, 60], {"units": "seconds since 2025-12-01"}),
                             "cml_id": ["apiA", "apiB"]})
    raw.to_netcdf(tmp_path / "raw.nc")
    links = pd.DataFrame({"cml_id_new": [1, 1, 2], "sublink_id": [1, 2, 1],
                          "cml_api": ["apiA", "apiA", "apiB"], "data_channel": ["rsl", "rsl_remote", "rsl"],
                          "site_0_lat": 40.7, "site_0_lon": -73.9, "site_1_lat": 40.71, "site_1_lon": -73.91,
                          "length": 1000.0, "frequency": 60000.0, "polarization": "v", "device_name": "d"})
    OS.build_opensense_nc(reduced_main=links, src_nc_path=tmp_path / "raw.nc",
                          out_nc_path=tmp_path / "os.nc", verbose=False)
    d = netCDF4.Dataset(tmp_path / "os.nc")
    rsl = np.ma.filled(d["rsl"][:], np.nan)
    assert rsl.shape == (2, 2, 2)
    assert list(rsl[0, 0]) == [-40.0, -42.0] and list(rsl[0, 1]) == [-60.0, -62.0]
    assert list(rsl[1, 0]) == [-41.0, -43.0] and np.isnan(rsl[1, 1]).all()
    assert int(d["time"][0]) == int(pd.Timestamp("2025-12-01").timestamp())
    assert d["polarisation"][0, 0] == "vertical" and d.Conventions == "OpenSense-CML-v1.0"


# ---------------------------------------------------------------- NOAA daily

def test_noaa_daily_roundtrip(tmp_path):
    df = pd.DataFrame({"datetime": pd.date_range("2024-01-01", periods=3), "station_id": "USW1",
                       "lat": 40.7, "lon": -73.9, "elev": 10.0, "precip_amount": [0.0, 5.5, 1.0]})
    df.to_csv(tmp_path / "c.csv", index=False)
    ND.csv_to_netcdf(tmp_path / "c.csv", tmp_path / "d.nc", verbose=False)
    g = netCDF4.Dataset(tmp_path / "d.nc")["USW1"]
    assert list(np.round(g["precip_amount"][:], 2)) == [0.0, 5.5, 1.0]


# ---------------------------------------------------------------- default (Zenodo) converters

import openmesh_to_opensense_cml as OM    # noqa: E402
import wu_pws_csv_to_opensense as WZ      # noqa: E402


def test_openmesh_to_opensense_collapses_and_fills(tmp_path):
    t = pd.date_range("2024-01-01", periods=3, freq="min")
    ds = xr.Dataset(
        {"rsl": (("cml_id", "sublink_id", "time"), np.full((2, 2, 3), -50.0, "f4")),
         "site_0_lat": (("cml_id", "sublink_id"), np.array([[40.7, 40.7], [40.8, 40.8]])),
         "length": (("cml_id", "sublink_id"), np.array([[1000.0, 1000.0], [2000.0, 2000.0]])),
         "frequency": (("cml_id", "sublink_id"), np.array([[5500.0, 60000.0], [24000.0, np.nan]])),
         "polarization": (("cml_id", "sublink_id"), np.array([["v", ""], ["h", ""]], dtype=object))},
        coords={"cml_id": ["1", "2"], "sublink_id": ["sublink_1", "sublink_2"], "time": t})
    out = OM.convert_to_opensense_cml(ds, tmp_path / "os.nc")
    assert out["site_0_lat"].dims == ("cml_id",) and out["length"].dims == ("cml_id",)
    assert "site_0_lat" in out.coords and out["rsl"].attrs["units"] == "dBm"
    back = xr.open_dataset(tmp_path / "os.nc")
    assert list(back.polarization.values.ravel()) == ["v", "v", "h", "v"]      # '' -> 'v'
    assert back.attrs["Conventions"] == "OpenSense-CML-v1.0"


def test_wu_zenodo_converter_one_station(tmp_path):
    (tmp_path / "raw").mkdir()
    pd.DataFrame({"Datetime": ["2024-01-09 14:01:00", "2024-01-09 14:16:00", "2024-01-09 14:31:00"],
                  "Precip. Rate.": ["0.04 °in", "0.05 °in", "0.00 °in"],
                  "Precip. Accum.": ["0.04 °in", "0.05 °in", "0.05 °in"],
                  "Temperature": ["32.0 °F", "43.6 °F", "44.0 °F"], "Dew Point": ["30.0 °F"] * 3,
                  "Humidity": ["86 °%"] * 3, "Wind": ["East", "SSE", "N"], "Speed": ["10.0 °mph"] * 3,
                  "Gust": ["14.0 °mph"] * 3, "Pressure": ["30.24 °in"] * 3, "UV": [np.nan] * 3,
                  "Solar": ["w/m²"] * 3}).to_csv(tmp_path / "raw" / "KNYNEWYO1.csv", index=False)
    pd.DataFrame({"Station ID": ["KNYNEWYO1"], "Latitude": [40.7], "Longitude": [-73.9],
                  "Elevation": [10.0], "Description": ["WU PWS"]}).to_csv(tmp_path / "meta.csv")
    out, dropped = WZ.convert(tmp_path / "raw", tmp_path / "meta.csv", tmp_path / "o.nc",
                              start="2024-01-01", end="2024-02-01")
    d = netCDF4.Dataset(out)
    assert d.Conventions == "OpenSense-PWS-v1.0" and not dropped
    g = d[list(d.groups)[0]]
    ds = xr.open_dataset(out, group=list(d.groups)[0])
    assert "rainfall_amount" in ds and ds.sizes["time"] == 3
    assert float(np.ravel(ds["lat"].values)[0]) == pytest.approx(40.7)
    assert pd.Timestamp(ds.time.values[0]) == pd.Timestamp("2024-01-09 19:01")     # EST -> UTC
    assert g is not None
