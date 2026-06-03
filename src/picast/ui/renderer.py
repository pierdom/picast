"""Screen renderer — btop-inspired layout.

Two ROUNDED panels side by side (left = list, right = details) with a
1-column gap between them, giving the ╮ ╭ junction btop uses. Below
them sits a ROUNDED player panel whose border colour reacts to playback
state. A thin header bar runs across the top.

Image rendering: half-block art is embedded in the right panel content;
for Kitty/iTerm2/Sixel terminals an escape-code overlay is written over
the same cell area after the frame for higher quality.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from rich import box as richbox
from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from picast import image as img_mod
from picast.ui import panels, theme

# Image area (terminal cells)
IMAGE_COLS = 22
IMAGE_ROWS = 11   # half-block: 2 px/row → 22×22 px block

# Column split ratios
LEFT_RATIO = 2
RIGHT_RATIO = 3

HEADER_HEIGHT = 1
PLAYER_HEIGHT = 4   # ╭border╮ + player_line + hints_line + ╰border╯


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

        if cols < 40 or rows < 12:
            return

        console = self._get_console(cols, rows)
        main_height = max(6, rows - HEADER_HEIGHT - PLAYER_HEIGHT)

        # left_allocated: columns given to the left Layout section (includes panel borders).
        # A 1-column gap sits between the two panels → subtract 1 from available width.
        left_allocated = (cols - 1) * LEFT_RATIO // (LEFT_RATIO + RIGHT_RATIO)
        left_inner = left_allocated - 4   # ROUNDED borders(2) + padding each side(2)
        list_height = main_height - 2    # ROUNDED panel top + bottom borders

        # ── left panel (podcast / episode list) ───────────────────────────────
        if state.view in ("home", "following"):
            if state.view == "following":
                list_panel_title = f"[bold {theme.ACCENT}]★ Following[/]"
            elif state.following_count > 0:
                list_panel_title = f"[bold {theme.ACCENT}]★ Podcasts[/]"
            else:
                list_panel_title = f"[{theme.FG_DIM}]Trending[/]"
            left_content = panels.podcast_list_content(
                state.podcasts, state.podcast_cursor, state.following_ids,
                playing_feed_id=None, height=list_height, width=left_inner,
                following_count=state.following_count if state.view == "home" else 0,
            )
        else:
            playing_ep_id = (
                state.now_playing_episode.get("id") if state.now_playing_episode else None
            )
            list_panel_title = f"[bold {theme.ACCENT}]◎ Episodes[/]"
            left_content = panels.episode_list_content(
                state.episodes, state.episode_cursor, state.episode_statuses,
                playing_episode_id=playing_ep_id, height=list_height,
            )

        left_panel = Panel(
            left_content,
            title=list_panel_title,
            title_align="left",
            border_style=theme.ACCENT_DIM,
            box=richbox.ROUNDED,
            padding=(0, 1),
        )

        # ── right panel (cover art + podcast detail) ──────────────────────────
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
        if state.selected_podcast:
            pod_name = state.selected_podcast.get("title", "")
            if len(pod_name) > 42:
                pod_name = pod_name[:39] + "…"
            detail_panel_title = f"[bold {theme.FG}]{pod_name}[/]"
        else:
            detail_panel_title = f"[{theme.FG_DIM}]Details[/]"

        right_panel = Panel(
            right_content,
            title=detail_panel_title,
            title_align="left",
            border_style=theme.DETAIL_BORDER,
            box=richbox.ROUNDED,
            padding=(0, 1),
        )

        # ── player panel (playback + hints; border changes with state) ────────
        player_line = panels.player_line(
            state.now_playing_episode,
            state.now_playing_podcast_title,
            state.playback_position,
            state.playback_duration,
            state.is_playing,
            width=cols,
        )
        hints = panels.hints_line(search_mode=state.search_mode, query=state.search_query)

        if state.now_playing_episode:
            if state.is_playing:
                player_border = theme.PLAYING_COLOR
                player_title = f"[bold {theme.PLAYING_COLOR}]▶ Now Playing[/]"
            else:
                player_border = theme.ACCENT_DIM
                player_title = f"[bold {theme.ACCENT_DIM}]⏸ Paused[/]"
        else:
            player_border = theme.BORDER_COLOR
            player_title = f"[{theme.FG_DIM}]Player[/]"

        player_panel = Panel(
            Group(player_line, hints),
            title=player_title,
            title_align="left",
            border_style=player_border,
            box=richbox.ROUNDED,
            padding=(0, 1),
        )

        # ── header bar ────────────────────────────────────────────────────────
        header = Text(no_wrap=True)
        badge = Style(bold=True, color="#ffffff", bgcolor=theme.ACCENT_DIM)
        header.append(" ▶ picast ", style=badge)
        header.append("  ", style=Style())

        if state.view == "following":
            header.append("Following", style=Style(color=theme.ACCENT, bold=True))
        elif state.view == "podcast" and state.selected_podcast:
            header.append(
                state.selected_podcast.get("title", "")[:50],
                style=Style(color=theme.FG_DIM, italic=True),
            )
        elif state.following_count > 0:
            header.append("Podcasts", style=Style(color=theme.FG_DIM))
        else:
            header.append("Trending", style=Style(color=theme.FG_DIM))

        if state.now_playing_episode:
            ep_icon = theme.PLAYING_ICON if state.is_playing else theme.PAUSED_ICON
            ep_title = state.now_playing_episode.get("title", "")[:45]
            header.append("   │   ", style=Style(color=theme.BORDER_COLOR))
            header.append(f"{ep_icon} ", style=Style(color=theme.PLAYING_COLOR, bold=True))
            header.append(ep_title, style=Style(color=theme.FG_DIM))

        proto = img_mod.protocol_name()
        if proto != "block":
            header.append(f"  [{proto}]", style=Style(color=theme.FG_DIM))
        if state.status:
            header.append(f"  {state.status}", style=Style(color=theme.WARNING))

        # ── assemble layout ───────────────────────────────────────────────────
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=HEADER_HEIGHT),
            Layout(name="main", size=main_height),
            Layout(name="player", size=PLAYER_HEIGHT),
        )
        layout["main"].split_row(
            Layout(name="left", ratio=LEFT_RATIO),
            Layout(name="gap", size=1),
            Layout(name="right", ratio=RIGHT_RATIO),
        )

        layout["header"].update(header)
        layout["left"].update(left_panel)
        layout["gap"].update(Text(""))
        layout["right"].update(right_panel)
        layout["player"].update(player_panel)

        # ── capture to string and write atomically ────────────────────────────
        with console.capture() as cap:
            console.print(layout, end="")
        # \r\n: tty.setraw() disables ONLCR so bare \n is LF-only; \r\n guarantees
        # column-1 reset. Clip to rows lines so cursor never advances past last row.
        frame = "\r\n".join(cap.get().split("\n")[:rows])

        # ── protocol image overlay ────────────────────────────────────────────
        # Layout: header(1) │ main: [left_allocated | gap(1) | right] │ player(4)
        #   img_row = header(1) + right-panel-top-border(1) + 1-indexed = HEADER_HEIGHT + 2
        #   img_col = left_allocated + gap(1) + right-border(1) + right-padding(1) + 1-indexed
        #           = left_allocated + 4
        image_overlay = ""
        if img_mod.protocol_name() != "block" and state.cover_image_bytes:
            if state.cover_image_bytes is not self._last_cover:
                self._last_cover = state.cover_image_bytes
                self._image_lines = img_mod.render_frame_lines(
                    state.cover_image_bytes, IMAGE_COLS, IMAGE_ROWS
                )
            if self._image_lines:
                img_row = HEADER_HEIGHT + 2
                img_col = left_allocated + 4
                parts = []
                for i, line in enumerate(self._image_lines):
                    parts.append(f"\033[{img_row + i};{img_col}H{line}")
                image_overlay = "".join(parts)

        # ── write frame + overlay atomically ──────────────────────────────────
        sys.stdout.write("\033[2J\033[H\033[?25l" + frame + image_overlay)
        sys.stdout.flush()
