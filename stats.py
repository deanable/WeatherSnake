"""Variability, extremes, year-over-year trends, and depth-window comparisons.

All values are computed in metric units (°C, mm); formatters in output.py
convert for display when imperial units are requested.
"""
import logging
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd

from conditions import RAIN_DAY_MM
from processing import get_season_months, is_date_in_season, is_date_in_custom_range

logger = logging.getLogger(__name__)


def _window_occurrence_year(dates: pd.Series, start_month: int) -> pd.Series:
	"""Year label for each date so cross-year windows group correctly.

	A Dec 2023 - Feb 2024 occurrence is labelled 2023 (the year it starts).
	"""
	return dates.dt.year - (dates.dt.month < start_month).astype(int)


def _window_rows(raw_data: Dict[str, Any], period: str,
                 custom_start: tuple = None, custom_end: tuple = None) -> pd.DataFrame:
	"""Daily rows inside the requested window, tagged with an occurrence year."""
	daily = raw_data.get("daily", {})
	if not daily:
		logger.error("No daily data found in API response")
		raise ValueError("No daily data found in API response.")

	df = pd.DataFrame({
		"date": pd.to_datetime(daily["time"]),
		"temp_max": daily["temperature_2m_max"],
		"temp_min": daily["temperature_2m_min"],
		"precip_sum": daily["precipitation_sum"],
	})

	# Exclude leap day for consistency with the rest of the pipeline
	leap = (df["date"].dt.month == 2) & (df["date"].dt.day == 29)
	df = df[~leap]

	if custom_start is not None and custom_end is not None:
		sm, sd = custom_start
		em, ed = custom_end
		mask = df["date"].apply(lambda d: is_date_in_custom_range(d, sm, sd, em, ed))
		start_month = sm
	else:
		start_month, end_month = get_season_months(period)
		mask = df["date"].apply(lambda d: is_date_in_season(d, start_month, end_month))

	df = df[mask].copy()
	df["year"] = _window_occurrence_year(df["date"], start_month)
	return df


def _complete_years(df: pd.DataFrame, start_month: int, end_month: int) -> List[int]:
	"""Occurrence years whose window is fully covered by the fetched data.

	For cross-year windows (start month after end month) the final occurrence
	is usually missing its tail months (e.g. Dec 2024 fetched but Jan/Feb 2025
	not yet in the archive), so it is excluded from per-year analysis.
	"""
	years = sorted(df["year"].unique())
	if start_month <= end_month:
		return years
	complete = []
	for y in years:
		# Cross-year windows label every day of an occurrence (e.g. Dec 2023
		# through Feb 2024) with the year the window starts, so head and tail
		# months are both checked within the same year label.
		years_days = df[df["year"] == y]
		has_head = (years_days["date"].dt.month == start_month).any()
		has_tail = (years_days["date"].dt.month == end_month).any()
		if has_head and has_tail:
			complete.append(y)
	return complete


def _trim_years(years: List[int], max_years: Optional[int]) -> List[int]:
	"""Keep only the most recent `max_years` complete years."""
	if max_years is not None and max_years > 0:
		return years[-max_years:]
	return years


def compute_variability_stats(raw_data: Dict[str, Any], period: str,
                              custom_start: tuple = None, custom_end: tuple = None,
                              precip_threshold: float = 0.0,
                              max_years: Optional[int] = None) -> Dict[str, Any]:
	"""Variability and extremes for the window across all fetched years.

	Returns metric-unit stats: per-series mean/std/percentiles/extremes for
	temps, per-year precipitation totals (wettest/driest year, years above
	mean), and rain-day counts.
	"""
	df = _window_rows(raw_data, period, custom_start, custom_end)
	if precip_threshold > 0:
		df.loc[df["precip_sum"] < precip_threshold, "precip_sum"] = 0.0

	sm, em = (custom_start[0], custom_end[0]) if custom_start is not None and custom_end is not None \
		else get_season_months(period)
	years = _trim_years(_complete_years(df, sm, em), max_years)
	df = df[df["year"].isin(years)]
	if df.empty:
		raise ValueError("No complete years of data available for the requested window.")

	def _series_stats(s: pd.Series) -> Dict[str, float]:
		return {
			"mean": float(s.mean()),
			"std": float(s.std()) if len(s) > 1 else 0.0,
			"p05": float(s.quantile(0.05)),
			"p95": float(s.quantile(0.95)),
			"min": float(s.min()),
			"max": float(s.max()),
		}

	year_totals = df.groupby("year")["precip_sum"].sum()
	mean_total = float(year_totals.mean())
	wettest = (int(year_totals.idxmax()), float(year_totals.max()))
	driest = (int(year_totals.idxmin()), float(year_totals.min()))
	years_above = int((year_totals > mean_total).sum())

	wet = df["precip_sum"] >= RAIN_DAY_MM
	rain_days_per_year = df.assign(wet=wet).groupby("year")["wet"].sum()

	stats = {
		"years_analyzed": len(years),
		"temp_max": _series_stats(df["temp_max"]),
		"temp_min": _series_stats(df["temp_min"]),
		"precip": {
			"mean_daily": float(df["precip_sum"].mean()),
			"mean_year_total": mean_total,
			"wettest_year": wettest,
			"driest_year": driest,
			"years_above_mean": years_above,
		},
		"rain_days": {
			"mean_per_year": float(rain_days_per_year.mean()) if len(rain_days_per_year) else 0.0,
			"max_per_year": int(rain_days_per_year.max()) if len(rain_days_per_year) else 0,
		},
	}
	logger.debug("Variability stats: %d years analyzed", len(years))
	return stats


