"""Color and style constants."""
from __future__ import annotations

from dataclasses import dataclass

from rich.theme import Theme

# ── fixed neutrals (never change) ────────────────────────────────────────────

FG = "#f1f5f9"
FG_DIM = "#64748b"
BG_SELECT = "#1c2533"
SUCCESS = "#4ade80"
WARNING = "#facc15"
DANGER = "#f87171"
BORDER_COLOR = "#374151"
DETAIL_BORDER = "#374151"
DONE_COLOR = FG_DIM

# ── accent presets ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Preset:
    accent: str
    accent_dim: str
    playing: str

_PRESETS: dict[str, _Preset] = {
    "orange": _Preset("#f97316", "#ea580c", "#fb923c"),
    "blue":   _Preset("#3b82f6", "#2563eb", "#60a5fa"),
    "green":  _Preset("#22c55e", "#16a34a", "#4ade80"),
    "purple": _Preset("#a855f7", "#9333ea", "#c084fc"),
    "cyan":   _Preset("#06b6d4", "#0891b2", "#22d3ee"),
}

THEME_NAMES: list[str] = list(_PRESETS)

# ── mutable accent globals (updated by set_theme) ─────────────────────────────

ACCENT: str = ""
ACCENT_DIM: str = ""
PLAYING_COLOR: str = ""
NEW_COLOR: str = ""
STARTED_COLOR: str = ""
RICH_THEME: Theme

_active_name: str = ""


def set_theme(name: str) -> None:
    global ACCENT, ACCENT_DIM, PLAYING_COLOR, NEW_COLOR, STARTED_COLOR, RICH_THEME, _active_name
    p = _PRESETS.get(name, _PRESETS["orange"])
    _active_name = name if name in _PRESETS else "orange"
    ACCENT = p.accent
    ACCENT_DIM = p.accent_dim
    PLAYING_COLOR = p.playing
    NEW_COLOR = p.accent
    STARTED_COLOR = p.accent_dim
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


def get_theme_name() -> str:
    return _active_name


def next_theme() -> str:
    idx = THEME_NAMES.index(_active_name)
    name = THEME_NAMES[(idx + 1) % len(THEME_NAMES)]
    set_theme(name)
    return name


# Initialize with default
set_theme("orange")

# ── icons (never change) ──────────────────────────────────────────────────────

PANEL_BORDER = "dim"
PLAYING_ICON = "▶"
PAUSED_ICON = "⏸"
FOLLOW_ICON = "♥"
UNFOLLOW_ICON = "♡"
NEW_ICON = "●"
STARTED_ICON = "◑"
DONE_ICON = "✓"
