"""Shared chart/UI theme — single source of truth for WeatherSnake colours.

The GUI chrome (ui_app.pyw), the embedded matplotlib figure (output.py), and
the QuickChart renderer (quickchart_client.py) all draw from this palette so
the app reads as one product everywhere data is shown.
"""
import matplotlib

# ── Weather-themed colour palette ──────────────────────────────────────────
PALETTE = {
    "deep_ocean":     "#1A2332",   # stable conditions, data surfaces
    "temp_warm":      "#E67E22",   # warm temperatures/heat
    "temp_cool":      "#3B82F6",   # cool temperatures/cold
    "precipitation":  "#60A5FA",   # rain/snow
    "bg_light":       "#F8FAFC",   # clean workspace
    "accent_warning": "#F59E0B",   # alerts, important info
    "text_primary":   "#0F172A",   # main weather metrics
    "text_secondary": "#64748B",   # supporting info
    "text_muted":     "#94A3B8",   # captions, labels
    "surface":        "#FFFFFF",   # cards, panels
    "success":        "#10B981",   # positive trends
    "danger":         "#EF4444",   # alerts, warnings
    "divider":        "#E2E8F0",   # subtle rules
    "input_bg":       "#FFFFFF",   # entry fields
}

# Font stack, most-preferred first; matplotlib resolves the first installed
# family and falls back to its own default when none are present.
FONT_STACK = ["Inter", "Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"]

# ── Matplotlib defaults ────────────────────────────────────────────────────
MPL_RC = {
    "font.family": "sans-serif",
    "font.sans-serif": FONT_STACK,

    "figure.facecolor": PALETTE["surface"],
    "axes.facecolor": PALETTE["surface"],
    "savefig.facecolor": PALETTE["surface"],

    "text.color": PALETTE["text_primary"],
    "axes.labelcolor": PALETTE["text_secondary"],
    "axes.edgecolor": PALETTE["divider"],
    "axes.linewidth": 1.0,
    "axes.titlecolor": PALETTE["deep_ocean"],
    "axes.titleweight": "bold",
    "axes.titlesize": 13,

    # Only show top/right spine removal; grid is drawn explicitly per-axis
    # so twin-axis figures don't get double rules.
    "axes.spines.top": False,
    "axes.spines.right": False,

    "xtick.color": PALETTE["text_secondary"],
    "ytick.color": PALETTE["text_secondary"],
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "axes.labelsize": 10,

    "legend.frameon": False,
    "legend.fontsize": 9,

    "lines.linewidth": 2.2,
}


def apply_mpl_theme():
    """Apply the themed rcParams to matplotlib's global state."""
    matplotlib.rcParams.update(MPL_RC)


def rgba(hex_color: str, alpha: float) -> str:
    """Convert '#RRGGBB' to an 'rgba(r, g, b, a)' string (Chart.js style)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


__all__ = ["PALETTE", "FONT_STACK", "MPL_RC", "apply_mpl_theme", "rgba"]
