"""Screen renderer — btop-inspired layout.

Two ROUNDED panels side by side (left = podcast cards grid, right = episode list)
with a 1-column gap between them. Below them sits a ROUNDED player panel whose
border colour reacts to playback state. A thin header bar runs across the top.

Image rendering: half-block art is embedded inside each podcast card. No protocol
image overlay is used.
"""
from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass, field

from rich import box as richbox
from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from picast import image as img_mod
from picast.ui import panels, theme

# Thumbnail size inside each podcast card (terminal cells)
CARD_THUMB_W = 10   # terminal cols per thumbnail
CARD_THUMB_H = 5    # terminal rows per thumbnail

# Column split ratios (40% left / 60% right)
LEFT_RATIO = 8
RIGHT_RATIO = 12

HEADER_HEIGHT = 1
PLAYER_HEIGHT = 6   # ╭border╮ + title_line + progress_bar + blank + hints_line + ╰border╯


@dataclass
class RenderState:
    view: str = "home"
    search_mode: bool = False
    search_query: str = ""

    podcasts: list[dict] = field(default_factory=list)
    podcast_cursor: int = 0
    following_ids: set[int] = field(default_factory=set)
    following_count: int = 0

    episodes: list[dict] = field(default_factory=list)
    episode_cursor: int = 0
    episode_statuses: dict[int, str] = field(default_factory=dict)

    selected_podcast: dict | None = None
    cover_images: dict[int, bytes] = field(default_factory=dict)   # podcast_id → image bytes
    episodes_for_pod: int | None = None   # feed_id whose episodes are in state.episodes
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
        self._console_theme_name: str = ""
        self._half_block_cache: dict[int, list[str]] = {}
        # pid → (img_bytes_ref, preencoded_escape_sequence)
        self._img_seq_cache: dict[int, tuple[bytes, str]] = {}
        self._lock = threading.Lock()   # guards render() vs exit_screen() stdout race
        self._exiting = False
        self._thumb_dims: tuple[int, int] | None = None
        # Tracks Kitty images currently on screen: pid → (term_row, term_col, img_bytes)
        # Used to avoid ESC[2J per-frame clears that cause flicker on Ghostty.
        self._displayed_kitty: dict[int, tuple[int, int, bytes]] = {}
        self._prev_frame_size: tuple[int, int] = (0, 0)

    def _thumb_cells(self) -> tuple[int, int]:
        """Largest cell box that renders the cover *square* in pixels, within the card.

        Terminal cells are typically ~2× taller than wide, so a CARD_THUMB_W×
        CARD_THUMB_H box stretches a square image. We derive the box from the actual
        cell pixel size: pick the dimensions whose pixel extents are closest to equal
        while fitting inside CARD_THUMB_W × CARD_THUMB_H. Cached — cell size is stable
        within a session.
        """
        if self._thumb_dims is None:
            cell_w, cell_h = img_mod.cell_pixels()
            cols = CARD_THUMB_W
            rows = max(1, round(cols * cell_w / cell_h))
            if rows > CARD_THUMB_H:
                rows = CARD_THUMB_H
                cols = max(1, min(CARD_THUMB_W, round(rows * cell_h / cell_w)))
            self._thumb_dims = (cols, rows)
        return self._thumb_dims

    def preprocess_image(self, pid: int, image_bytes: bytes) -> None:
        """Pre-encode image data in a background thread so renders never touch PIL."""
        cols, rows = self._thumb_cells()
        proto = img_mod.protocol_name()
        if proto in ("kitty", "iterm2", "sixel"):
            # Pre-encode the full escape sequence so _render_impl is PIL-free.
            existing = self._img_seq_cache.get(pid)
            if existing is None or existing[0] is not image_bytes:
                lines = img_mod.render_frame_lines(
                    image_bytes, cols, rows, kitty_id=pid
                )
                if lines:
                    self._img_seq_cache[pid] = (image_bytes, lines[0])
                else:
                    # Protocol encoding failed (e.g. unsupported image format) —
                    # fall back to half-block so the card shows something.
                    hb = img_mod.render_half_block_lines(image_bytes, cols, rows)
                    self._half_block_cache[pid] = self._pad_block(hb, cols, rows)
        else:
            if pid not in self._half_block_cache:
                lines = img_mod.render_half_block_lines(image_bytes, cols, rows)
                self._half_block_cache[pid] = self._pad_block(lines, cols, rows)

    @staticmethod
    def _pad_block(lines: list[str], cols: int, rows: int) -> list[str]:
        """Center half-block art (cols×rows) inside the CARD_THUMB_W×CARD_THUMB_H box."""
        if not lines:
            return lines
        col_off = (CARD_THUMB_W - cols) // 2
        row_off = (CARD_THUMB_H - rows) // 2
        pad_left = " " * col_off
        blank = " " * CARD_THUMB_W
        out = [blank] * row_off + [pad_left + ln for ln in lines]
        while len(out) < CARD_THUMB_H:
            out.append(blank)
        return out[:CARD_THUMB_H]

    def _get_console(self, cols: int, rows: int) -> Console:
        active_theme = theme.get_theme_name()
        if (cols, rows) != self._console_size or active_theme != self._console_theme_name:
            self._console_size = (cols, rows)
            self._console_theme_name = active_theme
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
        with self._lock:
            self._exiting = True
        sys.stdout.write("\033[?2026l")           # close any open BSU
        sys.stdout.write("\033[0m")               # reset SGR (colors, bold, etc.)
        if img_mod.protocol_name() == "kitty":
            sys.stdout.write("\033_Ga=d,d=a,q=2\033\\")  # delete all Kitty images
            self._img_seq_cache.clear()
            self._displayed_kitty.clear()
        sys.stdout.write("\033[2J\033[H")         # clear alternate screen
        sys.stdout.write("\033[?1049l")           # restore main screen
        sys.stdout.write("\033[?25h")             # show cursor (after screen restore)
        sys.stdout.write("\033[0m")               # reset SGR on main screen
        sys.stdout.flush()

    def render(self, state: RenderState) -> None:
        with self._lock:
            if self._exiting:
                return
            self._render_impl(state)

    def _render_impl(self, state: RenderState) -> None:
        try:
            sz = os.get_terminal_size()
            cols, rows = sz.columns, sz.lines
        except OSError:
            cols, rows = 80, 24

        if cols < 40 or rows < 12:
            return

        console = self._get_console(cols, rows)
        main_height = max(6, rows - HEADER_HEIGHT - PLAYER_HEIGHT)

        left_allocated = (cols - 1) * LEFT_RATIO // (LEFT_RATIO + RIGHT_RATIO)
        left_inner = left_allocated - 4   # ROUNDED borders(2) + padding each side(2)
        right_allocated = (cols - 1) - left_allocated
        right_inner = right_allocated - 4  # ROUNDED borders(2) + padding each side(2)
        list_height = main_height - 2    # ROUNDED panel top + bottom borders

        # ── image cache update ────────────────────────────────────────────────
        use_protocol = img_mod.protocol_name() in ("kitty", "iterm2", "sixel")
        current_ids = {p.get("id", 0) for p in state.podcasts}

        # Half-block cache is pre-populated by preprocess_image(); evict stale entries.
        for stale_id in [k for k in self._half_block_cache if k not in current_ids]:
            del self._half_block_cache[stale_id]

        # Protocol-active cards get blank placeholder cells; the image is overlaid after.
        # Exception: podcasts where protocol encoding failed use a half-block fallback
        # rendered directly in the card (they won't appear in the Kitty overlay loop).
        if use_protocol:
            display_images = {
                pid: lines for pid, lines in self._half_block_cache.items()
                if pid in current_ids
            }
        else:
            display_images = self._half_block_cache

        # ── left panel content (podcast cards) ───────────────────────────────
        import time as _time
        now = int(_time.time())
        now_playing_feed_id = None
        if state.now_playing_episode and state.selected_podcast:
            now_playing_feed_id = state.selected_podcast.get("id")

        left_content = panels.podcast_cards_content(
            podcasts=state.podcasts,
            cursor=state.podcast_cursor,
            following_ids=state.following_ids,
            half_block_images=display_images,
            thumb_w=CARD_THUMB_W,
            thumb_h=CARD_THUMB_H,
            total_width=left_inner,
            height=list_height,
            now_playing_feed_id=now_playing_feed_id,
            view=state.view,
        )

        if state.view == "following":
            left_panel_title = f"[bold {theme.ACCENT}]Following[/]"
        elif state.view == "search":
            left_panel_title = f"[{theme.FG_DIM}]Search Results[/]"
        elif state.following_count > 0:
            left_panel_title = f"[bold {theme.ACCENT}]Following[/]"
        else:
            left_panel_title = f"[{theme.FG_DIM}]Trending[/]"

        left_panel = Panel(
            left_content,
            title=left_panel_title,
            title_align="left",
            border_style=theme.ACCENT_DIM if state.view != "podcast" else theme.BORDER_COLOR,
            box=richbox.ROUNDED,
            padding=(0, 1),
        )

        # ── right panel title ─────────────────────────────────────────────────
        if state.selected_podcast:
            pod_name = state.selected_podcast.get("title", "")
            if len(pod_name) > 80:
                pod_name = pod_name[:77] + "…"
            detail_panel_title = f"[bold {theme.FG}]{pod_name}[/]"
        else:
            detail_panel_title = f"[{theme.FG_DIM}]Episodes[/]"

        # ── right panel content (episode list) ───────────────────────────────
        playing_ep_id = (
            state.now_playing_episode.get("id") if state.now_playing_episode else None
        )
        right_content = panels.episode_list_content(
            state.episodes,
            state.episode_cursor,
            state.episode_statuses,
            playing_episode_id=playing_ep_id,
            height=list_height,
            has_focus=state.view == "podcast",
            width=right_inner - 2,  # minus the 2-col status-dot column
        )

        right_panel = Panel(
            right_content,
            title=detail_panel_title,
            title_align="left",
            border_style=theme.ACCENT_DIM if state.view == "podcast" else theme.DETAIL_BORDER,
            box=richbox.ROUNDED,
            padding=(0, 1),
        )

        # ── player panel ──────────────────────────────────────────────────────
        player_group = panels.player_content(
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
            Group(player_group, Text(""), hints),
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
        if state.now_playing_episode:
            ep_icon = theme.PLAYING_ICON if state.is_playing else theme.PAUSED_ICON
            ep_title = state.now_playing_episode.get("title", "")[:45]
            header.append("   │   ", style=Style(color=theme.BORDER_COLOR))
            header.append(f"{ep_icon} ", style=Style(color=theme.PLAYING_COLOR, bold=True))
            header.append(ep_title, style=Style(color=theme.FG_DIM))

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
        frame = "\r\n".join(cap.get().split("\n")[:rows])

        # ── protocol image overlay for card thumbnails ────────────────────────
        proto_name = img_mod.protocol_name()

        # On terminal resize, re-transmit all Kitty images at updated positions.
        # We don't clear _img_seq_cache here because preprocess_image is only called
        # on image fetch, so clearing would leave images blank with no async re-trigger.
        if (cols, rows) != self._prev_frame_size:
            self._prev_frame_size = (cols, rows)
            self._thumb_dims = None  # force cell-size ratio recompute
            self._displayed_kitty.clear()  # force re-transmit at new positions

        delete_seqs = ""
        image_overlay = ""
        if use_protocol and state.podcasts:
            card_height = CARD_THUMB_H + 2   # border-top + thumb_h rows + border-bottom
            visible_rows = max(1, list_height // card_height)
            total_rows = len(state.podcasts)
            start_row = max(0, min(total_rows - visible_rows, state.podcast_cursor - visible_rows // 2))
            # Square image dims may be smaller than the card box — center within it.
            img_cols, img_rows = self._thumb_cells()
            row_off = (CARD_THUMB_H - img_rows) // 2
            col_off = (CARD_THUMB_W - img_cols) // 2

            # Compute the desired image positions for this frame.
            desired: dict[int, tuple[int, int, bytes]] = {}
            for vr in range(visible_rows):
                pod_idx = start_row + vr
                if pod_idx >= len(state.podcasts):
                    continue
                pid = state.podcasts[pod_idx].get("id", 0)
                img_bytes = state.cover_images.get(pid)
                if not img_bytes:
                    continue
                cached = self._img_seq_cache.get(pid)
                if not (cached and cached[0] is img_bytes):
                    continue  # PIL not done yet — skip; next render will pick it up
                # Terminal position: row 1=header, row 2=panel border, row 3=panel content.
                # Card top border at row 3 + vr*card_height → thumbnail at +1, then center.
                term_row = HEADER_HEIGHT + vr * card_height + 3 + row_off
                # Column: panel border(1) + panel padding(1) + card border(1) + 1-indexed = 4
                term_col = 4 + col_off
                desired[pid] = (term_row, term_col, img_bytes)

            if proto_name == "kitty":
                # Targeted deletes for images that moved, changed, or scrolled off.
                # This avoids ESC[2J which wipes all Kitty images and causes a blank-
                # screen flash every frame on Ghostty (which honours the spec strictly).
                for pid, old_info in self._displayed_kitty.items():
                    if desired.get(pid) != old_info:
                        delete_seqs += f"\033_Ga=d,d=i,i={pid},q=2\033\\"
                # Transmit only images that are new or have moved/changed.
                for pid, (term_row, term_col, img_bytes) in desired.items():
                    if self._displayed_kitty.get(pid) != (term_row, term_col, img_bytes):
                        image_overlay += f"\033[{term_row};{term_col}H" + self._img_seq_cache[pid][1]
                self._displayed_kitty = dict(desired)
            else:
                # iTerm2 / sixel: re-transmit every frame (simpler; ESC[2J doesn't
                # carry the same image-deletion behaviour as Ghostty's Kitty impl).
                for pid, (term_row, term_col, img_bytes) in desired.items():
                    image_overlay += f"\033[{term_row};{term_col}H" + self._img_seq_cache[pid][1]

        # For Kitty we skip ESC[2J to preserve images not deleted above — the Rich
        # frame fully overwrites the text layer starting from ESC[H, so no stale
        # text survives. Other protocols keep the traditional full-screen clear.
        if proto_name == "kitty":
            screen_init = "\033[H\033[?25l"
        else:
            screen_init = "\033[2J\033[H\033[?25l"

        sys.stdout.write(
            "\033[?2026h"
            + delete_seqs
            + screen_init
            + frame
            + image_overlay
            + "\033[?2026l"
        )
        sys.stdout.flush()