def compute_year_over_year(raw_data: Dict[str, Any], period: str,
                           custom_start: tuple = None, custom_end: tuple = None,
                           precip_threshold: float = 0.0,
                           max_years: Optional[int] = None) -> Dict[str, Any]:
	"""Per-year window means/totals plus a least-squares trend per decade."""
	df = _window_rows(raw_data, period, custom_start, custom_end)
	if precip_threshold > 0:
		df.loc[df["precip_sum"] < precip_threshold, "precip_sum"] = 0.0

	sm, em = (custom_start[0], custom_end[0]) if custom_start is not None and custom_end is not None \
		else get_season_months(period)
	years = _trim_years(_complete_years(df, sm, em), max_years)
	df = df[df["year"].isin(years)]
	if df.empty:
		raise ValueError("No complete years of data available for the requested window.")

	table = df.groupby("year").agg(
		temp_max=("temp_max", "mean"),
		temp_min=("temp_min", "mean"),
		precip_total=("precip_sum", "sum"),
		days=("date", "count"),
	).reset_index().sort_values("year")

	def _trend_per_decade(values: pd.Series) -> Optional[float]:
		if len(table) < 2:
			return None
		x = ((table["year"] - table["year"].min()) / 10.0).to_numpy(dtype=float)
		return float(np.polyfit(x, values.to_numpy(dtype=float), 1)[0])

	return {
		"table": table,
		"temp_max_trend": _trend_per_decade(table["temp_max"]),
		"temp_min_trend": _trend_per_decade(table["temp_min"]),
		"precip_trend": _trend_per_decade(table["precip_total"]),
	}


def compare_depths(raw_data: Dict[str, Any], period: str,
                   recent_depth: int, baseline_depth: int,
                   custom_start: tuple = None, custom_end: tuple = None,
                   precip_threshold: float = 0.0) -> Dict[str, Any]:
	"""Compare the most recent `recent_depth` complete years against the
	`baseline_depth` years immediately before them.

	Requires at least recent_depth + baseline_depth complete years of data.
	"""
	if recent_depth < 1 or baseline_depth < 1:
		raise ValueError("Comparison depths must both be at least 1.")

	df = _window_rows(raw_data, period, custom_start, custom_end)
	if precip_threshold > 0:
		df.loc[df["precip_sum"] < precip_threshold, "precip_sum"] = 0.0

	sm, em = (custom_start[0], custom_end[0]) if custom_start is not None and custom_end is not None \
		else get_season_months(period)
	years_desc = sorted(_complete_years(df, sm, em), reverse=True)
	if len(years_desc) < recent_depth + baseline_depth:
		raise ValueError(
			f"Not enough years for comparison: need {recent_depth + baseline_depth} complete years, "
			f"have {len(years_desc)}. Increase --depth."
		)

	recent_years = sorted(years_desc[:recent_depth])
	baseline_years = sorted(years_desc[recent_depth:recent_depth + baseline_depth])

	def _group_summary(year_labels: List[int]) -> Dict[str, float]:
		g = df[df["year"].isin(year_labels)]
		totals = g.groupby("year")["precip_sum"].sum()
		return {
			"temp_max": float(g["temp_max"].mean()),
			"temp_min": float(g["temp_min"].mean()),
			"precip_total": float(totals.mean()),
		}

	recent = _group_summary(recent_years)
	baseline = _group_summary(baseline_years)
	delta = {k: recent[k] - baseline[k] for k in recent}

	logger.debug("Depth comparison: recent=%s baseline=%s", recent_years, baseline_years)
	return {
		"recent_years": recent_years,
		"baseline_years": baseline_years,
		"recent": recent,
		"baseline": baseline,
		"delta": delta,
	}
