"""Tests for the QuickChart client (keyless chart-image rendering)."""
import os
import sys

import pandas as pd
import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import quickchart_client  # noqa: E402
from quickchart_client import (  # noqa: E402
    QuickChartError, chart_config, render_chart_png, export_chart_png, chart_url,
)


def _df():
    return pd.DataFrame({
        "date_label": ["December", "January", "February"],
        "temp_max": [26.0, 27.1, 28.2],
        "temp_min": [18.0, 19.0, 20.0],
        "precip_sum": [72.0, 65.5, 58.0],
    })


# ---------------------------------------------------------------------------
# Config building
# ---------------------------------------------------------------------------
def test_config_datasets_and_labels():
    config = chart_config(_df(), "Durban", "Summer", "metric")
    data = config["data"]
    assert data["labels"] == ["December", "January", "February"]
    kinds = [(d["label"], d["type"] if "type" in d else "bar") for d in data["datasets"]]
    assert kinds[0][0] == "Max Temp (°C)" and kinds[0][1] == "line"
    assert kinds[1][0] == "Min Temp (°C)" and kinds[1][1] == "line"
    assert kinds[2][0] == "Precip (mm)"
    assert data["datasets"][0]["data"] == [26.0, 27.1, 28.2]
    assert data["datasets"][2]["data"] == [72.0, 65.5, 58.0]


def test_config_imperial_units():
    config = chart_config(_df(), "X", "Y", "imperial")
    labels = [d["label"] for d in config["data"]["datasets"]]
    assert any("°F" in l for l in labels)
    assert any("inch" in l for l in labels)


def test_config_has_dual_axes_and_title():
    config = chart_config(_df(), "Durban", "Summer", "metric")
    scales = config["options"]["scales"]
    ids = [ax["id"] for ax in scales["yAxes"]]
    assert ids == ["y", "y1"]
    title = config["options"]["title"]
    assert title["display"] and "Durban" in title["text"]


def test_config_caps_labels():
    big = pd.DataFrame({
        "date_label": [f"Day {i}" for i in range(600)],
        "temp_max": [20.0] * 600, "temp_min": [10.0] * 600,
        "precip_sum": [0.0] * 600,
    })
    config = chart_config(big, "X", "Y", "metric")
    assert len(config["data"]["labels"]) == quickchart_client.MAX_LABELS


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"rest-of-image"


class _FakeResponse:
    def __init__(self, status_code=200, content=b"", text=""):
        self.status_code = status_code
        self.content = content
        self.text = text


def test_render_png_posts_config(monkeypatch):
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"], seen["json"] = url, json
        return _FakeResponse(200, content=PNG_BYTES)

    monkeypatch.setattr(quickchart_client.requests, "post", fake_post)
    png = render_chart_png(chart_config(_df(), "D", "S", "metric"))
    assert png == PNG_BYTES
    assert seen["url"] == f"{quickchart_client.API_BASE}/chart"
    payload = seen["json"]
    assert payload["format"] == "png" and payload["width"] >= 500
    assert payload["chart"]["data"]["labels"] == ["December", "January", "February"]


def test_render_png_rejects_non_png(monkeypatch):
    monkeypatch.setattr(quickchart_client.requests, "post",
                        lambda *a, **k: _FakeResponse(200, content=b"<html>oops</html>", text="<html>"))
    with pytest.raises(QuickChartError, match="expected a PNG"):
        render_chart_png(chart_config(_df(), "X", "Y", "metric"))


def test_render_rate_limit_message(monkeypatch):
    monkeypatch.setattr(quickchart_client.requests, "post",
                        lambda *a, **k: _FakeResponse(429, text="slow down"))
    with pytest.raises(QuickChartError, match="rate limit"):
        render_chart_png(chart_config(_df(), "X", "Y", "metric"))


def test_render_5xx_message(monkeypatch):
    monkeypatch.setattr(quickchart_client.requests, "post",
                        lambda *a, **k: _FakeResponse(503, text="down"))
    with pytest.raises(QuickChartError, match="try again later"):
        render_chart_png(chart_config(_df(), "X", "Y", "metric"))


def test_render_network_error_message(monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("no route")
    monkeypatch.setattr(quickchart_client.requests, "post", boom)
    with pytest.raises(QuickChartError, match="Could not reach QuickChart"):
        render_chart_png(chart_config(_df(), "X", "Y", "metric"))


def test_export_chart_png_writes_file(monkeypatch, tmp_path):
    monkeypatch.setattr(quickchart_client.requests, "post",
                        lambda *a, **k: _FakeResponse(200, content=PNG_BYTES))
    target = tmp_path / "chart.png"
    written = export_chart_png(_df(), "Cape Town", "September", "metric", str(target))
    assert written == str(target)
    assert target.read_bytes() == PNG_BYTES


def test_export_chart_png_default_filename(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(quickchart_client.requests, "post",
                        lambda *a, **k: _FakeResponse(200, content=PNG_BYTES))
    written = export_chart_png(_df(), "Cape Town", "September", "metric")
    assert written.startswith("weather_quickchart_Cape_Town_September")
    assert os.path.exists(written)
    os.remove(written)


def test_chart_url_is_get_able(monkeypatch):
    url = chart_url(_df(), "Durban", "Summer", "metric")
    assert url.startswith(f"{quickchart_client.API_BASE}/chart?c=")
    assert "Historical" in url or "Historical".replace("H", "%48") in url
