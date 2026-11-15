"""The v2 download constants match the Zenodo record (network; skipped offline)."""
import pytest
import requests

from fetch_data.OpenMesh import openmesh as om


def test_v2_md5_matches_zenodo():
    try:
        r = requests.get(f"https://zenodo.org/api/records/{om.ZENODO_V2_RECORD_ID}", timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        pytest.skip(f"Zenodo not reachable: {e}")
    files = {f["key"]: f["checksum"] for f in r.json()["files"]}
    assert om.ZENODO_V2_FILE in files
    assert files[om.ZENODO_V2_FILE] == f"md5:{om.ZENODO_V2_MD5}"
