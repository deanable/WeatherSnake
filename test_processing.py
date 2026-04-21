import pytest
import pandas as pd
from processing import get_season_months, is_date_in_season, is_date_in_custom_range, process_weather_data


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

    def test_leap_day_excluded(self):
        """Feb 29 data should be excluded from all processing."""
        raw = _make_raw_data(
            dates=["2024-02-28", "2024-02-29", "2024-03-01"],
            temp_max=[10.0, 99.0, 12.0],
            temp_min=[5.0, 99.0, 6.0],
            precip=[1.0, 99.0, 2.0],
        )
        df = process_weather_data(raw, "Full Year", "metric", monthly=False)
        labels = list(df["date_label"])
        assert "02-29" not in labels
        assert "02-28" in labels
        assert "03-01" in labels

    def test_precip_threshold_zeros_low_values(self):
        """Precipitation below the threshold should be zeroed out."""
        raw = _make_raw_data(
            dates=["2024-07-01", "2024-07-02", "2024-07-03"],
            temp_max=[20.0, 22.0, 24.0],
            temp_min=[10.0, 12.0, 14.0],
            precip=[2.0, 5.0, 10.0],
        )
        df = process_weather_data(raw, "Winter", "metric", monthly=False, precip_threshold=5.0)
        # 2.0 < 5.0 -> zeroed, 5.0 >= 5.0 -> kept, 10.0 >= 5.0 -> kept
        assert df.iloc[0]["precip_sum"] == 0.0
        assert df.iloc[1]["precip_sum"] == 5.0
        assert df.iloc[2]["precip_sum"] == 10.0

    def test_precip_threshold_applied_after_averaging(self):
        """Averaged precip that falls below threshold should also be zeroed."""
        raw = _make_raw_data(
            dates=["2023-07-01", "2024-07-01"],
            temp_max=[20.0, 22.0],
            temp_min=[10.0, 12.0],
            precip=[6.0, 0.0],  # raw: 6 kept, 0 zeroed -> avg = 3.0 which is < 5
        )
        df = process_weather_data(raw, "Winter", "metric", monthly=False, precip_threshold=5.0)
        assert df.iloc[0]["precip_sum"] == 0.0

    def test_precip_threshold_zero_disables(self):
        """Threshold of 0 should not alter any values."""
        raw = _make_raw_data(
            dates=["2024-07-01"],
            temp_max=[20.0],
            temp_min=[10.0],
            precip=[0.5],
        )
        df = process_weather_data(raw, "Winter", "metric", monthly=False, precip_threshold=0.0)
        assert df.iloc[0]["precip_sum"] == 0.5


class TestIsDateInCustomRange:
    def test_simple_range(self):
        assert is_date_in_custom_range(pd.Timestamp("2024-03-15"), 3, 1, 3, 21) is True

    def test_outside_simple_range(self):
        assert is_date_in_custom_range(pd.Timestamp("2024-03-25"), 3, 1, 3, 21) is False

    def test_cross_year_december(self):
        assert is_date_in_custom_range(pd.Timestamp("2024-12-15"), 12, 1, 2, 28) is True

    def test_cross_year_january(self):
        assert is_date_in_custom_range(pd.Timestamp("2024-01-10"), 12, 1, 2, 28) is True

    def test_cross_year_excludes_march(self):
        assert is_date_in_custom_range(pd.Timestamp("2024-03-01"), 12, 1, 2, 28) is False

    def test_boundary_start(self):
        assert is_date_in_custom_range(pd.Timestamp("2024-03-01"), 3, 1, 3, 21) is True

    def test_boundary_end(self):
        assert is_date_in_custom_range(pd.Timestamp("2024-03-21"), 3, 1, 3, 21) is True

    def test_leap_day_excluded(self):
        assert is_date_in_custom_range(pd.Timestamp("2024-02-29"), 2, 1, 2, 29) is False


class TestCustomRange:
    def test_daily_mode_short_range(self):
        """Custom range <=31 days should use daily MM-DD labels averaged across years."""
        raw = _make_raw_data(
            dates=["2023-03-01", "2023-03-02", "2024-03-01", "2024-03-02"],
            temp_max=[20.0, 22.0, 24.0, 26.0],
            temp_min=[10.0, 12.0, 14.0, 16.0],
            precip=[1.0, 2.0, 3.0, 4.0],
        )
        df = process_weather_data(raw, "Custom Range", "metric", monthly=False,
                                  custom_start=(3, 1), custom_end=(3, 10))
        assert len(df) == 2  # 03-01 and 03-02 averaged across years
        assert list(df["date_label"]) == ["03-01", "03-02"]
        # avg(20, 24) = 22.0 for 03-01
        assert abs(df.iloc[0]["temp_max"] - 22.0) < 0.01

    def test_monthly_mode_long_range(self):
        """Custom range >31 days should auto-switch to monthly averages."""
        raw = _make_raw_data(
            dates=["2024-01-15", "2024-01-16", "2024-02-15", "2024-03-15"],
            temp_max=[20.0, 22.0, 18.0, 24.0],
            temp_min=[10.0, 12.0, 8.0, 14.0],
            precip=[1.0, 2.0, 3.0, 4.0],
        )
        df = process_weather_data(raw, "Custom Range", "metric", monthly=False,
                                  custom_start=(1, 1), custom_end=(3, 31))
        assert len(df) == 3  # Jan, Feb, Mar
        jan = df.iloc[0]
        assert abs(jan["temp_max"] - 21.0) < 0.01  # avg(20, 22)
        assert df.iloc[0]["date_label"] == "January"

    def test_filters_by_day_month(self):
        """Custom range should filter to the specific day/month window."""
        raw = _make_raw_data(
            dates=["2024-03-01", "2024-03-21", "2024-03-25", "2024-06-15"],
            temp_max=[20.0, 22.0, 24.0, 30.0],
            temp_min=[10.0, 12.0, 14.0, 20.0],
            precip=[1.0, 2.0, 3.0, 5.0],
        )
        df = process_weather_data(raw, "Custom Range", "metric", monthly=False,
                                  custom_start=(3, 1), custom_end=(3, 21))
        assert len(df) == 2  # Only 03-01 and 03-21, not 03-25 or 06-15

    def test_cross_year_range(self):
        """Custom range crossing year boundary (e.g., Dec-Feb) should work."""
        raw = _make_raw_data(
            dates=["2023-12-15", "2024-01-15", "2024-02-15", "2024-05-15"],
            temp_max=[30.0, 28.0, 32.0, 20.0],
            temp_min=[20.0, 18.0, 22.0, 10.0],
            precip=[2.0, 3.0, 4.0, 8.0],
        )
        df = process_weather_data(raw, "Custom Range", "metric", monthly=False,
                                  custom_start=(12, 1), custom_end=(2, 28))
        # Should include Dec, Jan, Feb but not May
        assert len(df) == 3

    def test_imperial_conversion(self):
        """Unit conversion should still apply in custom range mode."""
        raw = _make_raw_data(
            dates=["2024-01-15"],
            temp_max=[0.0],
            temp_min=[-10.0],
            precip=[25.4],
        )
        df = process_weather_data(raw, "Custom Range", "imperial", monthly=False,
                                  custom_start=(1, 1), custom_end=(1, 31))
        row = df.iloc[0]
        assert abs(row["temp_max"] - 32.0) < 0.1  # 0C = 32F
        assert abs(row["precip_sum"] - 1.0) < 0.1  # 25.4mm = 1 inch
