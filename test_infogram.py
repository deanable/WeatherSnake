"""Tests for the Infogram API client (current api.infogram.com token API)."""
import json
import os
import sys

import pandas as pd
import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import infogram_client  # noqa: E402
from infogram_client import (  # noqa: E402
    InfogramError, chart_data, title_text, check_credentials, create_infographic,
    _find_entities,
)


# ---------------------------------------------------------------------------
# Data shaping
# ---------------------------------------------------------------------------
def _df():
    return pd.DataFrame({
        "date_label": ["December", "January", "February"],
        "temp_max": [26.0, 27.1, 28.2],
        "temp_min": [18.0, 19.0, 20.0],
        "precip_sum": [72.0, 65.5, 58.0],
    })


def test_chart_data_is_documented_schema():
    sheets = chart_data(_df(), "metric")
    assert isinstance(sheets, list) and len(sheets) == 1
    sheet = sheets[0]
    assert sheet["title"] == "Weather data"
    data = sheet["data"]
    assert data[0] == ["Date", "Max Temp (°C)", "Min Temp (°C)", "Precip (mm)"]
    assert data[1] == ["December", "26.0", "18.0", "72.0"]
    assert data[3] == ["February", "28.2", "20.0", "58.0"]


def test_chart_data_imperial_headers():
    sheets = chart_data(_df(), "imperial")
    assert any("°F" in h for h in sheets[0]["data"][0])
    assert any("inch" in h for h in sheets[0]["data"][0])


def test_chart_data_caps_rows():
    big = pd.DataFrame({
        "date_label": [f"Day {i}" for i in range(600)],
        "temp_max": [20.0] * 600, "temp_min": [10.0] * 600,
        "precip_sum": [0.0] * 600,
    })
    sheets = chart_data(big, "metric")
    assert len(sheets[0]["data"]) == infogram_client.MAX_TABLE_ROWS + 1


def test_title_text():
    assert title_text("Durban", "Summer") == "WeatherSnake: Durban (Summer)"


# ---------------------------------------------------------------------------
# Entity discovery
# ---------------------------------------------------------------------------
def test_find_entities_picks_first_of_each():
    entities = [
        {"entityId": "t1", "type": "TEXT", "value": "Title"},
        {"entityId": "c1", "type": "CHART", "data": []},
        {"entityId": "t2", "type": "TEXT", "value": "Other"},
        {"entityId": "i1", "type": "IMAGE", "assetId": "x.png"},
    ]
    text_id, chart_id = _find_entities(entities)
    assert text_id == "t1" and chart_id == "c1"


def test_find_entities_missing_chart_raises():
    with pytest.raises(InfogramError, match="no chart block"):
        _find_entities([{"entityId": "t1", "type": "TEXT"}])


# ---------------------------------------------------------------------------
# create_infographic — requests monkeypatched, no network
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else json.dumps(body if body is not None else {})

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def _patch_happy_path(monkeypatch, calls):
    """Wire the four documented endpoints to canned responses."""
    def fake_post(url, json=None, timeout=None, headers=None):
        calls.append(("POST", url, json))
        if "copyProject" in url:
            return _FakeResponse(200, {"projectId": "new-uuid"})
        if "updateProjectEntities" in url:
            return _FakeResponse(200, {})
        if "publishProject" in url:
            return _FakeResponse(200, {"webUrl": "https://infogram.com/abc123",
                                       "embedCodeId": "_/x"})
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url, params=None, timeout=None, headers=None):
        calls.append(("GET", url, params))
        assert params["projectId"] == "new-uuid"
        return _FakeResponse(200, [
            {"entityId": "t1", "type": "TEXT", "value": "Template title"},
            {"entityId": "c1", "type": "CHART", "data": []},
        ])

    monkeypatch.setattr(infogram_client.requests, "post", fake_post)
    monkeypatch.setattr(infogram_client.requests, "get", fake_get)


def test_create_infographic_full_flow(monkeypatch):
    calls = []
    _patch_happy_path(monkeypatch, calls)
    result = create_infographic(_df(), "Durban", "Summer", "metric", "TOKEN", "TPL")

    assert result == {"projectId": "new-uuid", "url": "https://infogram.com/abc123"}
    methods = [(m, u) for m, u, _ in calls]
    assert methods == [
        ("POST", f"{infogram_client.API_BASE}/copyProject"),
        ("GET", f"{infogram_client.API_BASE}/getProjectData"),
        ("POST", f"{infogram_client.API_BASE}/updateProjectEntities"),
        ("POST", f"{infogram_client.API_BASE}/publishProject"),
    ]
    # Copy carries the template id and a title.
    copy_payload = calls[0][2]
    assert copy_payload["projectId"] == "TPL"
    assert "Durban" in copy_payload["title"]
    # Update pushes text + chart entities.
    update_payload = calls[2][2]
    assert update_payload["projectId"] == "new-uuid"
    assert update_payload["entities"]["t1"] == "WeatherSnake: Durban (Summer)"
    assert update_payload["entities"]["c1"]["data"][0]["data"][0] == [
        "Date", "Max Temp (°C)", "Min Temp (°C)", "Precip (mm)"]
    # Publish defaults to a private link.
    publish_payload = calls[3][2]
    assert publish_payload["privacy"] == "private"


def test_create_infographic_public(monkeypatch):
    calls = []
    _patch_happy_path(monkeypatch, calls)
    create_infographic(_df(), "X", "Y", "metric", "TOKEN", "TPL", public=True)
    assert calls[3][2]["privacy"] == "public"


