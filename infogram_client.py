"""Infogram API client (current api.infogram.com REST API).

Implements the documented workflow of the current Infogram API:

  * base URL https://api.infogram.com
  * every request carries a single API token via `Authorization: Bearer`
  * infographics are created from a TEMPLATE project:
      1. copyProject      - duplicate the template (new draft project)
      2. getProjectData   - discover the template's text/chart entities
      3. updateProjectEntities - push the title text and the data table
      4. publishProject   - make it accessible and get the share URL

Credentials are ONE value (the API token) from Infogram account settings,
plus the project ID of the template infographic. Docs:
https://api.infogram.com/docs/
"""
import logging
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from output import temp_unit, precip_unit

logger = logging.getLogger(__name__)

API_BASE = "https://api.infogram.com"
REQUEST_TIMEOUT = 30
# Table charts render fine with hundreds of rows; cap to keep the payload sane.
MAX_TABLE_ROWS = 400


class InfogramError(Exception):
    """An Infogram API request failed; message is user-presentable."""


def _bearer(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _post(resource: str, payload: Dict[str, Any], token: str) -> Any:
    """JSON POST; returns the decoded body."""
    url = f"{API_BASE}/{resource}"
    logger.debug("Infogram POST %s", url)
    try:
        response = requests.post(
            url, json=payload, timeout=REQUEST_TIMEOUT,
            headers={**_bearer(token), "Content-Type": "application/json; charset=utf-8"})
    except requests.RequestException as exc:
        logger.error("Infogram request failed: %s", exc, exc_info=True)
        raise InfogramError(
            f"Could not reach Infogram ({exc.__class__.__name__}). "
            "Check your internet connection and try again."
        ) from exc
    return _decode(response)


def _get(resource: str, params: Dict[str, Any], token: str) -> Any:
    """GET with query parameters; returns the decoded body."""
    url = f"{API_BASE}/{resource}"
    logger.debug("Infogram GET %s", url)
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT,
                                headers=_bearer(token))
    except requests.RequestException as exc:
        logger.error("Infogram request failed: %s", exc, exc_info=True)
        raise InfogramError(
            f"Could not reach Infogram ({exc.__class__.__name__}). "
            "Check your internet connection and try again."
        ) from exc
    return _decode(response)


def _decode(response: requests.Response) -> Any:
    """Raise a user-presentable InfogramError for HTTP errors; else decode JSON."""
    if response.status_code >= 400:
        detail = (response.text or "").strip()
        logger.error("Infogram API error %s: %s", response.status_code, detail[:500])
        if response.status_code in (401, 403):
            raise InfogramError(
                f"Infogram rejected the API token (HTTP {response.status_code}). "
                "Check that the token is correct and still active "
                "(infogram.com, account settings, API). Server said: "
                f"{detail[:200] or '(no detail)'}"
            )
        if response.status_code == 404:
            raise InfogramError(
                "Infogram could not find that project (HTTP 404). "
                "Check the template project ID — it is the UUID in the "
                "project's URL or its context menu (Copy project ID)."
            )
        if response.status_code >= 500:
            raise InfogramError(
                f"Infogram had a server problem (HTTP {response.status_code}). "
                "Please try again later."
            )
        raise InfogramError(
            f"Infogram returned HTTP {response.status_code}: {detail[:200] or '(no detail)'}"
        )
    try:
        return response.json()
    except ValueError:
        raise InfogramError(
            "Infogram returned an unreadable response (expected JSON)."
        )


# ---------------------------------------------------------------------------
# Data shaping
# ---------------------------------------------------------------------------
def chart_data(df: pd.DataFrame, units: str) -> List[Dict[str, Any]]:
    """Build the chart update payload for a processed weather DataFrame.

    Follows the documented CHART entity format: a list of sheets, each with
    a title and a 2D array of strings (first row = column headers).
    """
    tu, pu = temp_unit(units), precip_unit(units)
    rows: List[List[str]] = [[
        "Date", f"Max Temp ({tu})", f"Min Temp ({tu})", f"Precip ({pu})"
    ]]
    for _, row in df.iterrows():
        rows.append([
            str(row["date_label"]),
            f"{row['temp_max']:.1f}",
            f"{row['temp_min']:.1f}",
            f"{row['precip_sum']:.1f}",
        ])
    if len(rows) - 1 > MAX_TABLE_ROWS:
        logger.warning("Trimming table from %d to %d rows", len(rows) - 1, MAX_TABLE_ROWS)
        rows = rows[:MAX_TABLE_ROWS + 1]
    return [{"title": "Weather data", "data": rows}]


