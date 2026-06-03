"""Screen renderer.

One outer Panel with a Table inside — avoids the double-border that two
adjacent Panels create. Image is embedded as half-block art in the layout;
for graphics-protocol terminals it is also overlaid via cursor positioning
(covering the half-block art with a higher-quality render).

Scroll prevention: we lock the scroll region to the terminal height in
enter_screen() so the alternate-screen buffer never scrolls, which would
otherwise shift absolute cursor coordinates and put the image in the wrong row.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from rich import box as richbox
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text

from picast import image as img_mod
from picast.ui import panels, theme

# Image area (terminal cells)
IMAGE_COLS = 22
IMAGE_ROWS = 11   # half-block: 2 px/row → 22×22 px block

# Column split
LEFT_RATIO = 2
RIGHT_RATIO = 3

HEADER_HEIGHT = 1
FOOTER_HEIGHT = 3   # rule + player line + hints line


@dataclass
class RenderState:
    view: str = "home"
    search_mode: bool = False
    search_query: str = ""

    podcasts: list[dict] = field(default_factory=list)
    podcast_cursor: int = 0
    following_ids: set[int] = field(default_factory=set)
    following_count: int = 0   # podcasts[:following_count] are follows; rest are trending

    episodes: list[dict] = field(default_factory=list)
    episode_cursor: int = 0
    episode_statuses: dict[int, str] = field(default_factory=dict)

    selected_podcast: dict | None = None
    cover_image_bytes: bytes | None = None
    loading: bool = False

    now_playing_episode: dict | None = None
    now_playing_podcast_title: str = ""
    playback_position: float = 0.0
    playback_duration: float = 0.0
    is_playing: bool = False

    status: str = ""


class Renderer:
    def __init__(self) -> None:
        self._console: Console | None = None
        self._console_size: tuple[int, int] = (0, 0)
        self._last_cover: bytes | None = None
        self._image_lines: list[str] = []

    def _get_console(self, cols: int, rows: int) -> Console:
        if (cols, rows) != self._console_size:
            self._console_size = (cols, rows)
            self._console = Console(
                force_terminal=True,
                width=cols,
                height=rows,
                theme=theme.RICH_THEME,
                highlight=False,
                legacy_windows=False,
            )
        return self._console  # type: ignore[return-value]

    def enter_screen(self) -> None:
        sys.stdout.write("\033[?1049h")          # alternate screen
        sys.stdout.write("\033[?25l")            # hide cursor
        sys.stdout.write("\033[2J\033[H")        # clear + top-left
        sys.stdout.flush()
        img_mod._detect()                        # re-probe now that stdout is a real tty

    def exit_screen(self) -> None:
        sys.stdout.write("\033[?25h")            # show cursor
        sys.stdout.write("\033[?1049l")          # restore main screen
        sys.stdout.flush()

    def render(self, state: RenderState) -> None:
        try:
            sz = os.get_terminal_size()
            cols, rows = sz.columns, sz.lines
        except OSError:
            cols, rows = 80, 24

        if cols < 40 or rows < 10:
            return

        console = self._get_console(cols, rows)
        main_height = max(4, rows - HEADER_HEIGHT - FOOTER_HEIGHT)

        # Left column inner width:
        #   total left region = cols * 2/5
        #   minus outer Panel border (1 each side) + Table padding (1 each side) = 4
        left_region = cols * LEFT_RATIO // (LEFT_RATIO + RIGHT_RATIO)
        left_inner = left_region - 4   # for content column of the table

        list_height = main_height - 2  # Panel top + bottom border

        # ── left column content (podcast or episode list) ─────────────────────
        if state.view in ("home", "following"):
            if state.view == "following":
                list_title = "Following"
            elif state.following_count > 0:
                list_title = "Podcasts"
            else:
                list_title = "Trending"
            left_content = panels.podcast_list_content(
                state.podcasts, state.podcast_cursor, state.following_ids,
                playing_feed_id=None, height=list_height, width=left_inner,
                following_count=state.following_count if state.view == "home" else 0,
            )
        else:
            playing_ep_id = (
                state.now_playing_episode.get("id") if state.now_playing_episode else None
            )
            list_title = (
                state.selected_podcast.get("title", "Episodes")
                if state.selected_podcast else "Episodes"
            )
            left_content = panels.episode_list_content(
                state.episodes, state.episode_cursor, state.episode_statuses,
                playing_episode_id=playing_ep_id, height=list_height,
            )

        # ── right column content (image + detail text) ────────────────────────
        is_following = (
            state.selected_podcast is not None
            and state.selected_podcast.get("id", 0) in state.following_ids
        )
        right_content = panels.detail_content(
            state.selected_podcast,
            state.cover_image_bytes,
            IMAGE_COLS,
            IMAGE_ROWS,
            is_following=is_following,
            loading=state.loading,
        )

        # ── main panel: ONE Panel wrapping a 2-column Table ───────────────────
        tbl = Table(
            box=richbox.SIMPLE,   # gives "│" between columns, no outer lines
            padding=(0, 1),
            show_header=True,
            header_style=f"bold {theme.FG_DIM}",
            expand=True,
        )
        tbl.add_column(list_title, width=left_inner, no_wrap=True)
        tbl.add_column("Details")
        tbl.add_row(left_content, right_content)

        main_panel = Panel(tbl, border_style=theme.BORDER_COLOR, padding=0)

        # ── header ────────────────────────────────────────────────────────────
        header = Text(no_wrap=True)
        header.append("  ▶ picast", style=Style(color="#c084fc", bold=True))
        if state.view == "following":
            header.append("  Following", style=Style(color=theme.FG_DIM))
        elif state.view == "podcast" and state.selected_podcast:
            header.append(
                f"  {state.selected_podcast.get('title', '')}",
                style=Style(color=theme.FG_DIM, italic=True),
            )
        else:
            header.append("  Trending", style=Style(color=theme.FG_DIM))
        proto = img_mod.protocol_name()
        if proto != "block":
            header.append(f"  [{proto}]", style=Style(color=theme.FG_DIM))
        if state.status:
            header.append(f"  {state.status}", style=Style(color=theme.WARNING))

        # ── footer ────────────────────────────────────────────────────────────
        rule = Rule(style=Style(color=theme.BORDER_COLOR))
        player = panels.player_line(
            state.now_playing_episode,
            state.now_playing_podcast_title,
            state.playback_position,
            state.playback_duration,
            state.is_playing,
            width=cols,
        )
        hints = panels.hints_line(search_mode=state.search_mode, query=state.search_query)

        # ── layout ────────────────────────────────────────────────────────────
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=HEADER_HEIGHT),
            Layout(name="main", size=main_height),
            Layout(name="footer", size=FOOTER_HEIGHT),
        )
        layout["footer"].split_column(
            Layout(name="rule", size=1),
            Layout(name="player", size=1),
            Layout(name="hints", size=1),
        )
        layout["header"].update(header)
        layout["main"].update(main_panel)
        layout["rule"].update(rule)
        layout["player"].update(player)
        layout["hints"].update(hints)

        # ── capture to string and write atomically ────────────────────────────
        with console.capture() as cap:
            console.print(layout, end="")
        frame = cap.get()
        # Clip to `rows` lines and join with \r\n.
        # tty.setraw() disables ONLCR so bare \n is LF-only (no CR); each line would
        # start at the column where the previous line ended rather than column 1.
        # Using \r\n guarantees column-1 resets in raw mode.
        # split() on a \n-terminated string produces a trailing empty element;
        # taking [:rows] and joining gives rows-1 \r\n pairs → cursor stays on row rows.
        frame = "\r\n".join(frame.split("\n")[:rows])

        # ── protocol image overlay ────────────────────────────────────────────
        # For protocol images (Kitty/iTerm2/Sixel) the half-block art already in
        # the layout is replaced by a higher-quality overlay at the same position.
        #
        # Position inside the ONE Panel + Table layout:
        #   Row: header(1) + panel-border(1) + table-header(1) + separator(1) + 1-indexed = 5
        #   Col: panel-border(1) + left-pad(1) + left_inner + table-sep(3) + right-pad(1) + 1-idx
        #      = left_inner + 7 = (left_region - 4) + 7 = left_region + 3
        image_overlay = ""
        if img_mod.protocol_name() != "block" and state.cover_image_bytes:
            if state.cover_image_bytes is not self._last_cover:
                self._last_cover = state.cover_image_bytes
                self._image_lines = img_mod.render_frame_lines(
                    state.cover_image_bytes, IMAGE_COLS, IMAGE_ROWS
                )
            if self._image_lines:
                img_row = 5                  # header + panel-border + table-header + separator
                img_col = left_region + 3   # see comment above
                parts = []
                for i, line in enumerate(self._image_lines):
                    parts.append(f"\033[{img_row + i};{img_col}H{line}")
                image_overlay = "".join(parts)

        # ── write everything atomically ───────────────────────────────────────
        sys.stdout.write("\033[2J\033[H\033[?25l" + frame + image_overlay)
        sys.stdout.flush()
