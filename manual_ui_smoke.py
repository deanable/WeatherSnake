"""Headless smoke test for the redesigned WeatherSnake GUI.

Runs the real WeatherJuiceApp with a mocked network layer. The Tk root is
mapped but parked offscreen so widget mapping states are meaningful.
"""
import sys
import time
import types
import pandas as pd

import tkinter as tk
import tkinter.messagebox as mb

# ── Stub the network layer before ui_app is imported ──────────────────────
FAKE_GEO = {"latitude": -33.9, "longitude": 18.4}

def fake_get_coordinates(city):
    if city == "BOOM":
        raise RuntimeError("Failed to get coordinates for 'BOOM'")
    return FAKE_GEO["latitude"], FAKE_GEO["longitude"]

def _fake_raw(years=5):
    import numpy as np
    dates = pd.date_range("2019-01-01", periods=365 * years, freq="D")
    rng = np.random.default_rng(7)
    return {
        "daily": {
            "time": [d.strftime("%Y-%m-%d") for d in dates],
            "temperature_2m_max": (20 + 8 * np.sin(np.arange(len(dates)) / 58)
                                   + rng.normal(0, 1.5, len(dates))).tolist(),
            "temperature_2m_min": (10 + 6 * np.sin(np.arange(len(dates)) / 58)
                                   + rng.normal(0, 1.5, len(dates))).tolist(),
            "precipitation_sum": rng.gamma(0.4, 4.0, len(dates)).round(2).tolist(),
            "weather_code": [61] * len(dates),
        }
    }

RAW = _fake_raw()

def fake_fetch(lat, lon, start_date, end_date):
    return RAW

import api_client
api_client.get_coordinates = fake_get_coordinates
api_client.fetch_historical_weather = fake_fetch

import ui_app

failures = []
tk_errors = []

def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    extra = f"  ({detail})" if detail and not cond else ""
    print(f"[{status}] {name}{extra}")
    if not cond:
        failures.append(name)

root = tk.Tk()
root.geometry("440x340+-32000+0")   # mapped, but far offscreen

def trap(exc, val, tb):
    tk_errors.append(f"{exc.__name__}: {val}")
root.report_callback_exception = trap

app = ui_app.WeatherJuiceApp(root)
root.update_idletasks()
root.update()

def pump(predicate, timeout=20.0):
    """Wait for predicate() while keeping the Tk main loop RUNNING.

    Worker threads call root.after(...), which requires the interpreter to be
    inside mainloop() — exactly like the real app. We stay inside one
    mainloop() invocation and use a repeating tick to re-check the predicate.
    """
    end = time.time() + timeout

    def tick():
        if predicate() or time.time() > end:
            root.quit()
        else:
            root.after(25, tick)

    root.after(25, tick)
    root.mainloop()
    root.update()
    return bool(predicate())

# ── Construction & layout basics ───────────────────────────────────────────
check("app constructs with themed fonts",
      ui_app._UI_FONT_NAME in ("Inter", "Segoe UI", "Helvetica", "Arial", "TkDefaultFont"),
      ui_app._UI_FONT_NAME)
check("no tk callback errors during construction", not tk_errors, "; ".join(tk_errors[:3]))

# ── Period switching ──────────────────────────────────────────────────────
app.period_var.set("Custom Range")
app._on_period_changed()
root.update()
check("Custom Range shows selector row",
      all(w.winfo_manager() == "pack" for w in app._custom_range_widgets))
check("Custom Range disables monthly toggle",
      str(app.monthly_chk.cget("state")) == "disabled")

app.period_var.set("Month")
app._on_period_changed()
root.update()
check("Month hides custom-range widgets",
      all(w.winfo_manager() != "pack" for w in app._custom_range_widgets))
check("Month shows month selector",
      all(w.winfo_manager() == "pack" for w in app._month_widgets))

app.period_var.set("Summer")
app._on_period_changed()
root.update()
check("Season hides both selector groups",
      all(w.winfo_manager() != "pack"
          for w in app._custom_range_widgets + app._month_widgets))
check("Season re-enables monthly toggle",
      str(app.monthly_chk.cget("state")) == "normal")

# ── Custom city entry swap ─────────────────────────────────────────────────
app.location_var.set("Custom...")
app._on_location_changed()
root.update()
check("Custom city entry mapped, combobox unmapped",
      app.custom_city_entry.winfo_manager() == "pack"
      and app.location_cb.winfo_manager() != "pack")
