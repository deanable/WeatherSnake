# Changelog

All notable changes to WeatherSnake are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

## [1.2.0] - 2026-09-12

### Added
- **Sigstore signing of release artifacts**: the release job installs cosign (`sigstore/cosign-installer@v3`), generates a `SHA256SUMS.txt` manifest, and keylessly signs every installer/archive plus the manifest with the workflow's ephemeral OIDC identity. `.sig` and `.pem` certificate files are published next to the binaries on the GitHub Release, after an in-workflow verification pass against `https://github.com/deanable/WeatherSnake/.github/workflows/build-release.yml@refs/tags/v*`. Verify a download with `cosign verify-blob --certificate <file>.pem --signature <file>.sig --certificate-identity-regexp '^https://github.com/deanable/WeatherSnake/\.github/workflows/build-release\.yml@refs/tags/v.+$' --certificate-oidc-issuer https://token.actions.githubusercontent.com <file>`.

### Fixed
- **Infogram export now targets the current Infogram API (`api.infogram.com`).** The prior fix implemented the legacy HMAC-signed API (`infogr.am/service/v1` with an API key *and* secret); accounts provisioned on the current API use a single bearer token instead. The client now implements the documented token workflow: `copyProject` (duplicate a user-chosen template containing a text block and table chart) → `getProjectData` → `updateProjectEntities` (title + weather table) → `publishProject` (share URL). One `INFOGRAM_API_TOKEN` plus `INFOGRAM_TEMPLATE_ID` replaces the key/secret pair; the *Infogram Token* button asks for both values and verifies them live. Background threading, parented dialogs, and per-step error messages (rejected token, wrong template ID, template without a chart, 5xx, network) are unchanged. The legacy HMAC signing implementation and its worked-example tests were replaced by flow tests for the new endpoints.

## [1.1.0] - 2026-09-12

### Added
- **Built-in help system**: a 19-topic compiled HTML Help manual (`WeatherSnake.chm`) authored under `help/html/` (welcome, getting started, window tour, per-control topics, conditions/extremes/yearly/comparison explainers, exports, CLI reference, data sources, troubleshooting, about) with contents tree, keyword index, and full-text search.
- **Context-sensitive F1**: every input control is registered with a help context id (`help_launcher.py`); F1 (and Tk's `<Help>` event) opens the compiled help directly at the matching topic via the native HTML Help viewer on Windows, falling back to the same pages in the system browser on macOS/Linux or when `hhctrl.ocx` is unavailable.
- **Help menu** in the GUI (Help Topics, Getting Started, Using the Window, CLI Reference, Data Sources and Accuracy, Troubleshooting, Keyboard Shortcuts, About) plus new keyboard shortcuts: `F1`/`Ctrl+F1` for help, `Ctrl+R` fetch, `Ctrl+S` save chart, `Ctrl+E` export CSV, and a File menu.
- **Help build tooling** (`build_chm.py`): validates the help tree on every platform (topic files, charset/styles, tag balance, cross-links, `.hhp`/`.hhc`/`.hhk` consistency, F1 id mapping) and compiles the CHM with `hhc.exe` when available; release CI installs HTML Help Workshop via Chocolatey, compiles the CHM on the Windows runner, and bundles it into the Windows exes and installer (standalone double-clickable copy included); macOS/Linux builds and packages ship the same HTML topics as the browser fallback.
- `test_help.py`: 22 tests covering help-tree validation, CHM project consistency, and the F1 registry/fallback behaviour.
- **Weather-condition summaries**: fetches WMO `weather_code` from Open-Meteo, translates it into plain-language conditions, and reports the most-common-condition distribution plus rain-day share for any window (`conditions.py`; CLI shows it by default, GUI shows it in the insights panel).
- **Variability & extremes**: typical daily high/low ranges (5th–95th percentile), record low/high in the window, wettest and driest historical years, years above average precipitation, and rain days per year (`stats.py`).
- **Year-over-year breakdown** (`--yearly`): per-year window averages/totals with least-squares trend-per-decade estimates for highs, lows, and precipitation.
- **Recent vs baseline comparison** (`--compare-recent N [--compare-baseline M]`): compares the most recent N complete years against a preceding baseline window, with unit-aware deltas.
- **`--precip-threshold MM`** CLI flag mirroring the GUI's dew/frost exclusion setting.
- Insights panel in the GUI: conditions/variability and yearly breakdown rendered in a scrollable text area, with new "Conditions & Extremes" and "Yearly Breakdown" toggles (persisted in settings).
- Cross-platform CI: test matrix (Python 3.11/3.13 × Ubuntu/Windows) with compile checks on every push/PR (`.github/workflows/ci.yml`).
- **Native installers** built on `v*` tags (tests gate the builds):
  - Windows: signed-off setup .exe via Inno Setup (`packaging/installers.iss`) with Start Menu shortcuts, optional desktop icon, and a proper uninstaller; per-user fallback when no admin rights.
  - macOS: drag-to-Applications `.dmg` (plus `.app` zip) built from a real `.app` bundle.
  - Linux: `.deb` package installing `weathersnake` / `weathersnake-cli` to `/usr/bin`, with a desktop entry and hicolor icon (packaging validated locally with `dpkg-deb`).
  - Portable archives (Windows zip, Linux tar.gz) for no-install usage.
- **Version stamping**: `version.py` is the single source of truth; release CI derives the version from the `v*` tag and stamps it into the build, and the GUI window title reports it.
- Frozen-build data locations: settings (`ui_settings.json`) and logs (`weathersnake.log`) now write to the user's application-data directory in packaged builds instead of a temp extraction dir, so preferences survive restarts and uninstalls cleanly.
- Cross-platform build & release pipeline: on `v*` tags, tests gate PyInstaller builds for Windows, macOS, and Linux, published to a GitHub Release with generated notes (`.github/workflows/build-release.yml`).
- `test_insights.py`: unit tests for weather-code translation, condition distributions, variability stats, year-over-year trends, and depth comparisons.
- `CHANGELOG.md`.

### Changed
- `--depth` now accepts 1, 3, 5, 7, 10, 15, or 20 years (previously 1, 5, 10, 20) in both CLI and GUI; docs updated to match.
- Analysis depth is now exact: within-year seasons no longer silently analyze one extra year (the extra fetch year is only used for cross-year windows like Dec–Feb, where it keeps the earliest occurrence complete).
- Per-year statistics only count *complete* window occurrences; the trailing partial occurrence (e.g. a December with no Jan/Feb follow-up yet) is excluded.
- CSV export returns the written filename; figure/plot helpers reuse shared unit formatters.
- README rewritten to document the actual feature set (conditions, variability, trends, comparisons, cross-platform builds).

### Fixed
- `--list-presets` no longer requires `--city` (argparse previously rejected the invocation before the handler could run).
- Temperature/precipitation *deltas* in the recent-vs-baseline comparison are now converted for imperial display (previously printed metric-unit deltas with an imperial table).
- The trailing partial year (e.g. a December with no Jan/Feb follow-up yet) no longer skews per-year statistics.
- Chart creation uses the shared unit formatters instead of duplicating unit-selection logic.

## [1.0.0] - 2026-06-04 (initial snapshot)

### Added
- Historical temperature/precipitation averages per month or day-of-year over a selectable depth of years.
- Seasons, full year, single month, and custom day/month windows with cross-year wrapping.
- Metric/imperial conversion, monthly averaging, shared Y-axis option.
- Tkinter GUI with presets, custom locations, settings persistence, JPG/PNG/CSV export, and Infogr.am infographic export.
- Windows launcher (`weather graph launch.bat`) and Windows exe build workflow.
