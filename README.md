# WeatherSnake

A simple historical weather analyzer that fetches multi‑year averages for temperature and precipitation and visualizes them.

## Features

- **CLI** (`weather_juice.py`) – scriptable, supports custom date ranges, seasons, depth (years of history), metric/imperial units.
- **GUI** (`ui_app.pyw`) – friendly Tkinter interface with presets, monthly averages, shared Y‑axis option, and export to JPG.
- **Automatic Windows launcher** (`weather graph launch.bat`) – checks for Python, creates a virtual environment, installs dependencies, and starts the GUI.
- **Cross‑platform** – works on any system with Python 3.11+ and the required packages.
- **CI/CD** – GitHub Actions builds standalone executables for Windows (GUI & CLI) on every push to `main` and on version tags.

## Quick Start (Windows)

1. Download the latest release from the [Releases](https://github.com/deanable/WeatherSnake/releases) page (either the GUI or CLI `.exe`).
2. Double‑click the executable – no installation required.

   *Or* use the provided batch file:
   1. Ensure you have git and an internet connection.
   2. Double‑click `weather graph launch.bat`.
   3. The script will download the source, set up a virtual environment, install dependencies, and launch the GUI.

## Usage

### Command‑line interface

```bash
python weather_juice.py --city "Cape Town" --period Summer --depth 10 --units metric
```

**Options**

| Option | Description |
|--------|-------------|
| `--city` | Location name or one of the presets: Cape Town, Johannesburg, Durban. |
| `--period` | Season (`Summer`, `Autumn`, `Winter`, `Spring`) or `Full Year`. Required unless using `--start-day`/`--start-month`/`--end-day`/`--end-month` for a custom range. |
| `--depth` | Number of past years to average (1, 5, 10, or 20). |
| `--units` | `metric` (°C, mm) or `imperial` (°F, inch). |
| `--monthly` | Output monthly averages instead of daily‑of‑year values. |
| `--unify-scales` | Use the same Y‑axis range for temperature and precipitation. |
| `--start-day`, `--start-month`, `--end-day`, `--end-month` | Define a custom day‑month range (requires `--depth`). All four must be supplied together. |
| `--list-presets` | Show the built‑in city list and exit. |

**Examples**

```bash
# Summer averages for Johannesburg over the last 5 years, imperial units
python weather_juice.py --city Johannesburg --period Summer --depth 5 --units imperial

# Custom range: 15 Nov to 28 Feb (covers austral summer) over 10 years
python weather_juice.py --city "Cape Town" --start-day 15 --start-month 11 --end-day 28 --end-month 2 --depth 10

# Monthly precipitation for Durban, full year, metric
python weather_juice.py --city Durban --period "Full Year" --depth 20 --monthly --units metric
```

### Graphical user interface

- Choose a location from the dropdown or type a custom name.
- Select a period (season, full year, month, or custom range).
- Set the depth (years of history).
- Pick metric or imperial units.
- Toggle **Monthly Average** and **Shared Y‑Axis** as desired.
- Click **Fetch Data** – the table and chart will update.
- Use **Save to JPG** to export the current chart.

The GUI remembers your last selections and restarts with them.

## How it works

1. The application queries a public weather API (Open‑Meteo) for historical daily data.
2. It filters the data to the requested season or custom day‑month window.
3. It computes the mean temperature (max/min) and precipitation for each day‑of‑year or month, averaging over the requested number of years.
4. Optionally, values are converted to imperial units.
5. Results are shown in a table, saved as CSV, and plotted as a combined line/bar chart with a small logo watermark.

## License

This project is released under the MIT License – see the `LICENSE` file for details.

## Acknowledgments

- Weather data provided by [Open‑Meteo](https://open-meteo.com/).
- Built with Python, `requests`, `pandas`, `matplotlib`, and `tkinter`.