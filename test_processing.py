import pytest
import pandas as pd
from processing import get_season_months, is_date_in_season, process_weather_data


class TestGetSeasonMonths:
    def test_summer(self):
        assert get_season_months("summer") == (12, 2)

    def test_autumn(self):
        assert get_season_months("autumn") == (3, 5)

    def test_winter(self):
        assert get_season_months("winter") == (6, 8)

    def test_spring(self):
        assert get_season_months("spring") == (9, 11)

    def test_full_year(self):
        assert get_season_months("full year") == (1, 12)

    def test_case_insensitive(self):
        assert get_season_months("Summer") == (12, 2)
        assert get_season_months("WINTER") == (6, 8)

    def test_unknown_period(self):
        with pytest.raises(ValueError, match="Unknown period"):
            get_season_months("monsoon")


class TestIsDateInSeason:
    def test_summer_december(self):
        assert is_date_in_season(pd.Timestamp("2024-12-15"), 12, 2) is True

    def test_summer_january(self):
        assert is_date_in_season(pd.Timestamp("2024-01-15"), 12, 2) is True

    def test_summer_february(self):
        assert is_date_in_season(pd.Timestamp("2024-02-15"), 12, 2) is True

    def test_summer_excludes_march(self):
        assert is_date_in_season(pd.Timestamp("2024-03-15"), 12, 2) is False

    def test_winter_june(self):
        assert is_date_in_season(pd.Timestamp("2024-06-15"), 6, 8) is True

    def test_winter_excludes_may(self):
        assert is_date_in_season(pd.Timestamp("2024-05-15"), 6, 8) is False

    def test_full_year(self):
        for month in range(1, 13):
            assert is_date_in_season(pd.Timestamp(f"2024-{month:02d}-01"), 1, 12) is True


def _make_raw_data(dates, temp_max, temp_min, precip):
    """Helper to build raw API-like data dict."""
    return {
        "daily": {
            "time": dates,
            "temperature_2m_max": temp_max,
            "temperature_2m_min": temp_min,
            "precipitation_sum": precip,
        }
    }


class TestProcessWeatherData:
    def test_filters_to_season(self):
        # 4 days: 2 in winter (Jun-Aug), 2 outside
        raw = _make_raw_data(
            dates=["2024-06-15", "2024-07-15", "2024-03-15", "2024-10-15"],
            temp_max=[20.0, 22.0, 30.0, 28.0],
            temp_min=[10.0, 12.0, 18.0, 16.0],
            precip=[5.0, 3.0, 10.0, 8.0],
        )
        df = process_weather_data(raw, "Winter", "metric", monthly=True)
        assert len(df) == 2  # June and July only

    def test_imperial_conversion(self):
        raw = _make_raw_data(
            dates=["2024-07-01", "2024-07-02"],
            temp_max=[20.0, 30.0],
            temp_min=[10.0, 15.0],
            precip=[25.4, 0.0],
        )
        df = process_weather_data(raw, "Winter", "imperial", monthly=True)
        row = df.iloc[0]
        # 25°C -> 77°F, 12.5°C -> 54.5°F
        assert abs(row["temp_max"] - 77.0) < 0.1
        assert abs(row["temp_min"] - 54.5) < 0.1
        # 25.4mm / 25.4 = 1.0 inch (averaged: (25.4+0)/2 = 12.7mm -> 0.5 inch)
        assert abs(row["precip_sum"] - 0.5) < 0.1

    def test_metric_no_conversion(self):
        raw = _make_raw_data(
            dates=["2024-07-01"],
            temp_max=[20.0],
            temp_min=[10.0],
            precip=[5.0],
        )
        df = process_weather_data(raw, "Winter", "metric", monthly=True)
        row = df.iloc[0]
        assert row["temp_max"] == 20.0
        assert row["temp_min"] == 10.0
        assert row["precip_sum"] == 5.0

    def test_monthly_averaging(self):
        raw = _make_raw_data(
            dates=["2024-07-01", "2024-07-15", "2024-08-01"],
            temp_max=[20.0, 24.0, 18.0],
            temp_min=[10.0, 14.0, 8.0],
            precip=[4.0, 6.0, 2.0],
        )
        df = process_weather_data(raw, "Winter", "metric", monthly=True)
        jul = df[df["date_label"] == "July"].iloc[0]
        assert abs(jul["temp_max"] - 22.0) < 0.01  # avg(20, 24)
        assert abs(jul["temp_min"] - 12.0) < 0.01  # avg(10, 14)

    def test_daily_mode(self):
        raw = _make_raw_data(
            dates=["2024-07-01", "2024-07-02"],
            temp_max=[20.0, 22.0],
            temp_min=[10.0, 12.0],
            precip=[4.0, 6.0],
        )
        df = process_weather_data(raw, "Winter", "metric", monthly=False)
        assert len(df) == 2
        assert list(df["date_label"]) == ["07-01", "07-02"]

    def test_cross_year_season_sorting(self):
        # Summer (Dec-Feb) should sort Dec before Jan/Feb
        raw = _make_raw_data(
            dates=["2024-01-15", "2024-02-15", "2023-12-15"],
            temp_max=[30.0, 28.0, 32.0],
            temp_min=[20.0, 18.0, 22.0],
            precip=[3.0, 4.0, 2.0],
        )
        df = process_weather_data(raw, "Summer", "metric", monthly=True)
        labels = list(df["date_label"])
        assert labels == ["December", "January", "February"]

    def test_empty_data_raises(self):
        with pytest.raises(ValueError, match="No daily data"):
            process_weather_data({}, "Winter", "metric", monthly=True)
