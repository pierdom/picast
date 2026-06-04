"""Rich renderable builders for each UI panel."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from rich import box as richbox
from rich.console import Group
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text

from picast.ui.theme import (
    ACCENT,
    ACCENT_DIM,
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

_NEW_EPISODE_SECS = 7 * 86400  # 7 days → show NEW badge


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


# ── podcast card (2-column grid) ──────────────────────────────────────────────

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return " ".join(_HTML_TAG_RE.sub(" ", text).split())


def _word_wrap(text: str, width: int, max_lines: int) -> list[str]:
    """Wrap text to width, returning at most max_lines lines."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        if not current:
            current = word[:width]
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            if len(lines) >= max_lines:
                return lines
            current = word[:width]
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def _podcast_card(
    podcast: dict,
    image_lines: list[str],
    thumb_w: int,
    thumb_h: int,
    card_w: int,
    is_selected: bool,
    is_following: bool,
    now: int,
    is_playing: bool,
) -> Panel:
    """Build a single podcast card Panel.

    Layout (card_height = thumb_h + 4):
      ╭─────────────────────────────────────────╮
      │ [img row 0] Title                    ★  │
      │ [img row 1] Author                       │
      │ [img row 2] Description line 1           │
      │ [img row 3] Description line 2           │
      │ [img row 4] Description line 3           │
      │             Jun 04  ·  45 ep  ● NEW      │
      │             ▶ Play                       │
      ╰─────────────────────────────────────────╯
    """
    # card border(1 each side) + no panel padding → inner width = card_w - 2
    text_w = max(1, card_w - thumb_w - 1 - 2)  # thumb + gap(1) + borders(2)

    title = podcast.get("title", "")
    author = podcast.get("author", "") or ""
    pub_ts = podcast.get("newestItemPubdate", 0) or 0
    ep_count = podcast.get("episodeCount", 0) or 0
    raw_desc = (podcast.get("description", "") or "").strip()
    description = _strip_html(raw_desc)

    # Row 0: title (+ star if following)
    title_text = Text(no_wrap=True, overflow="ellipsis")
    if is_following:
        max_title = max(1, text_w - 2)
        truncated = title[:max_title] if len(title) > max_title else title
        title_text.append(truncated, style=Style(color=FG, bold=True))
        remaining = text_w - len(truncated)
        if remaining > 1:
            title_text.append(" " * (remaining - 1))
            title_text.append("★", style=Style(color=ACCENT))
    else:
        title_text.append(title, style=Style(color=FG, bold=True))

    # Row 1: author
    author_text = Text(
        (author[:text_w] if len(author) > text_w else author) or " ",
        style=Style(color=FG_DIM, italic=True),
        no_wrap=True,
        overflow="ellipsis",
    )

    # Rows 2 … thumb_h-1: description (word-wrapped)
    desc_row_count = max(0, thumb_h - 2)
    desc_lines_raw = _word_wrap(description, text_w, desc_row_count) if description else []
    while len(desc_lines_raw) < desc_row_count:
        desc_lines_raw.append("")
    desc_texts = [
        Text(ln, style=Style(color=FG_DIM), no_wrap=True, overflow="ellipsis")
        for ln in desc_lines_raw
    ]

    text_lines: list[Text] = [title_text, author_text] + desc_texts

    # Build inner grid: [thumbnail | gap | text] × thumb_h rows
    grid = Table.grid(padding=0)
    grid.add_column(width=thumb_w)
    grid.add_column(width=1)
    grid.add_column(width=text_w)

    for i in range(thumb_h):
        img_cell: object
        if image_lines and i < len(image_lines):
            img_cell = Text.from_ansi(image_lines[i])
        else:
            img_cell = Text(" " * thumb_w)
        grid.add_row(img_cell, Text(""), text_lines[i] if i < len(text_lines) else Text(""))

    # Meta row (below image): date · ep count  ● NEW
    parts: list[str] = []
    if pub_ts:
        parts.append(_fmt_date(pub_ts))
    if ep_count:
        parts.append(f"{ep_count} ep")
    meta_t = Text(no_wrap=True, overflow="ellipsis")
    meta_t.append("  ·  ".join(parts) if parts else "", style=Style(color=FG_DIM))
    if pub_ts and (now - pub_ts) < _NEW_EPISODE_SECS:
        meta_t.append("  ● NEW", style=Style(color=NEW_COLOR, bold=True))
    grid.add_row(Text(" " * thumb_w), Text(""), meta_t)

    # Play row
    if is_playing:
        play_t = Text("▶ Playing", style=Style(color=PLAYING_COLOR, bold=True))
    else:
        play_t = Text("  Play", style=Style(color=FG_DIM))
    grid.add_row(Text(" " * thumb_w), Text(""), play_t)

    if is_playing:
        border_style = PLAYING_COLOR
    elif is_selected:
        border_style = ACCENT
    else:
        border_style = BORDER_COLOR

    return Panel(grid, box=richbox.ROUNDED, padding=(0, 0), border_style=border_style)


