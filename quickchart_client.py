"""QuickChart client: render the weather data as a PNG chart image.

QuickChart (https://quickchart.io) is an open-source web service that renders
Chart.js configurations to images. No account and no API key are needed for
the free tier (1,000 charts/month, 60 requests/minute); the service can also
be self-hosted for unlimited use.

WeatherSnake uses the POST form of the /chart endpoint so large labels and
many data points never overflow a URL:

    POST https://quickchart.io/chart
    {"chart": <Chart.js config>, "width": ..., "height": ...}

and the response body is the rendered PNG.
"""
import json
import logging
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from output import temp_unit, precip_unit

logger = logging.getLogger(__name__)

API_BASE = "https://quickchart.io"
REQUEST_TIMEOUT = 30
# Cap the number of labels sent to the renderer; beyond this the image is
# unreadably dense anyway.
MAX_LABELS = 200
# Number of x labels at which we stop drawing markers (Chart.js autoskip
# still leaves overlapping points on dense line charts).
LINE_HIDE_MARKERS_ABOVE = 60


class QuickChartError(Exception):
    """A QuickChart request failed; message is user-presentable."""


def chart_config(df: pd.DataFrame, city: str, period: str, units: str) -> Dict[str, Any]:
    """Build a Chart.js config rendering the processed weather DataFrame.

    Mirrors the in-app matplotlib figure: temperature max/min as line
    datasets on the left axis, precipitation as bars on the right axis.
    """
    tu, pu = temp_unit(units), precip_unit(units)
    labels: List[str] = [str(v) for v in df["date_label"].tolist()]
    if len(labels) > MAX_LABELS:
        logger.warning("Trimming chart from %d to %d labels", len(labels), MAX_LABELS)
        step = len(labels) / MAX_LABELS
        labels = [labels[int(i * step)] for i in range(MAX_LABELS)]
        df = df.iloc[[int(i * step) for i in range(MAX_LABELS)]]

    show_markers = len(labels) <= LINE_HIDE_MARKERS_ABOVE
    config: Dict[str, Any] = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "type": "line",
                    "label": f"Max Temp ({tu})",
                    "data": [round(float(v), 2) for v in df["temp_max"]],
                    "borderColor": "#d62728",
                    "backgroundColor": "#d62728",
                    "pointRadius": 2 if show_markers else 0,
                    "fill": False,
                    "yAxisID": "y",
                },
                {
                    "type": "line",
                    "label": f"Min Temp ({tu})",
                    "data": [round(float(v), 2) for v in df["temp_min"]],
                    "borderColor": "#ff7f0e",
                    "backgroundColor": "#ff7f0e",
                    "pointRadius": 2 if show_markers else 0,
                    "fill": False,
                    "yAxisID": "y",
                },
                {
                    "label": f"Precip ({pu})",
                    "data": [round(float(v), 2) for v in df["precip_sum"]],
                    "backgroundColor": "rgba(31, 119, 180, 0.4)",
                    "borderColor": "#1f77b4",
                    "yAxisID": "y1",
                },
            ],
        },
        "options": {
            "title": {
                "display": True,
                "text": f"Historical Weather for {city} ({period})",
            },
            "legend": {"position": "top"},
            "scales": {
                "yAxes": [
                    {
                        "id": "y",
                        "position": "left",
                        "scaleLabel": {"display": True, "labelString": f"Temperature ({tu})"},
                        "ticks": {"color": "#d62728"},
                    },
                    {
                        "id": "y1",
                        "position": "right",
                        "gridLines": {"drawOnChartArea": False},
                        "scaleLabel": {"display": True, "labelString": f"Precipitation ({pu})"},
                        "ticks": {"color": "#1f77b4"},
                    },
                ],
                "xAxes": [
                    {
                        "scaleLabel": {"display": True, "labelString": "Date" if " " in labels[0] else "Month"},
                        "ticks": {
                            "maxRotation": 90,
                            "minRotation": 45,
                            "autoSkip": True,
                            "maxTicksLimit": 40,
                        },
                    }
                ],
            },
        },
    }
    return config


def render_chart_png(config: Dict[str, Any], width: int = 1000, height: int = 600,
                     background: str = "white") -> bytes:
    """POST the config to QuickChart and return the rendered PNG bytes.

    Raises QuickChartError with a user-presentable message on any failure.
    """
    payload = {
        "chart": config,
        "width": width,
        "height": height,
        "devicePixelRatio": 2,
        "format": "png",
        "backgroundColor": background,
        "version": "2",
    }
    logger.debug("QuickChart POST %s/chart (%d labels)", API_BASE,
                 len(config.get("data", {}).get("labels", [])))
    try:
        response = requests.post(f"{API_BASE}/chart", json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.error("QuickChart request failed: %s", exc, exc_info=True)
        raise QuickChartError(
            f"Could not reach QuickChart ({exc.__class__.__name__}). "
            "Check your internet connection and try again."
        ) from exc
    if response.status_code >= 400:
        detail = (response.text or "").strip()
        logger.error("QuickChart error %s: %.300s", response.status_code, detail)
        if response.status_code == 429:
            raise QuickChartError(
                "QuickChart rate limit reached (60 charts per minute on the "
                "free tier). Wait a minute and try again."
            )
        if response.status_code >= 500:
            raise QuickChartError(
                f"QuickChart had a server problem (HTTP {response.status_code}). "
                "Please try again later."
            )
        raise QuickChartError(
            f"QuickChart rejected the chart (HTTP {response.status_code}): {detail[:200]}"
        )
    if not response.content.startswith(b"\x89PNG"):
        raise QuickChartError(
            "QuickChart returned an unexpected response (expected a PNG image)."
        )
    return response.content


def export_chart_png(df: pd.DataFrame, city: str, period: str, units: str,
                     filepath: Optional[str] = None) -> str:
    """Render the weather data via QuickChart and save it to a PNG file.

    Returns the written filepath.
    """
    config = chart_config(df, city, period, units)
    png = render_chart_png(config)
    if not filepath:
        import re

        from output import _safe_filename
        filepath = f"weather_quickchart_{_safe_filename(city)}_{_safe_filename(period)}.png"
    with open(filepath, "wb") as fh:
        fh.write(png)
    logger.info("QuickChart chart saved to %s", filepath)
    return filepath


def chart_url(df: pd.DataFrame, city: str, period: str, units: str) -> str:
    """Return a GET-able QuickChart URL for the weather data (sharable)."""
    config = chart_config(df, city, period, units)
    query = requests.models.RequestEncodingMixin._encode_params(
        {"c": json.dumps(config)})
    return f"{API_BASE}/chart?{query}"
