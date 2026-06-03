"""Rich renderable builders for each UI panel."""
from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Group
from rich.style import Style
from rich.table import Table
from rich.text import Text

from picast import image as img_mod
from picast.ui.theme import (
    ACCENT,
    BG_SELECT,
    BORDER_COLOR,
    DONE_COLOR,
    DONE_ICON,
    FG,
    FG_DIM,
    FOLLOW_ICON,
    NEW_COLOR,
    NEW_ICON,
    PAUSED_ICON,
    PLAYING_COLOR,
    PLAYING_ICON,
    STARTED_COLOR,
    STARTED_ICON,
    UNFOLLOW_ICON,
)


def _fmt_dur(seconds: int) -> str:
    if not seconds:
        return ""
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    return f"{h}h{m:02d}m" if h else f"{m}:{s:02d}"


def _fmt_date(ts: int) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%b %d")
    except Exception:
        return ""


def _status_icon(status: str) -> tuple[str, str]:
    return {
        "started": (STARTED_ICON, STARTED_COLOR),
        "completed": (DONE_ICON, DONE_COLOR),
    }.get(status, (NEW_ICON, NEW_COLOR))


# ── podcast list ──────────────────────────────────────────────────────────────

def podcast_list_content(
    podcasts: list[dict],
    cursor: int,
    following_ids: set[int],
    playing_feed_id: int | None,
    height: int = 20,
    width: int = 30,
    following_count: int = 0,
) -> Table:
    table = Table.grid(padding=(0, 0))
    table.add_column(width=1)
    table.add_column(max_width=width - 2, no_wrap=True)

    # Build a flat display list interleaving section headers with podcast rows.
    # Each entry: ("header", label, style) or ("podcast", podcast_dict, logical_idx)
    display: list[tuple] = []
    has_following = following_count > 0 and len(podcasts) >= following_count
    has_trending = len(podcasts) > following_count

    if has_following:
        display.append(("header", "Following", Style(color=ACCENT, bold=True)))
        for li in range(following_count):
            display.append(("podcast", podcasts[li], li))
    if has_trending:
        display.append(("header", "Trending", Style(color=FG_DIM, italic=True)))
        for li in range(following_count, len(podcasts)):
            display.append(("podcast", podcasts[li], li))
    if not display:
        for li, p in enumerate(podcasts):
            display.append(("podcast", p, li))

    if not display:
        table.add_row("", Text("No podcasts", style=Style(color=FG_DIM, italic=True)))
        return table

    # Find the visual index of the cursor so we can center the window on it.
    visual_cursor = 0
    for vi, entry in enumerate(display):
        if entry[0] == "podcast" and entry[2] == cursor:
            visual_cursor = vi
            break

    visual_start = max(0, visual_cursor - height // 2)
    visible = display[visual_start: visual_start + height]

    for entry in visible:
        if entry[0] == "header":
            _, label, hstyle = entry
            icon = FOLLOW_ICON if label == "Following" else " "
            icon_style = Style(color=ACCENT, bold=True) if label == "Following" else Style()
            table.add_row(Text(icon, style=icon_style), Text(label, style=hstyle))
        else:
            _, p, li = entry
            is_selected = li == cursor
            feed_id = p.get("id", 0)
            is_followed = feed_id in following_ids

            icon = FOLLOW_ICON if is_followed else " "
            icon_style = Style(color=ACCENT) if is_followed else Style(color=FG_DIM)
            name = p.get("title", f"Feed {feed_id}")
            row_style = Style(bgcolor=BG_SELECT) if is_selected else Style()
            name_style = Style(color=FG, bold=True) if is_selected else Style(color=FG)

            table.add_row(
                Text(icon, style=icon_style),
                Text(name, style=name_style, overflow="ellipsis", no_wrap=True),
                style=row_style,
            )

    return table


# ── episode list ──────────────────────────────────────────────────────────────

def episode_list_content(
    episodes: list[dict],
    cursor: int,
    episode_statuses: dict[int, str],
    playing_episode_id: int | None,
    height: int = 20,
) -> Table:
    table = Table.grid(padding=(0, 0))
    table.add_column(width=1)
    table.add_column()
    table.add_column(width=6, justify="right")
    table.add_column(width=6, justify="right")

    visible_start = max(0, cursor - height // 2)
    visible = episodes[visible_start: visible_start + height]

    for i, ep in enumerate(visible):
        idx = visible_start + i
        ep_id = ep.get("id", 0)
        is_selected = idx == cursor
        is_playing = ep_id == playing_episode_id
        status = episode_statuses.get(ep_id, "new")

        dot, dot_color = _status_icon(status)
        if is_playing:
            dot = PLAYING_ICON
            dot_color = PLAYING_COLOR

        title = ep.get("title", f"Episode {ep_id}")
        date_str = _fmt_date(ep.get("datePublished", 0))
        dur_str = _fmt_dur(ep.get("duration", 0))

        row_style = Style(bgcolor=BG_SELECT) if is_selected else Style()
        title_style = Style(color=FG, bold=True) if is_selected else Style(color=FG)

        table.add_row(
            Text(dot, style=Style(color=dot_color)),
            Text(title, style=title_style, overflow="ellipsis", no_wrap=True),
            Text(date_str, style=Style(color=FG_DIM)),
            Text(dur_str, style=Style(color=FG_DIM)),
            style=row_style,
        )

    if not episodes:
        table.add_row("", Text("No episodes", style=Style(color=FG_DIM, italic=True)), "", "")

    return table


# ── detail content ────────────────────────────────────────────────────────────

def detail_content(
    podcast: dict | None,
    image_bytes: bytes | None,
    image_cols: int,
    image_rows: int,
    is_following: bool = False,
    loading: bool = False,
) -> Group:
    lines: list[object] = []

    if image_bytes:
        raw_lines = img_mod.render_half_block_lines(image_bytes, image_cols, image_rows)
        for raw in raw_lines:
            lines.append(Text.from_ansi(raw))
    else:
        for _ in range(image_rows):
            lines.append(Text(" " * image_cols, style=Style(color=FG_DIM)))

    lines.append(Text(""))

    if podcast is None:
        lines.append(Text("Select a podcast", style=Style(color=FG_DIM, italic=True)))
        return Group(*lines)

    title = podcast.get("title", "")
    author = podcast.get("author", "")
    description = (podcast.get("description", "") or "").strip()

    lines.append(Text(title, style=Style(color=FG, bold=True), overflow="fold"))
    if author:
        lines.append(Text(author, style=Style(color=FG_DIM, italic=True), overflow="fold"))

    follow_label = f" {FOLLOW_ICON} Following" if is_following else f" {UNFOLLOW_ICON} Follow [f]"
    lines.append(Text(follow_label, style=Style(color=ACCENT if is_following else FG_DIM)))
    lines.append(Text("─" * image_cols, style=Style(color=BORDER_COLOR)))

    if loading:
        lines.append(Text("Loading…", style=Style(color=FG_DIM, italic=True)))
    elif description:
        if len(description) > 400:
            description = description[:397] + "…"
        lines.append(Text(description, style=Style(color=FG_DIM), overflow="fold"))

    return Group(*lines)


# ── player line ───────────────────────────────────────────────────────────────

def player_line(
    episode: dict | None,
    podcast_title: str,
    position: float,
    duration: float,
    is_playing: bool,
    width: int,
) -> Text:
    if episode is None:
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append("  No media playing", style=Style(color=FG_DIM))
        return t

    icon = PLAYING_ICON if is_playing else PAUSED_ICON
    title = episode.get("title", "")
    pos_str = _fmt_dur(int(position)) or "0:00"
    dur_str = _fmt_dur(int(duration)) if duration else "?:??"

    bar_width = max(10, width - 50)
    frac = min(1.0, position / duration) if duration > 0 else 0.0
    filled = int(frac * bar_width)
    bar = "█" * filled + "░" * (bar_width - filled)

    t = Text(no_wrap=True, overflow="ellipsis")
    t.append(f" {icon} ", style=Style(color=PLAYING_COLOR, bold=True))
    if podcast_title:
        t.append(f"{podcast_title}  ", style=Style(color=FG_DIM))
    t.append(title, style=Style(color=FG))
    t.append(f"  {pos_str} ", style=Style(color=FG_DIM))
    t.append(bar, style=Style(color=ACCENT))
    t.append(f" {dur_str}", style=Style(color=FG_DIM))
    return t


# ── hints line ────────────────────────────────────────────────────────────────

def hints_line(search_mode: bool = False, query: str = "") -> Text:
    t = Text(no_wrap=True, overflow="ellipsis")
    if search_mode:
        t.append(" / ", style=Style(color=ACCENT, bold=True))
        t.append(query, style=Style(color=FG))
        t.append("█", style=Style(color=ACCENT))
        t.append("  Enter=search  Esc=cancel", style=Style(color=FG_DIM))
    else:
        t.append(
            "  j/k navigate · Enter select · Space play · ←→ seek · / search"
            " · f follow · Tab toggle · q quit",
            style=Style(color=FG_DIM),
        )
    return t
