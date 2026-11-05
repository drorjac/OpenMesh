"""Offline tests for the Weather Underground fetcher (no network, no API key)."""
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "fetch_data"))
from weather_underground import config as wu_config  # noqa: E402
from weather_underground import wu_fetch  # noqa: E402


def test_request_error_masks_api_key():
    url = "https://api.weather.com/v2/pws/history/hourly?stationId=K1&apiKey=SECRET123&units=m"
    resp = requests.Response()
    resp.status_code, resp.url = 401, url
    assert "SECRET123" not in wu_fetch._request_error(requests.HTTPError(f"401 for url: {url}", response=resp))
    resp.status_code = 500
    msg = wu_fetch._request_error(requests.HTTPError(f"500 for url: {url}", response=resp))
    assert "SECRET123" not in msg and "apiKey=***" in msg


def test_pipeline_without_key_fails_before_any_request(monkeypatch):
    monkeypatch.delenv("WU_API_KEY", raising=False)
    monkeypatch.setattr(wu_config, "load_api_key_from_shell_config", lambda: False)
    monkeypatch.setattr(wu_fetch, "fetch_all_data", lambda *a, **k: pytest.fail("requested without a key"))
    from datetime import datetime
    with pytest.raises(ValueError, match="WU_API_KEY not found"):
        wu_fetch.run_wu_pipeline(None, ["KNYNEWYO1805"], datetime(2024, 3, 22), datetime(2024, 3, 23))