def title_text(city: str, period: str) -> str:
    """Plain-text headline for the template's text entity."""
    return f"WeatherSnake: {city} ({period})"


# ---------------------------------------------------------------------------
# Project listing (for template picking)
# ---------------------------------------------------------------------------
def list_projects(token: str) -> List[Dict[str, str]]:
    """List the account's projects (private library) for template selection.

    Returns [{projectId, title, state, modifiedAt}, ...]; newest first is
    the API's ordering.
    """
    body = _get("getProjectList", {}, token)
    projects: List[Dict[str, str]] = []
    if isinstance(body, list):
        for item in body:
            if isinstance(item, dict) and item.get("projectId"):
                projects.append({
                    "projectId": str(item["projectId"]),
                    "title": str(item.get("title") or "(untitled)"),
                    "state": str(item.get("state") or "draft"),
                    "modifiedAt": str(item.get("modifiedAt") or ""),
                })
    logger.debug("Infogram project list: %d project(s)", len(projects))
    return projects


# ---------------------------------------------------------------------------
# Credential check
# ---------------------------------------------------------------------------
def check_credentials(token: str, template_id: str = "") -> Optional[str]:
    """Verify the token (and optionally the template) against the live API.

    Returns None when everything passes, or a short reason string otherwise.
    """
    try:
        _get("getProjectList", {}, token)
        if template_id:
            _get("getProjectData", {"projectId": template_id}, token)
    except InfogramError as exc:
        return str(exc)
    return None


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
def create_infographic(df: pd.DataFrame, city: str, period: str, units: str,
                       token: str, template_id: str,
                       public: bool = False) -> Dict[str, Any]:
    """Create an Infogram infographic from a template project.

    Copies the template, fills its text entity with the title and its chart
    entity with the weather table, then publishes it (private link by
    default). Returns {"projectId": ..., "url": ...}.
    """
    if not token:
        raise InfogramError(
            "An Infogram API token is required. Create one in your Infogram "
            "account settings (API section) and save it via the "
            "'Infogram Token' button."
        )
    if not template_id:
        raise InfogramError(
            "A template project ID is required. In Infogram, create a project "
            "containing a text block and a table chart, copy its project ID "
            "(context menu on the project card), and save it via the "
            "'Infogram Token' button."
        )

    # 1. Copy the template into a fresh draft project.
    copy = _post("copyProject",
                 {"projectId": template_id,
                  "title": f"WeatherSnake {city} {period}".strip()},
                 token)
    new_id = (copy or {}).get("projectId") if isinstance(copy, dict) else None
    if not new_id:
        logger.error("copyProject returned no projectId: %.300s", copy)
        raise InfogramError(
            "Infogram accepted the copy request but returned no project ID."
        )

    try:
        # 2. Discover the template's updatable entities.
        entities = _get("getProjectData", {"projectId": new_id}, token)
        text_id, chart_id = _find_entities(entities)

        # 3. Push the title and the data table.
        update: Dict[str, Any] = {
            chart_id: {"data": chart_data(df, units)},
        }
        if text_id:
            update[text_id] = title_text(city, period)
        _post("updateProjectEntities", {"projectId": new_id, "entities": update}, token)

        # 4. Publish (private = accessible with the link only) and get the URL.
        published = _post("publishProject",
                          {"projectId": new_id,
                           "privacy": "public" if public else "private"},
                          token)
    except InfogramError:
        logger.error("Infogram flow failed after copy; draft project %s remains "
                     "in your Infogram library", new_id)
        raise

    web_url = (published or {}).get("webUrl") if isinstance(published, dict) else None
    if not web_url:
        logger.error("publishProject returned no webUrl: %.300s", published)
        raise InfogramError(
            "Infogram published the project but did not return a share URL."
        )
    logger.info("Infogram infographic created: projectId=%s url=%s", new_id, web_url)
    return {"projectId": new_id, "url": web_url}


def _find_entities(entities: Any) -> tuple:
    """Return (first_text_id, first_chart_id) from a getProjectData response."""
    text_id = chart_id = None
    if isinstance(entities, list):
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            etype = entity.get("type")
            eid = entity.get("entityId")
            if etype == "TEXT" and text_id is None:
                text_id = eid
            elif etype == "CHART" and chart_id is None:
                chart_id = eid
    if chart_id is None:
        raise InfogramError(
            "The template has no chart block. Add a table chart to the "
            "template project in Infogram, then try again."
        )
    return text_id, chart_id
