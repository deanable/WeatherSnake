# WeatherSnake

A historical weather analyzer that turns decades of daily weather into practical insight: multi-year averages, most-common conditions, typical ranges and extremes, year-over-year trends, and recent-vs-baseline comparisons — so you can reason about future weather by reflecting on the past.

Weather data comes from the free [Open-Meteo](https://open-meteo.com/) Archive API — no API key required.

## Features

- **Averages, done properly** — temperature and precipitation averaged per month or day-of-year across your chosen depth of years, with dew/frost excluded via a configurable precipitation threshold.
- **Weather-condition summaries** — plain-language conditions (clear, overcast, drizzle, thunderstorm, …) derived from WMO weather codes, with a "most common condition" distribution and rain-day share for any window.
- **Variability & extremes** — typical daily high/low ranges (5th–95th percentile), record low/high, wettest and driest historical years, years above average, and rain days per year. Not just means.
- **Year-over-year breakdown** — per-year averages/totals with a least-squares trend-per-decade estimate for highs, lows, and precipitation.
- **Recent vs baseline comparison** — compare the most recent N years against a baseline window to see whether things are shifting.
- **Flexible windows** — seasons, full year, a single month, or any custom day/month range (crosses year boundaries, e.g. 15 Nov – 28 Feb).
- **Metric or imperial** — °C/mm or °F/inches throughout, including deltas.
- **Two interfaces** — a scriptable CLI and a desktop GUI with the same engine.
- **Exports** — CSV of processed data, PNG/JPG chart export, a shareable interactive Datawrapper chart, and a keyless QuickChart PNG renderer from the GUI.
- **Cross-platform, with installers** — native installers for Windows (setup .exe), macOS (.dmg), and Linux (.deb), plus portable builds; CI produces them all on version tags.
- **Built-in help system** — a compiled HTML Help manual (`WeatherSnake.chm`, 19 topics) shipped inside the app, with a Help menu, context-sensitive F1 on every control, keyboard shortcuts, and a browser-based fallback on macOS/Linux.

## Quick Start

### Windows

1. Download `WeatherSnake-<version>-windows-setup.exe` from the [Releases](https://github.com/deanable/WeatherSnake/releases) page.
2. Run it — Start Menu shortcuts, an optional desktop icon, and an uninstaller are set up for you. (A per-user install is offered if you don't have admin rights.)

Prefer no installation? Grab `WeatherSnake-<version>-windows-x64-portable.zip` or the raw `WeatherSnake.exe` / `WeatherSnake-CLI.exe`.

*Or* run `weather graph launch.bat`, which checks for Python, creates a virtual environment, installs dependencies, and starts the GUI.

### macOS

Requires macOS 10.15 (Catalina) or later — Intel Macs natively, Apple Silicon via Rosetta 2 (macOS offers to install Rosetta on first launch).

1. Download `WeatherSnake-<version>-macos.dmg` from Releases.
2. Open it and drag **WeatherSnake** into **Applications**. (The CLI binary is included on the disk image.)

The app is unsigned, so the first launch may report it "cannot be opened because the developer cannot be verified": right-click **WeatherSnake** in Applications and choose **Open**, then confirm.

### Linux

```bash
sudo dpkg -i weathersnake_<version>_amd64.deb
weathersnake        # GUI (also in your app menu)
weathersnake-cli    # command line
```

A portable tarball (`WeatherSnake-<version>-linux-x64-portable.tar.gz`) is also available if you'd rather not install anything.

### From source (any platform)

### From source (any platform)

```bash
pip install -r requirements.txt
python3 weather_juice.py --city "Cape Town" --period Winter --depth 10
```

## Usage

### Command-line interface

```bash
# Winter averages for Cape Town over the last 10 years
python weather_juice.py --city "Cape Town" --period Winter --depth 10

# Are recent summers different from the past 10 years?
python weather_juice.py --city Durban --period Summer --depth 20 --yearly --compare-recent 5

# Custom window crossing the year boundary, imperial units, ignore dew
python weather_juice.py --city "Cape Town" --start-day 15 --start-month 11 --end-day 28 --end-month 2 --depth 10 --units imperial --precip-threshold 1.0
```

Every run prints a summary table, saves `weather_report_<city>_<period>.csv`, and saves `weather_plot_<city>_<period>.png`.

**Options**

| Option | Description |
|--------|-------------|
| `--city` | Location name or preset (Cape Town, Johannesburg, Durban). |
| `--period` | `Summer`, `Autumn`, `Winter`, `Spring`, or `Full Year`. Required unless using a custom range. |
| `--depth` | Years of history to analyze: 1, 3, 5, 7, 10, 15, or 20. |
| `--units` | `metric` (°C, mm) or `imperial` (°F, inch). |
| `--monthly` | Monthly averages instead of day-of-year values. |
| `--unify-scales` | Share the Y-axis range between temperature and precipitation. |
| `--precip-threshold MM` | Zero out daily precipitation below this many mm (excludes dew/frost). |
| `--no-insights` | Skip the condition and variability/extremes summaries. |
| `--yearly` | Year-by-year breakdown with trend-per-decade estimates. |
| `--compare-recent N` | Compare the most recent N years against a baseline window. |
| `--compare-baseline M` | Baseline depth in years for `--compare-recent` (default 10). Requires `--depth >= N + M`. |
| `--start-day/--start-month/--end-day/--end-month` | Custom day-month window (all four together, requires `--depth`). |
| `--list-presets` | Show the built-in city list. |

**Sample output**

```
Weather Conditions (historical)
------------------------------------------------------------
  Drizzle                  256 days    47.4%
  Overcast                 126 days    23.3%
  Rain                     123 days    22.8%
  ...
  Rain days (>=1 mm): 45.2% of days

Variability & Extremes
------------------------------------------------------------
  Typical daily high: 80.8°F (range usually 74.2°F to 87.1°F)
  Record low/high in window: 60.3°F / 98.1°F
  Wettest year:  2022 (22.1 inch)
  Driest year:   2023 (11.0 inch)

Recent vs Baseline
------------------------------------------------------------
  Metric           Recent             Baseline           Change
  Avg high         16.7°C             16.5°C             +0.2°C
  Precip total     376.1 mm           266.2 mm           +109.9 mm
```

### Graphical user interface

Run `ui_app.pyw` (or the packaged executable). The GUI offers the same engine plus:

- Preset or custom locations, seasons/months/custom ranges, depth and unit pickers.
- **Conditions & Extremes** panel: most-common conditions, rain-day share, typical ranges, records, wettest/driest years.
- **Yearly Breakdown** panel: per-year averages/totals and trends.
- Monthly-Average and Shared-Y-Axis toggles, precipitation threshold.
- **Help menu** (Help Topics, Getting Started, Using the Window, CLI Reference, Data Sources, Troubleshooting, Keyboard Shortcuts, About) and **context-sensitive F1**: hover or focus any control and press F1 to open the matching topic in the compiled help. `Ctrl+F1` opens the contents; `Ctrl+R` fetches, `Ctrl+S` saves the chart, `Ctrl+E` exports CSV.
- **Save to JPG**, **Export CSV**, **CSV + Online Chart**, and **QuickChart PNG**:
  - *CSV + Online Chart* publishes an interactive chart on **Datawrapper** (what newsrooms use). Enter your free API token once via the *Datawrapper Token* button (or set `DATAWRAPPER_ACCESS_TOKEN`) — the app creates the chart, uploads your data, labels the series, and publishes it via the Datawrapper API, returning a public share link. Free tier: 500 creates / 1,000 publishes per month.
  - *QuickChart PNG* renders the data as a chart image via **QuickChart** with **no account and no API key** (free tier: 1,000 charts/month) — the open-source service can also be self-hosted.
  Both run in the background with clear success/error dialogs.

Settings persist between sessions in `ui_settings.json`.

## How it works

1. Geocodes the location via Open-Meteo's Geocoding API.
2. Fetches daily `temperature_2m_max`, `temperature_2m_min`, `precipitation_sum`, and `weather_code` from the Open-Meteo Archive API for the requested depth (cross-year windows fetch one extra leading year so the earliest occurrence is complete).
3. Filters to the season or custom day/month window and excludes leap days.
4. Computes averages per month/day-of-year, condition distributions, variability/extremes, per-year totals, trends, and recent-vs-baseline deltas (all cross-year groupings label an occurrence by the year it starts, and incomplete final occurrences are excluded).
5. Converts to imperial if requested, prints summaries, and writes CSV + chart files.

## Project layout

| File | Purpose |
|------|---------|
| `weather_juice.py` | CLI entry point |
| `ui_app.pyw` | Tkinter GUI |
| `version.py` | Single-source app version, stamped by release CI |
| `packaging/installers.iss` | Inno Setup script for the Windows installer |
| `api_client.py` | Geocoding + archive fetch |
| `datawrapper_client.py` | Datawrapper v3 REST client (create → data → publish, error mapping) |
| `quickchart_client.py` | QuickChart client (Chart.js config builder, PNG rendering, shareable URL) |
| `processing.py` | Season/custom-range filtering and averaging |
| `conditions.py` | WMO weather-code translation and condition distributions |
| `stats.py` | Variability/extremes, year-over-year trends, depth comparisons |
| `output.py` | Console/insight formatting, CSV export, matplotlib figures |
| `logger_setup.py` | Rotating file logging (`weathersnake.log`) |
| `help_launcher.py` | Help runtime: CHM viewer integration, F1 registry, browser fallback |
| `help/html/` | Help topics (HTML), contents/index/project files for the CHM |
| `build_chm.py` | Help validator + CHM compiler driver (`python build_chm.py --compile`) |

## Development

```bash
pip install -r requirements.txt pytest
pytest test_processing.py test_insights.py test_help.py -q

# Validate the help tree (content, CHM project files, F1 mappings)
python build_chm.py
```

Compiling `WeatherSnake.chm` locally requires HTML Help Workshop (Windows only); release CI installs it via Chocolatey and compiles the CHM automatically. On macOS/Linux the same HTML topics serve as the built-in help, opened in the browser.

CI runs the test suite, compile checks, and help validation on Python 3.11/3.13 across Ubuntu and Windows on every push/PR; tagging `v*` builds the installers and portable packages — Windows setup .exe (Inno Setup), macOS .dmg, Linux .deb — plus portable archives, and publishes them in a GitHub release with generated notes. See [CHANGELOG.md](CHANGELOG.md) for release history.

## License

MIT — see the `LICENSE` file.

## Acknowledgments

- Weather data provided by [Open-Meteo](https://open-meteo.com/).
- Built with Python, `requests`, `pandas`, `numpy`, `matplotlib`, and `tkinter`.
