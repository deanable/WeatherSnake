import pandas as pd
import pytest

from conditions import (
	compute_condition_distribution,
	describe_weather_code,
	weather_code_category,
	RAIN_DAY_MM,
)
from stats import (
	compare_depths,
	compute_variability_stats,
	compute_year_over_year,
)


def _make_raw_data(dates, temp_max, temp_min, precip, codes):
	"""Helper to build raw API-like data with weather codes."""
	return {
		"daily": {
			"time": dates,
			"temperature_2m_max": temp_max,
			"temperature_2m_min": temp_min,
			"precipitation_sum": precip,
			"weather_code": codes,
		}
	}


class TestDescribeWeatherCode:
	def test_clear(self):
		assert describe_weather_code(0) == "Clear sky"

	def test_rain(self):
		assert describe_weather_code(61) == "Slight rain"

	def test_thunderstorm(self):
		assert describe_weather_code(95) == "Thunderstorm"

	def test_unknown_code_returns_label(self):
		assert describe_weather_code(42) == "Code 42"

	def test_none_returns_unknown(self):
		assert describe_weather_code(None) == "Unknown"

	def test_nan_returns_unknown(self):
		assert describe_weather_code(float("nan")) == "Unknown"


class TestWeatherCodeCategory:
	def test_fog_codes_grouped(self):
		assert weather_code_category(45) == "Fog"
		assert weather_code_category(48) == "Fog"

	def test_rain_codes_grouped(self):
		assert weather_code_category(61) == "Rain"
		assert weather_code_category(63) == "Rain"
		assert weather_code_category(65) == "Rain"

	def test_showers_separate_from_rain(self):
		assert weather_code_category(80) == "Rain showers"

	def test_unknown_code_passthrough(self):
		assert weather_code_category(7) == "Code 7"


class TestConditionDistribution:
	def test_basic_distribution(self):
		raw = _make_raw_data(
			dates=["2024-06-01", "2024-06-02", "2024-06-03", "2024-06-04"],
			temp_max=[20.0] * 4,
			temp_min=[10.0] * 4,
			precip=[5.0, 0.0, 0.2, 0.0],
			codes=[61, 0, 2, 0],
		)
		result = compute_condition_distribution(raw, "Winter")
		assert result is not None
		assert result["total_days"] == 4
		assert result["dominant"] == "Clear sky"
		# 2 of 4 days clear, 1 rain, 1 partly cloudy
		top = result["conditions"].iloc[0]
		assert top["condition"] == "Clear sky"
		assert abs(top["share"] - 0.5) < 1e-9
		# Rain days: precip >= 1mm -> only June 1
		assert abs(result["rainy_day_share"] - 0.25) < 1e-9

	def test_filters_to_season(self):
		raw = _make_raw_data(
			dates=["2024-06-15", "2024-01-15"],
			temp_max=[20.0, 30.0],
			temp_min=[10.0, 20.0],
			precip=[0.0, 0.0],
			codes=[0, 3],
		)
		result = compute_condition_distribution(raw, "Winter")
		assert result["total_days"] == 1
		assert result["dominant"] == "Clear sky"

	def test_custom_range(self):
		raw = _make_raw_data(
			dates=["2024-03-05", "2024-04-15"],
			temp_max=[20.0, 25.0],
			temp_min=[10.0, 15.0],
			precip=[0.0, 0.0],
			codes=[2, 0],
		)
		result = compute_condition_distribution(raw, "Custom", custom_start=(3, 1), custom_end=(3, 31))
		assert result["total_days"] == 1
		assert result["dominant"] == "Partly cloudy"

	def test_no_weather_code_returns_none(self):
		raw = {"daily": {"time": ["2024-06-01"], "temperature_2m_max": [20.0],
		                 "temperature_2m_min": [10.0], "precipitation_sum": [0.0]}}
		assert compute_condition_distribution(raw, "Winter") is None

	def test_empty_window_returns_none(self):
		raw = _make_raw_data(
			dates=["2024-01-15"],
			temp_max=[20.0], temp_min=[10.0], precip=[0.0], codes=[0],
		)
		assert compute_condition_distribution(raw, "Winter") is None

	def test_leap_day_excluded(self):
		raw = _make_raw_data(
			dates=["2024-02-28", "2024-02-29", "2024-03-01"],
			temp_max=[10.0] * 3, temp_min=[5.0] * 3, precip=[0.0] * 3,
			codes=[0] * 3,
		)
		# Use custom range spanning Feb 28 - Mar 1 to exercise the leap filter
		result = compute_condition_distribution(raw, "Custom", custom_start=(2, 28), custom_end=(3, 1))
		assert result["total_days"] == 2


