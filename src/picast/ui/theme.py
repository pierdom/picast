"""Color and style constants."""
from rich.theme import Theme

# Palette
ACCENT = "#c084fc"       # purple
ACCENT_DIM = "#7c3aed"
FG = "#e2e8f0"
FG_DIM = "#64748b"
BG_SELECT = "#1e293b"
SUCCESS = "#4ade80"
WARNING = "#facc15"
DANGER = "#f87171"
BORDER_COLOR = "#334155"
DETAIL_BORDER = "#1d4ed8"   # blue for the detail/right panel
PLAYING_COLOR = "#c084fc"
NEW_COLOR = "#38bdf8"
STARTED_COLOR = "#facc15"
DONE_COLOR = "#4ade80"

RICH_THEME = Theme({
    "accent": ACCENT,
    "dim": FG_DIM,
    "selected": f"bold {FG} on {BG_SELECT}",
    "playing": PLAYING_COLOR,
    "ep.new": NEW_COLOR,
    "ep.started": STARTED_COLOR,
    "ep.done": DONE_COLOR,
    "header": f"bold {FG} on {ACCENT_DIM}",
    "border": BORDER_COLOR,
})

PANEL_BORDER = "dim"
PLAYING_ICON = "▶"
PAUSED_ICON = "⏸"
FOLLOW_ICON = "★"
UNFOLLOW_ICON = "☆"
NEW_ICON = "●"
STARTED_ICON = "◑"
DONE_ICON = "✓"
