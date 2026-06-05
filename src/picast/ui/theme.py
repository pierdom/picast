"""Color and style constants."""
from rich.theme import Theme

# Palette — minimalistic dark with orange accents
ACCENT = "#f97316"       # orange-500
ACCENT_DIM = "#ea580c"   # orange-600
FG = "#f1f5f9"
FG_DIM = "#64748b"
BG_SELECT = "#1c2533"
SUCCESS = "#4ade80"
WARNING = "#facc15"
DANGER = "#f87171"
BORDER_COLOR = "#374151"
DETAIL_BORDER = "#374151"
PLAYING_COLOR = "#fb923c"  # orange-400
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
