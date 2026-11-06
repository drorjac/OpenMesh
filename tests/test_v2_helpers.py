"""The v2 record's helpers merged into the repo: bands, path table, flat ASOS, hourly summary,
the k-R law in CML-file units, and analysis.v2 reading through analysis.datasets."""
import numpy as np
import pandas as pd
import pytest

from analysis import datasets as D
from analysis.itu_rainrate import itu_k_alpha, rain_rate
from test_datasets import _cml, v2_record  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def _v2(monkeypatch, v2_record):
    monkeypatch.setenv('OPENMESH_V2_DIR', str(v2_record))
    monkeypatch.delenv('OPENMESH_DATA', raising=False)
    monkeypatch.setattr(D, '_active', None)
    D._OPEN.clear()
    yield
    for ds in D._OPEN.values():
        ds.close()
    D._OPEN.clear()


def test_band_and_split():
    assert [D.band_of(f) for f in (68_000, 60_000, 24_100, 5_500, np.nan)] == ['V60', 'V60', 'K24', 'C5', '']
    assert D.split_of(68_000) == 'V60 upper' and D.split_of(60_000) == 'V60 lower' and D.split_of(5_500) == 'C5'


def test_path_table_one_row_per_path():
    m = D.path_table('v2', availability=True)
    assert list(m.cml_id) == ['1', '2', '3'] and (m.band == 'V60').all()
    assert (m.n_radios == 1).all() and (m.bands == 'V60').all() and (m.availability == 1).all()


def test_open_asos_masks_flags():
    a = D.open_asos('v2')
    np.testing.assert_allclose(a.rainfall_amount.sel(id='LGA').values, [0.2, 0.3, np.nan, 0.1])
    assert int(D.open_asos('v2', only_ok=False).rainfall_amount.sel(id='LGA').isnull().sum()) == 0


def test_hourly_summary_level_and_counts():
    H = D.hourly_summary('v2')
    assert H.sizes == {'cml_id': 3, 'sublink_id': 4, 'time': 6}
    np.testing.assert_allclose(H['median'].sel(cml_id='1', sublink_id='sublink_1').values,
                               [-50, -50, -50, -60, -60, -60])          # rsl, then rsl_avg
    below = H['n_max_below'].sel(cml_id='1', sublink_id='sublink_1').values
    np.testing.assert_array_equal(below, [1, 1, 1, 0, 0, 0])          # rsl_max -55 under rsl -50, over rsl_avg -60

def test_rain_rate_inverts_itu_in_file_units():
    k, a = itu_k_alpha(68.0, 'V')
    A = k * 10.0 ** a * 1.3
    np.testing.assert_allclose(rain_rate([A, 0.0, -1.0, np.nan], 1300, 68_000, 'vertical'),
                               [10.0, 0.0, 0.0, np.nan])
    assert rain_rate([1e-6], 1300, 68_000, 'vertical')[0] == 0.0       # below r_min


def test_v2_helpers_read_through_datasets(v2_record):
    from analysis import v2 as om
    assert om.setup() == v2_record and D.active() == 'v2'
    assert om.open_links() is D.open_cml('v2')                         # one shared handle
    assert list(om.link_meta().cml_id) == ['1', '2', '3']
    x = om.links(cml_ids=['1'], start='2025-04-20 00:00', end='2025-04-20 02:00')
    assert x.sizes['time'] == 3 and set(x.data_vars) == {'rsl', 'rsl_avg', 'rsl_max'}
    lvl = om.link_level(om.open_links(), '1')
    assert len(lvl) == 6 and lvl.iloc[-1] == -60


# ---- downloads: ensure() and the resumable, checked download ------------------

def test_ensure_skips_present_and_fetches_missing(monkeypatch, tmp_path, v2_record):
    calls = []
    monkeypatch.setattr(D, 'fetch_v2', lambda: calls.append('v2'))
    assert D.ensure('v2').cml.exists() and calls == []                  # present: no download
    monkeypatch.setenv('OPENMESH_V2_DIR', str(tmp_path / 'empty'))
    with pytest.raises(FileNotFoundError):                               # fetcher stubbed: still missing
        D.ensure('v2')
    assert calls == ['v2']


class _Resp:
    def __init__(self, body, status):
        self.body, self.status_code = body, status
        self.headers = {'content-length': str(len(body))}
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def raise_for_status(self):
        pass
    def iter_content(self, chunk_size):
        yield from (self.body[i:i + chunk_size] for i in range(0, len(self.body), chunk_size))


def test_download_resumes_part_file_and_checks_md5(monkeypatch, tmp_path):
    import hashlib
    from fetch_data.OpenMesh import openmesh as O
    data = bytes(range(256)) * 40
    seen = []

    def get(url, stream, timeout, headers):
        seen.append(headers.get('Range'))
        start = int(headers['Range'][6:-1]) if headers else 0
        return _Resp(data[start:], 206 if headers else 200)

    monkeypatch.setattr(O.requests, 'get', get)
    out = tmp_path / 'f.zip'
    (tmp_path / 'f.zip.part').write_bytes(data[:1000])                  # an interrupted download
    assert O.download_file('u', out, md5=hashlib.md5(data).hexdigest(), retries=1)
    assert out.read_bytes() == data and seen == ['bytes=1000-'] and not (tmp_path / 'f.zip.part').exists()
    bad = tmp_path / 'g.zip'
    assert not O.download_file('u', bad, md5='0' * 32, retries=1)
    assert not bad.exists() and not (tmp_path / 'g.zip.part').exists()