class TestVariabilityStats:
	def test_basic_stats(self):
		raw = _make_raw_data(
			dates=["2023-07-01", "2023-07-02", "2024-07-01", "2024-07-02"],
			temp_max=[20.0, 30.0, 25.0, 35.0],
			temp_min=[10.0, 15.0, 12.0, 18.0],
			precip=[10.0, 0.0, 0.0, 5.0],
			codes=[61, 0, 0, 61],
		)
		stats = compute_variability_stats(raw, "Winter")
		assert stats["years_analyzed"] == 2
		assert abs(stats["temp_max"]["mean"] - 27.5) < 1e-9
		assert stats["temp_max"]["min"] == 20.0
		assert stats["temp_max"]["max"] == 35.0
		# Season totals: 2023 = 10, 2024 = 5 -> mean 7.5
		assert abs(stats["precip"]["mean_year_total"] - 7.5) < 1e-9
		assert stats["precip"]["wettest_year"] == (2023, 10.0)
		assert stats["precip"]["driest_year"] == (2024, 5.0)
		assert stats["precip"]["years_above_mean"] == 1
		# Rain days: 1 per year
		assert stats["rain_days"]["mean_per_year"] == 1.0

	def test_precip_threshold_applied(self):
		raw = _make_raw_data(
			dates=["2024-07-01"],
			temp_max=[20.0], temp_min=[10.0], precip=[0.4], codes=[0],
		)
		stats = compute_variability_stats(raw, "Winter", precip_threshold=1.0)
		assert stats["precip"]["mean_year_total"] == 0.0

	def test_empty_raises(self):
		with pytest.raises(ValueError):
			compute_variability_stats({"daily": {}}, "Winter")

	def test_cross_year_season_counts_complete_years_only(self):
		# Summer (Dec-Feb): Dec 2023 + Jan/Feb 2024 = complete year 2023.
		# Dec 2024 alone is incomplete and must be excluded.
		raw = _make_raw_data(
			dates=["2023-12-15", "2024-01-15", "2024-02-15", "2024-12-15"],
			temp_max=[30.0, 32.0, 31.0, 29.0],
			temp_min=[20.0, 22.0, 21.0, 19.0],
			precip=[2.0, 0.0, 1.0, 3.0],
			codes=[0, 1, 2, 3],
		)
		stats = compute_variability_stats(raw, "Summer")
		assert stats["years_analyzed"] == 1


class TestYearOverYear:
	def test_table_and_trend(self):
		# Two years; highs 20 and 30 -> +10/yr = +100/decade
		raw = _make_raw_data(
			dates=["2023-07-01", "2024-07-01"],
			temp_max=[20.0, 30.0],
			temp_min=[10.0, 12.0],
			precip=[5.0, 5.0],
			codes=[0, 0],
		)
		yoy = compute_year_over_year(raw, "Winter")
		assert list(yoy["table"]["year"]) == [2023, 2024]
		assert abs(yoy["temp_max_trend"] - 100.0) < 1e-6
		assert abs(yoy["temp_min_trend"] - 20.0) < 1e-6
		assert abs(yoy["precip_trend"]) < 1e-6

	def test_single_year_no_trend(self):
		raw = _make_raw_data(
			dates=["2024-07-01"],
			temp_max=[20.0], temp_min=[10.0], precip=[5.0], codes=[0],
		)
		yoy = compute_year_over_year(raw, "Winter")
		assert yoy["temp_max_trend"] is None
		assert yoy["temp_min_trend"] is None
		assert yoy["precip_trend"] is None


class TestCompareDepths:
	def _multi_year_data(self):
		# 3 winters: 2022, 2023, 2024 with highs 10, 20, 30
		return _make_raw_data(
			dates=["2022-07-01", "2023-07-01", "2024-07-01"],
			temp_max=[10.0, 20.0, 30.0],
			temp_min=[5.0, 10.0, 15.0],
			precip=[10.0, 20.0, 30.0],
			codes=[61, 61, 61],
		)

	def test_recent_vs_baseline(self):
		comparison = compare_depths(self._multi_year_data(), "Winter",
		                            recent_depth=1, baseline_depth=2)
		assert comparison["recent_years"] == [2024]
		assert comparison["baseline_years"] == [2022, 2023]
		# Recent high 30 vs baseline avg 15 -> +15
		assert abs(comparison["delta"]["temp_max"] - 15.0) < 1e-9
		# Precip totals 30 vs avg 15 -> +15
		assert abs(comparison["delta"]["precip_total"] - 15.0) < 1e-9

	def test_insufficient_years_raises(self):
		with pytest.raises(ValueError, match="Not enough years"):
			compare_depths(self._multi_year_data(), "Winter",
			               recent_depth=2, baseline_depth=2)

	def test_invalid_depths_raise(self):
		with pytest.raises(ValueError, match="at least 1"):
			compare_depths(self._multi_year_data(), "Winter",
			               recent_depth=0, baseline_depth=2)
