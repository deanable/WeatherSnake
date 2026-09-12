"""Tests for the Datawrapper API client (v3 create/data/publish flow)."""
import os
import sys

import pandas as pd
import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import datawrapper_client  # noqa: E402
from datawrapper_client import (  # noqa: E402
    DatawrapperError, chart_csv, csv_headers, title_text, check_credentials,
    create_chart,
)


def _df():
    return pd.DataFrame({
        "date_label": ["December", "January", "February"],
        "temp_max": [26.0, 27.1, 28.2],
        "temp_min": [18.0, 19.0, 20.0],
        "precip_sum": [72.0, 65.5, 58.0],
    })


# ---------------------------------------------------------------------------
# Data shaping
# ---------------------------------------------------------------------------
def test_chart_csv_shape():
    csv = chart_csv(_df())
    lines = csv.strip().split("\n")
    assert lines[0] == "date_label,temp_max,temp_min,precip_sum"
    assert lines[1] == "December,26.0,18.0,72.0"
    assert lines[3] == "February,28.2,20.0,58.0"


def test_chart_csv_caps_rows():
    big = pd.DataFrame({
        "date_label": [f"Day {i}" for i in range(5000)],
        "temp_max": [20.0] * 5000, "temp_min": [10.0] * 5000,
        "precip_sum": [0.0] * 5000,
    })
    csv = chart_csv(big)
    assert len(csv.strip().split("\n")) == datawrapper_client.MAX_ROWS + 1


def test_csv_headers_units():
    assert csv_headers("metric")[0] == "Max Temp (°C)"
    assert csv_headers("imperial")[2] == "Precip (inch)"


def test_title_text():
    assert title_text("Durban", "Summer") == "Historical Weather for Durban (Summer)"


# ---------------------------------------------------------------------------
# create_chart — requests monkeypatched, no network
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else (
            __import__("json").dumps(body if body is not None else {}))

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def _patch_happy_path(monkeypatch, calls):
    """Wire the four v3 endpoints to canned responses."""
    def fake_request(method, url, json=None, data=None, headers=None, timeout=None):
        calls.append({"method": method, "url": url, "json": json,
                      "data": data, "headers": headers})
        if method == "POST" and url.endswith("/v3/charts"):
            return _FakeResponse(201, {"id": "abc123", "title": "t"})
        if method == "PUT" and "/data" in url:
            return _FakeResponse(204)
        if method == "PATCH":
            return _FakeResponse(200, {"id": "abc123"})
        if method == "POST" and url.endswith("/publish"):
            return _FakeResponse(200, {"data": {
                "publicUrl": "https://datawrapper.dwcdn.net/abc123/1/"}})
        raise AssertionError(f"unexpected {method} {url}")

    monkeypatch.setattr(datawrapper_client.requests, "request", fake_request)


def test_create_chart_full_flow(monkeypatch):
    calls = []
    _patch_happy_path(monkeypatch, calls)
    result = create_chart(_df(), "Durban", "Summer", "metric", "TOKEN")

    assert result == {"chartId": "abc123",
                      "url": "https://datawrapper.dwcdn.net/abc123/1/"}
    steps = [(c["method"], c["url"]) for c in calls]
    assert steps == [
        ("POST", f"{datawrapper_client.API_BASE}/v3/charts"),
        ("PUT", f"{datawrapper_client.API_BASE}/v3/charts/abc123/data"),
        ("PATCH", f"{datawrapper_client.API_BASE}/v3/charts/abc123"),
        ("POST", f"{datawrapper_client.API_BASE}/v3/charts/abc123/publish"),
    ]
    # Create carries the title and the chart type.
    create_body = calls[0]["json"]
    assert create_body["title"] == "Historical Weather for Durban (Summer)"
    assert create_body["type"] == datawrapper_client.CHART_TYPE
    # Data upload is CSV with the right content type.
    upload = calls[1]
    assert upload["headers"]["Content-Type"] == "text/csv"
    assert upload["data"].startswith(b"date_label,temp_max")
    # Metadata patch sets axes and labels.
    meta = calls[2]["json"]["metadata"]
    assert meta["axes"]["x"] == "date_label"
    assert "temp_max" in meta["axes"]["y"]
    # Publish is the last step.
    assert steps[-1][1].endswith("/publish")


def test_bearer_header_sent(monkeypatch):
    calls = []
    _patch_happy_path(monkeypatch, calls)
    create_chart(_df(), "X", "Y", "metric", "SECRET_TOKEN")
    assert all(c["headers"]["Authorization"] == "Bearer SECRET_TOKEN" for c in calls)


def test_missing_token_raises_friendly_error():
    with pytest.raises(DatawrapperError) as excinfo:
        create_chart(_df(), "X", "Y", "metric", "")
    assert "API token is required" in str(excinfo.value)