def test_bearer_header_sent(monkeypatch):
    headers_seen = {}

    def fake_post(url, json=None, timeout=None, headers=None):
        headers_seen.update(headers or {})
        if "copyProject" in url:
            return _FakeResponse(200, {"projectId": "p"})
        return _FakeResponse(200, {"webUrl": "https://infogram.com/x"})

    def fake_get(*a, **k):
        return _FakeResponse(200, [{"entityId": "c", "type": "CHART"}])

    monkeypatch.setattr(infogram_client.requests, "post", fake_post)
    monkeypatch.setattr(infogram_client.requests, "get", fake_get)
    create_infographic(_df(), "X", "Y", "metric", "SECRET_TOKEN", "TPL")
    assert headers_seen.get("Authorization") == "Bearer SECRET_TOKEN"


def test_missing_token_raises_friendly_error():
    with pytest.raises(InfogramError) as excinfo:
        create_infographic(_df(), "X", "Y", "metric", "", "TPL")
    assert "API token is required" in str(excinfo.value)


def test_missing_template_raises_friendly_error():
    with pytest.raises(InfogramError) as excinfo:
        create_infographic(_df(), "X", "Y", "metric", "TOKEN", "")
    assert "template project ID" in str(excinfo.value)


def test_copy_without_project_id_raises(monkeypatch):
    monkeypatch.setattr(infogram_client.requests, "post",
                        lambda *a, **k: _FakeResponse(200, {}))
    with pytest.raises(InfogramError, match="no project ID"):
        create_infographic(_df(), "X", "Y", "metric", "TOKEN", "TPL")


def test_template_without_chart_raises(monkeypatch):
    monkeypatch.setattr(infogram_client.requests, "post",
                        lambda *a, **k: _FakeResponse(200, {"projectId": "p"}))
    monkeypatch.setattr(infogram_client.requests, "get",
                        lambda *a, **k: _FakeResponse(200, [
                            {"entityId": "t1", "type": "TEXT"}]))
    with pytest.raises(InfogramError, match="no chart block"):
        create_infographic(_df(), "X", "Y", "metric", "TOKEN", "TPL")


def test_publish_without_url_raises(monkeypatch):
    monkeypatch.setattr(infogram_client.requests, "post", lambda url, **k: (
        _FakeResponse(200, {"projectId": "p"}) if "copyProject" in url
        else _FakeResponse(200, {}) if "updateProject" in url
        else _FakeResponse(200, {})))
    monkeypatch.setattr(infogram_client.requests, "get",
                        lambda *a, **k: _FakeResponse(200, [
                            {"entityId": "c", "type": "CHART"}]))
    with pytest.raises(InfogramError, match="did not return a share URL"):
        create_infographic(_df(), "X", "Y", "metric", "TOKEN", "TPL")


# ---------------------------------------------------------------------------
# HTTP error mapping
# ---------------------------------------------------------------------------
def test_http_401_maps_to_token_hint(monkeypatch):
    monkeypatch.setattr(infogram_client.requests, "post",
                        lambda *a, **k: _FakeResponse(401, text="bad token"))
    with pytest.raises(InfogramError) as excinfo:
        create_infographic(_df(), "X", "Y", "metric", "TOKEN", "TPL")
    msg = str(excinfo.value)
    assert "HTTP 401" in msg and "token" in msg.lower()


def test_http_404_maps_to_template_hint(monkeypatch):
    monkeypatch.setattr(infogram_client.requests, "get",
                        lambda *a, **k: _FakeResponse(404, text="nope"))
    monkeypatch.setattr(infogram_client.requests, "post",
                        lambda *a, **k: _FakeResponse(200, {"projectId": "p"}))
    with pytest.raises(InfogramError, match="template project ID"):
        create_infographic(_df(), "X", "Y", "metric", "TOKEN", "TPL")


def test_http_500_maps_to_retry_hint(monkeypatch):
    monkeypatch.setattr(infogram_client.requests, "post",
                        lambda *a, **k: _FakeResponse(503, text="maintenance"))
    with pytest.raises(InfogramError, match="try again later"):
        create_infographic(_df(), "X", "Y", "metric", "TOKEN", "TPL")


def test_non_json_success_raises(monkeypatch):
    monkeypatch.setattr(infogram_client.requests, "post",
                        lambda *a, **k: _FakeResponse(200, text="<html>gateway</html>"))
    with pytest.raises(InfogramError, match="unreadable response"):
        create_infographic(_df(), "X", "Y", "metric", "TOKEN", "TPL")


def test_network_error_maps_to_connectivity_message(monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("no route to host")
    monkeypatch.setattr(infogram_client.requests, "post", boom)
    with pytest.raises(InfogramError) as excinfo:
        create_infographic(_df(), "X", "Y", "metric", "TOKEN", "TPL")
    assert "Could not reach Infogram" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Credential check
# ---------------------------------------------------------------------------
def test_check_credentials_pass(monkeypatch):
    monkeypatch.setattr(infogram_client.requests, "get",
                        lambda *a, **k: _FakeResponse(200, []))
    assert check_credentials("K", "TPL") is None


def test_check_credentials_bad_template(monkeypatch):
    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse(200, [])
        return _FakeResponse(404, text="missing")

    monkeypatch.setattr(infogram_client.requests, "get", fake_get)
    problem = check_credentials("K", "TPL")
    assert problem and "HTTP 404" in problem


def test_check_credentials_rejected_token(monkeypatch):
    monkeypatch.setattr(infogram_client.requests, "get",
                        lambda *a, **k: _FakeResponse(401, text="bad creds"))
    problem = check_credentials("K", "")
    assert problem and "HTTP 401" in problem