app.location_var.set("Cape Town")
app._on_location_changed()
root.update()
check("Preset selection restores combobox",
      app.location_cb.winfo_manager() == "pack"
      and app.custom_city_entry.winfo_manager() != "pack")

# ── Fake fetch: Summer ─────────────────────────────────────────────────────
app.location_var.set("Cape Town")
app._on_location_changed()
app.period_var.set("Summer")
app._on_period_changed()
app.monthly_var.set(True)
app.insights_var.set(True)
app.yearly_var.set(False)
app.fetch_data_thread()
done = pump(lambda: str(app.fetch_btn.cget("state")) == "normal")
check("Summer fetch completed (buttons re-enabled)", done)
check("Summer fetch populated the data table", len(app.tree.get_children()) > 0,
      f"rows={len(app.tree.get_children())}")
check("Summer fetch produced a chart figure", app.current_fig is not None)
check("timeline hidden after successful fetch",
      app.timeline.winfo_manager() != "pack")
check("no tk callback errors after Summer fetch", not tk_errors, "; ".join(tk_errors[:3]))

summary_widget = app.conditions_text
check("analysis summary margin populated", summary_widget is not None)
if summary_widget:
    text = summary_widget.get("1.0", "end").strip()
    check("analysis summary has content", len(text) > 50, f"chars={len(text)}")
    check("summary shows climate highlights and insights output",
          "Mean temperature" in text and len(text) > 50)

# ── Fake fetch: Month (the previously crashing path) ──────────────────────
app.period_var.set("Month")
app._month_select_var.set("Jul")
app._on_period_changed()
app.monthly_var.set(False)
app.fetch_data_thread()
done = pump(lambda: str(app.fetch_btn.cget("state")) == "normal")
check("Month fetch completed", done)
check("Month fetch populated the data table", len(app.tree.get_children()) > 0)
check("Month fetch set display period to July",
      getattr(app, "_last_period", "") == "July", str(getattr(app, "_last_period", "")))
# Monthly toggle is off here, so July yields 31 day-of-year averages
# (one per calendar day, averaged across years) — same as the original app.
check("Month fetch has 31 day-of-year rows", len(app.tree.get_children()) == 31,
      f"rows={len(app.tree.get_children())}")
check("no tk callback errors after Month fetch", not tk_errors, "; ".join(tk_errors[:3]))

# ── Fake fetch: Custom Range (cross-year) ──────────────────────────────────
app.period_var.set("Custom Range")
app._on_period_changed()
app._cr_start_month.set("Nov")
app._cr_start_day.set("15")
app._cr_end_month.set("Feb")
app._cr_end_day.set("28")
app.fetch_data_thread()
done = pump(lambda: str(app.fetch_btn.cget("state")) == "normal")
check("Custom Range fetch completed", done)
check("Custom Range display period",
      getattr(app, "_last_period", "").startswith("Custom:"),
      str(getattr(app, "_last_period", "")))
check("Custom Range dataframe is not empty",
      getattr(app, "_last_df", None) is not None and not app._last_df.empty)
check("no tk callback errors after Custom Range fetch", not tk_errors,
      "; ".join(tk_errors[:3]))

# ── Error path ─────────────────────────────────────────────────────────────
shown = []
mb.showerror = lambda *a, **k: shown.append(a)
app.location_var.set("Custom...")
app._on_location_changed()
app.custom_city_var.set("BOOM")
app.period_var.set("Summer")
app._on_period_changed()
app.fetch_data_thread()
got_dialog = pump(lambda: bool(shown), timeout=20)
check("error dialog shown for bad city", got_dialog)
check("fetch button re-enabled after error",
      str(app.fetch_btn.cget("state")) == "normal")
check("timeline hidden after error", app.timeline.winfo_manager() != "pack")

# ── Settings round-trip ────────────────────────────────────────────────────
app.save_settings()
import json
with open(ui_app.SETTINGS_FILE, "r", encoding="utf-8") as f:
    saved = json.load(f)
check("settings include insights/yearly keys",
      "insights" in saved and "yearly" in saved)

print()
if tk_errors:
    print("TK CALLBACK ERRORS:")
    for e in tk_errors[:10]:
        print("  ", e)
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("ALL SMOKE CHECKS PASSED")