def test_create_without_chart_id_raises(monkeypatch):
    monkeypatch.setattr(datawrapper_client.requests, "request",
                        lambda *a, **k: _FakeResponse(201, {}))
    with pytest.raises(DatawrapperError, match="no chart ID"):
        create_chart(_df(), "X", "Y", "metric", "TOKEN")


def test_publish_without_url_falls_back_to_dwcdn(monkeypatch):
    calls = []

    def fake_request(method, url, **k):
        calls.append((method, url))
        if method == "POST" and url.endswith("/v3/charts"):
            return _FakeResponse(201, {"id": "xyz789"})
        return _FakeResponse(200, {})

    monkeypatch.setattr(datawrapper_client.requests, "request", fake_request)
    result = create_chart(_df(), "X", "Y", "metric", "TOKEN")
    assert result["url"] == "https://datawrapper.dwcdn.net/xyz789/"


# ---------------------------------------------------------------------------
# HTTP error mapping
# ---------------------------------------------------------------------------
def _always(status_code, body=None, text=None):
    """A fake request that always returns the same canned response."""
    def fake_request(method, url, **k):
        return _FakeResponse(status_code, body=body, text=text)
    return fake_request


def test_http_401_maps_to_token_hint(monkeypatch):
    monkeypatch.setattr(datawrapper_client.requests, "request",
                        _always(401, text="bad token"))
    with pytest.raises(DatawrapperError) as excinfo:
        create_chart(_df(), "X", "Y", "metric", "TOKEN")
    msg = str(excinfo.value)
    assert "HTTP 401" in msg and "token" in msg.lower()


def test_http_429_maps_to_quota_hint(monkeypatch):
    monkeypatch.setattr(datawrapper_client.requests, "request",
                        _always(429, text="quota"))
    with pytest.raises(DatawrapperError, match="quota"):
        create_chart(_df(), "X", "Y", "metric", "TOKEN")


def test_http_500_maps_to_retry_hint(monkeypatch):
    monkeypatch.setattr(datawrapper_client.requests, "request",
                        _always(503, text="maintenance"))
    with pytest.raises(DatawrapperError, match="try again later"):
        create_chart(_df(), "X", "Y", "metric", "TOKEN")


def test_non_json_success_raises(monkeypatch):
    monkeypatch.setattr(datawrapper_client.requests, "request",
                        _always(200, text="<html>gateway</html>"))
    with pytest.raises(DatawrapperError, match="unreadable response"):
        create_chart(_df(), "X", "Y", "metric", "TOKEN")


def test_network_error_maps_to_connectivity_message(monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("no route to host")
    monkeypatch.setattr(datawrapper_client.requests, "request", boom)
    with pytest.raises(DatawrapperError) as excinfo:
        create_chart(_df(), "X", "Y", "metric", "TOKEN")
    assert "Could not reach Datawrapper" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Credential check
# ---------------------------------------------------------------------------
def test_check_credentials_pass(monkeypatch):
    monkeypatch.setattr(datawrapper_client.requests, "request",
                        lambda *a, **k: _FakeResponse(200, {"id": "me"}))
    assert check_credentials("K") is None


def test_check_credentials_rejected_token(monkeypatch):
    monkeypatch.setattr(datawrapper_client.requests, "request",
                        _always(401, text="bad creds"))
    problem = check_credentials("K")
    assert problem and "HTTP 401" in problem


# ---------------------------------------------------------------------------
# Live integration test — networked, opt-in via the `live` marker
#
# Set DATAWRAPPER_ACCESS_TOKEN to a valid token (free account:
# app.datawrapper.de, Settings & Account > API tokens) and run:
#
#     pytest -m live
#
# Without the env var the test skips, so CI and ordinary runs stay offline.
# The chart the test creates is deleted afterwards so it does not linger in
# (or count permanently against) the account.
# ---------------------------------------------------------------------------
@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get(datawrapper_client.ENV_TOKEN, "").strip(),
    reason="DATAWRAPPER_ACCESS_TOKEN not set — skipping live Datawrapper API test",
)
def test_live_create_and_publish_roundtrip():
    """Full v3 round-trip against the real API: me -> create -> publish -> delete."""
    token = os.environ[datawrapper_client.ENV_TOKEN].strip()

    problem = check_credentials(token)
    if problem:
        pytest.fail(f"DATAWRAPPER_ACCESS_TOKEN was rejected by the API: {problem}")

    result = create_chart(_df(), "Live Test", "Smoke Window", "metric", token)
    chart_id = result["chartId"]
    try:
        assert chart_id, "create_chart returned an empty chart id"
        assert result["url"].startswith("https://"), result["url"]
        # Publishing must yield a publicly reachable page.
        page = requests.get(result["url"], timeout=datawrapper_client.REQUEST_TIMEOUT)
        assert page.status_code == 200, (
            f"public chart URL returned HTTP {page.status_code}")
    finally:
        try:
            datawrapper_client._request("DELETE", f"v3/charts/{chart_id}", token)
        except datawrapper_client.DatawrapperError as exc:
            print(f"note: could not clean up live test chart {chart_id}: {exc}")