def podcast_cards_content(
    podcasts: list[dict],
    cursor: int,
    following_ids: set[int],
    half_block_images: dict[int, list[str]],
    thumb_w: int,
    thumb_h: int,
    total_width: int,
    height: int,
    now_playing_feed_id: int | None,
    view: str,
) -> Group:
    """Render podcasts as a 2-column card grid."""
    if not podcasts:
        return Group(
            Text(
                "No podcasts. Press / to search.",
                style=Style(color=FG_DIM, italic=True),
            )
        )

    now = int(time.time())

    # Card sizing: two columns with a 1-col gap
    card_w = max(10, (total_width - 1) // 2)
    right_card_w = max(10, total_width - card_w - 1)

    # Card height: ROUNDED border top+bottom (2) + thumb_h rows + 1 meta row + 1 play row = thumb_h + 4
    card_height = thumb_h + 4

    # Visible rows based on available height
    visible_rows = max(1, height // card_height)

    # Scroll: keep cursor row centred
    cursor_row = cursor // 2
    total_rows = (len(podcasts) + 1) // 2
    start_row = max(0, min(total_rows - visible_rows, cursor_row - visible_rows // 2))

    # Determine focus: when view == "podcast" the card grid is not the active panel
    cards_focused = view not in ("podcast",)

    # Outer grid: left_card | gap | right_card
    outer = Table.grid(padding=0)
    outer.add_column(width=card_w)
    outer.add_column(width=1)
    outer.add_column(width=right_card_w)

    for row_idx in range(start_row, start_row + visible_rows):
        left_idx = row_idx * 2
        right_idx = left_idx + 1

        # Left card
        if left_idx < len(podcasts):
            p_left = podcasts[left_idx]
            pid_left = p_left.get("id", 0)
            left_card: object = _podcast_card(
                podcast=p_left,
                image_lines=half_block_images.get(pid_left, []),
                thumb_w=thumb_w,
                thumb_h=thumb_h,
                card_w=card_w,
                is_selected=cards_focused and left_idx == cursor,
                is_following=pid_left in following_ids,
                now=now,
                is_playing=pid_left == now_playing_feed_id,
            )
        else:
            left_card = Text("")

        # Right card
        if right_idx < len(podcasts):
            p_right = podcasts[right_idx]
            pid_right = p_right.get("id", 0)
            right_card: object = _podcast_card(
                podcast=p_right,
                image_lines=half_block_images.get(pid_right, []),
                thumb_w=thumb_w,
                thumb_h=thumb_h,
                card_w=right_card_w,
                is_selected=cards_focused and right_idx == cursor,
                is_following=pid_right in following_ids,
                now=now,
                is_playing=pid_right == now_playing_feed_id,
            )
        else:
            right_card = Text("")

        outer.add_row(left_card, Text(""), right_card)

    return Group(outer)


# ── podcast list (legacy — kept for compatibility) ─────────────────────────────

def podcast_list_content(
    podcasts: list[dict],
    cursor: int,
    following_ids: set[int],
    playing_feed_id: int | None,
    height: int = 20,
    width: int = 30,
    following_count: int = 0,
) -> Table:
    now = int(time.time())

    # icon(1) · name(expanding) · badge(4)
    badge_w = 4
    table = Table.grid(padding=(0, 0))
    table.add_column(width=1)
    table.add_column(max_width=max(1, width - 1 - badge_w), no_wrap=True)
    table.add_column(width=badge_w)

    display: list[tuple] = []

    if following_count > 0 and len(podcasts) > 0:
        display.append(("following_header", None, -1))
        for li in range(min(following_count, len(podcasts))):
            p = podcasts[li]
            display.append(("podcast", p, li))
            pub_ts = p.get("newestItemPubdate", 0) or 0
            ep_count = p.get("episodeCount", 0) or 0
            if pub_ts or ep_count:
                display.append(("podcast_sub", p, li))
        if len(podcasts) > following_count:
            display.append(("spacer", None, -1))
            display.append(("trending_header", None, -1))
            for li in range(following_count, len(podcasts)):
                display.append(("podcast", podcasts[li], li))
    else:
        for li, p in enumerate(podcasts):
            display.append(("podcast", p, li))

    if not display:
        table.add_row("", Text("No podcasts", style=Style(color=FG_DIM, italic=True)), "")
        return table

    visual_cursor = 0
    for vi, entry in enumerate(display):
        if entry[0] == "podcast" and entry[2] == cursor:
            visual_cursor = vi
            break

    visual_start = max(0, visual_cursor - height // 2)
    visible = display[visual_start: visual_start + height]

    title_w = max(0, width - 1 - badge_w)

    for entry in visible:
        kind = entry[0]

        if kind == "following_header":
            label = " Following"
            dashes = "─" * max(0, title_w - len(label))
            t = Text(no_wrap=True)
            t.append(label, style=Style(color=ACCENT, bold=True))
            t.append(dashes, style=Style(color=ACCENT_DIM))
            table.add_row(Text("★", style=Style(color=ACCENT, bold=True)), t, Text(""))

        elif kind == "spacer":
            table.add_row(Text(""), Text(""), Text(""))

        elif kind == "trending_header":
            label = " Trending "
            n = max(0, title_w - len(label))
            t = Text(no_wrap=True)
            t.append("─" * (n // 2), style=Style(color=FG_DIM))
            t.append(label, style=Style(color=FG_DIM, italic=True))
            t.append("─" * (n - n // 2), style=Style(color=FG_DIM))
            table.add_row(Text(""), t, Text(""))

        elif kind == "podcast_sub":
            _, p, li = entry
            is_selected = li == cursor
            pub_ts = p.get("newestItemPubdate", 0) or 0
            ep_count = p.get("episodeCount", 0) or 0
            parts: list[str] = []
            if pub_ts:
                parts.append(_fmt_date(pub_ts))
            if ep_count:
                parts.append(f"{ep_count} ep")
            sub_str = "  " + "  ·  ".join(parts)
            row_style = Style(bgcolor=BG_SELECT) if is_selected else Style()
            table.add_row(
                Text(""),
                Text(sub_str, style=Style(color=FG_DIM), overflow="ellipsis", no_wrap=True),
                Text(""),
                style=row_style,
            )

        else:  # podcast
            _, p, li = entry
            is_selected = li == cursor
            feed_id = p.get("id", 0)
            is_followed = feed_id in following_ids

            icon = FOLLOW_ICON if is_followed else " "
            icon_style = Style(color=ACCENT) if is_followed else Style(color=FG_DIM)
            name = p.get("title", f"Feed {feed_id}")
            row_style = Style(bgcolor=BG_SELECT) if is_selected else Style()
            name_style = Style(color=FG, bold=True) if is_selected else Style(color=FG)

            badge_t = Text("")
            if is_followed:
                pub_ts = p.get("newestItemPubdate", 0) or 0
                if pub_ts and (now - pub_ts) < _NEW_EPISODE_SECS:
                    badge_t = Text("NEW", style=Style(color=NEW_COLOR, bold=True))

            table.add_row(
                Text(icon, style=icon_style),
                Text(name, style=name_style, overflow="ellipsis", no_wrap=True),
                badge_t,
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
    has_focus: bool = True,
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
        if is_selected:
            if has_focus:
                title_style = Style(color=FG, bold=True)
            else:
                # Dimmer selection when panel is not focused
                title_style = Style(color=FG_DIM, bold=True)
        else:
            title_style = Style(color=FG)

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
    image_lines: list[str],
    image_cols: int,
    image_rows: int,
    is_following: bool = False,
    loading: bool = False,
) -> Group:
    lines: list[object] = []

    if image_lines:
        for raw in image_lines:
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


# ── player content (title line + progress bar) ────────────────────────────────

def player_content(
    episode: dict | None,
    podcast_title: str,
    position: float,
    duration: float,
    is_playing: bool,
    width: int,
) -> Group:
    if episode is None:
        return Group(
            Text("  No media playing", style=Style(color=FG_DIM)),
            Text(""),
        )

    icon = PLAYING_ICON if is_playing else PAUSED_ICON
    ep_title = episode.get("title", "")
    pos_str = _fmt_dur(int(position)) or "0:00"
    dur_str = _fmt_dur(int(duration)) if duration else "?:??"

    title_t = Text(no_wrap=True, overflow="ellipsis")
    title_t.append(f" {icon} ", style=Style(color=PLAYING_COLOR, bold=True))
    if podcast_title:
        title_t.append(f"{podcast_title}  ", style=Style(color=FG_DIM))
    title_t.append(ep_title, style=Style(color=FG))
    title_t.append(f"  {pos_str} / {dur_str}", style=Style(color=FG_DIM))

    # Full-width progress bar (panel overhead: 2 borders + 2×1 padding = 4)
    bar_width = max(10, width - 4)
    frac = min(1.0, position / duration) if duration > 0 else 0.0
    filled = int(frac * bar_width)
    bar_t = Text(no_wrap=True)
    bar_t.append("█" * filled, style=Style(color=PLAYING_COLOR))
    bar_t.append("░" * (bar_width - filled), style=Style(color=BORDER_COLOR))

    return Group(title_t, bar_t)


# ── hints line ────────────────────────────────────────────────────────────────

def hints_line(search_mode: bool = False, query: str = "") -> Text:
    t = Text(no_wrap=True, overflow="ellipsis")
    if search_mode:
        t.append(" / ", style=Style(color=ACCENT, bold=True))
        t.append(query, style=Style(color=FG))
        t.append("█", style=Style(color=ACCENT))
        t.append("  Enter=search  Esc=cancel", style=Style(color=FG_DIM))
        return t

    _chip = Style(color="#0f172a", bgcolor=ACCENT_DIM, bold=True)
    _lbl = Style(color=FG_DIM)
    _sep = Style(color=BORDER_COLOR)

    def chip(k: str) -> None:
        t.append(f" {k} ", style=_chip)

    def lbl(s: str) -> None:
        t.append(f" {s}", style=_lbl)

    def sep() -> None:
        t.append("  ·  ", style=_sep)

    t.append("  ", style=Style())
    chip("j/k");   lbl("navigate");   sep()
    chip("Enter"); lbl("episodes");   sep()
    chip("p");     lbl("play latest"); sep()
    chip("Space"); lbl("play/pause"); sep()
    chip("←→");   lbl("seek");       sep()
    chip("/");     lbl("search");     sep()
    chip("f");     lbl("follow");     sep()
    chip("Tab");   lbl("toggle");     sep()
    chip("q");     lbl("quit")
    return t
