"""Datawrapper API client: publish the weather data as an interactive chart.

Implements the Datawrapper API v3 workflow (https://api.datawrapper.de):

  1. POST  /v3/charts              create a chart (title, type)
  2. PUT   /v3/charts/{id}/data    upload the data as CSV
  3. PATCH /v3/charts/{id}         set metadata (axes, source, intro)
  4. POST  /v3/charts/{id}/publish publish; returns the public URL

Credentials are ONE value: a personal access token from
app.datawrapper.de/account/api-tokens (free account, free tier:
500 creates / 1,000 publishes / 3,000 exports per month).
"""
import logging
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from output import temp_unit, precip_unit

logger = logging.getLogger(__name__)

API_BASE = "https://api.datawrapper.de"
REQUEST_TIMEOUT = 30
# CSV upload cap; Datawrapper renders large tables fine but keep payloads sane.
MAX_ROWS = 2000
CHART_TYPE = "d3-lines"
ENV_TOKEN = "DATAWRAPPER_ACCESS_TOKEN"


class DatawrapperError(Exception):
    """A Datawrapper API request failed; message is user-presentable."""


def _bearer(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _request(method: str, resource: str, token: str, *, json_body: Any = None,
             data: Any = None, headers: Optional[Dict[str, str]] = None) -> requests.Response:
    """Send one API request; map failures to user-presentable errors."""
    url = f"{API_BASE}/{resource}"
    logger.debug("Datawrapper %s %s", method, url)
    all_headers = {**_bearer(token), **(headers or {})}
    try:
        response = requests.request(method, url, json=json_body, data=data,
                                    headers=all_headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.error("Datawrapper request failed: %s", exc, exc_info=True)
        raise DatawrapperError(
            f"Could not reach Datawrapper ({exc.__class__.__name__}). "
            "Check your internet connection and try again."
        ) from exc
    if response.status_code >= 400:
        detail = (response.text or "").strip()
        logger.error("Datawrapper API error %s: %.500s", response.status_code, detail)
        if response.status_code in (401, 403):
            raise DatawrapperError(
                f"Datawrapper rejected the API token (HTTP {response.status_code}). "
                "Check that the token is correct and still active "
                "(app.datawrapper.de, Settings & Account, API tokens). "
                f"Server said: {detail[:200] or '(no detail)'}"
            )
        if response.status_code == 429:
            raise DatawrapperError(
                "Datawrapper monthly API quota reached (free tier: 500 creates "
                "and 1,000 publishes per month). Try again next month or "
                "upgrade your Datawrapper plan."
            )
        if response.status_code >= 500:
            raise DatawrapperError(
                f"Datawrapper had a server problem (HTTP {response.status_code}). "
                "Please try again later."
            )
        raise DatawrapperError(
            f"Datawrapper returned HTTP {response.status_code}: {detail[:200] or '(no detail)'}"
        )
    return response


def _decode_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raise DatawrapperError(
            "Datawrapper returned an unreadable response (expected JSON)."
        )


# ---------------------------------------------------------------------------
# Data shaping
# ---------------------------------------------------------------------------
def chart_csv(df: pd.DataFrame) -> str:
    """Render the processed weather DataFrame as CSV for the data upload.

    The first column becomes the x axis; Datawrapper treats every following
    column as a dataset the user can switch on in the visualization.
    """
    data = df
    if len(data) > MAX_ROWS:
        logger.warning("Trimming chart data from %d to %d rows", len(data), MAX_ROWS)
        data = data.iloc[:MAX_ROWS]
    columns = ["date_label", "temp_max", "temp_min", "precip_sum"]
    return data[columns].to_csv(index=False, lineterminator="\n")


def csv_headers(units: str) -> List[str]:
    """CSV column headers for the given unit system."""
    tu, pu = temp_unit(units), precip_unit(units)
    return [f"Max Temp ({tu})", f"Min Temp ({tu})", f"Precip ({pu})"]


def title_text(city: str, period: str) -> str:
    """Chart title."""
    return f"Historical Weather for {city} ({period})"


# ---------------------------------------------------------------------------
# Credential check
# ---------------------------------------------------------------------------
def check_credentials(token: str) -> Optional[str]:
    """Verify the token against the live API (GET /v3/me).

    Returns None when the token passes, or a short reason string otherwise.
    """
    try:
        _request("GET", "v3/me", token)
    except DatawrapperError as exc:
        return str(exc)
    return None


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
def create_chart(df: pd.DataFrame, city: str, period: str, units: str,
                 token: str) -> Dict[str, Any]:
    """Create, fill, and publish a Datawrapper chart from the weather data.

    Returns {"chartId": ..., "url": ...} where url is the public chart page.
    """
    if not token:
        raise DatawrapperError(
            "A Datawrapper API token is required. Create a free account at "
            "app.datawrapper.de, generate a token under Settings & Account > "
            "API tokens, and save it via the 'Datawrapper Token' button."
        )

    # 1. Create the chart shell.
    created = _decode_json(_request(
        "POST", "v3/charts", token,
        json_body={"title": title_text(city, period), "type": CHART_TYPE}))
    chart_id = (created or {}).get("id") if isinstance(created, dict) else None
    if not chart_id:
        logger.error("create chart returned no id: %.300s", created)
        raise DatawrapperError(
            "Datawrapper accepted the create request but returned no chart ID."
        )
    logger.info("Datawrapper chart created: id=%s", chart_id)

    try:
        # 2. Upload the data as CSV.
        _request("PUT", f"v3/charts/{chart_id}/data", token,
                 data=chart_csv(df).encode("utf-8"),
                 headers={"Content-Type": "text/csv"})

        # 3. Metadata: pick the axes, label the series, add the source line.
        tu, pu = temp_unit(units), precip_unit(units)
        metadata: Dict[str, Any] = {
            "metadata": {
                "axes": {
                    "x": "date_label",
                    "y": ["temp_max", "temp_min", "precip_sum"],
                },
                "visualize": {
                    "y-grid": "on",
                    "x-axis-label": "Date",
                    "y-axis-label": f"{tu} / {pu}",
                },
                "describe": {
                    "source-name": "Open-Meteo (ERA5 reanalysis)",
                    "source-url": "https://open-meteo.com/",
                    "intro": f"Averages over the selected years — {period} window.",
                },
                "custom": {
                    "series": [
                        {"key": "temp_max", "label": f"Max Temp ({tu})"},
                        {"key": "temp_min", "label": f"Min Temp ({tu})"},
                        {"key": "precip_sum", "label": f"Precip ({pu})"},
                    ],
                },
            }
        }
        _request("PATCH", f"v3/charts/{chart_id}", token, json_body=metadata)

        # 4. Publish and read back the public URL.
        published = _decode_json(_request("POST", f"v3/charts/{chart_id}/publish", token))
    except DatawrapperError:
        logger.error("Datawrapper flow failed after create; unfinished chart %s "
                     "remains in your Datawrapper account", chart_id)
        raise

    url = _public_url(published, chart_id)
    if not url:
        logger.error("publish returned no public url: %.300s", published)
        raise DatawrapperError(
            "Datawrapper published the chart but did not return a public URL."
        )
    logger.info("Datawrapper chart published: id=%s url=%s", chart_id, url)
    return {"chartId": chart_id, "url": url}


def _public_url(published: Any, chart_id: str) -> Optional[str]:
    """Extract the public URL from a publish (or chart fetch) response."""
    if isinstance(published, dict):
        data = published.get("data", published)
        if isinstance(data, dict):
            # The canonical public URL pattern for published charts.
            url = data.get("publicUrl") or data.get("url")
            if url:
                return str(url)
    # Chart page URLs follow https://datawrapper.dwcdn.net/<id>/
    if chart_id:
        return f"https://datawrapper.dwcdn.net/{chart_id}/"
    return None
