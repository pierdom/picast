# picast — codebase guide

## Architecture

picast is a single-process asyncio application with three concurrent tasks:

```
_render_loop   — event-driven: renders only when _render_event is set
_key_loop      — reads raw stdin keypresses, dispatches to _handle_key
_player_poll_loop — polls mpv IPC for playback position every 500 ms
```

**No Textual.** Rich renders text layout, then raw ANSI escape sequences overlay cover art at precise cursor positions. Textual (or any other framework that takes over screen management) would break the image overlay model — don't introduce it.

## Module map

| File | Responsibility |
|------|---------------|
| `app.py` | Event loop, state machine, all async logic |
| `ui/renderer.py` | `Renderer` — assembles Rich layout + image overlay each frame |
| `ui/panels.py` | Pure render functions: podcast cards, episode list, player bar |
| `ui/theme.py` | Color constants and Rich theme; all colors live here |
| `image.py` | Protocol detection (Kitty → iTerm2 → half-block) + rendering |
| `keys.py` | Raw-mode stdin reader, escape sequence parser |
| `player.py` | mpv subprocess + Unix IPC socket wrapper |
| `api.py` | PodcastIndex API client (httpx async) |
| `store.py` | JSON persistence: follows, playback progress |
| `config.py` | Credential loading (env vars → config file → interactive prompt) |

## Rendering model

1. `_render_impl` runs in a thread-pool executor (never blocks the event loop).
2. Rich captures the full frame to a string.
3. The string is written atomically with BSU (`\033[?2026h/l`) to avoid tearing.
4. For Kitty/iTerm2: after the Rich frame, cursor is repositioned per card and the pre-encoded image escape sequence is appended.

**PIL is banned from the render thread.** Image preprocessing (PIL resize + encode) runs in `preprocess_image` via `run_in_executor`, populating `_half_block_cache` or `_img_seq_cache`. The render thread reads from these caches only.

## Layout

```
HEADER_HEIGHT = 1 row
main area     = rows - 7 rows  (split: LEFT_RATIO=8 / RIGHT_RATIO=12 → 40% / 60%)
PLAYER_HEIGHT = 6 rows
```

Left panel: `padding=(0, 1)`, `ROUNDED` border → `left_inner = left_allocated - 4`.  
Podcast cards: single column, each `CARD_THUMB_H + 2` rows tall (`CARD_THUMB_H = 5`).

Right panel (episode list): each episode is 2 rows (title + meta). The **selected**
episode also renders its description (HTML-stripped, word-wrapped, capped at
`_DESC_MAX_LINES`) below the meta. Because episodes have variable height,
`episode_list_content` uses a budget-based scroll window: it always keeps the
selected episode's full block on screen, then grows outward to fill `height`.

## State

`RenderState` (dataclass) in `renderer.py` is the single source of truth passed into every render. `App` mutates it from the event loop; `Renderer` only reads it.

## Image overlay positioning (Kitty/iTerm2)

```python
term_row = HEADER_HEIGHT + vr * card_height + 3
term_col = 4  # panel_border(1) + panel_padding(1) + card_border(1) + 1-indexed
```

If `HEADER_HEIGHT`, `PLAYER_HEIGHT`, or panel padding change, these offsets must be updated.

## Key bindings (current)

| Key(s) | Action |
|--------|--------|
| `j` / `↓` | `_move_cursor(+1)` |
| `k` / `↑` | `_move_cursor(-1)` |
| `l` | `_go_right()` → switches to episode pane |
| `h` / `Esc` | `_go_back()` → returns to podcast pane |
| `Enter` | In podcast pane: open episodes. In episode pane: play. |
| `Space` | Play / pause |
| `←` / `→` | `player.seek(±10)` |
| `/` | Enter search mode |
| `f` | Follow / unfollow |
| `F` | Show following list |
| `Tab` / `Shift+Tab` | Switch focus between podcast and episode panes |
| `p` | Play latest episode |
| `q` / `Ctrl-C` | Quit |

## Theme

All colors are in `ui/theme.py`. The palette uses orange accents:

- `ACCENT = "#f97316"` — active borders, selected cards, follow icon
- `ACCENT_DIM = "#ea580c"` — dimly-active borders, paused state, header badge
- `PLAYING_COLOR = "#fb923c"` — playback indicator
- `BORDER_COLOR = "#374151"` — inactive borders

## Data paths

- Config: `~/.config/picast/config.json`
- Follows: `~/.local/share/picast/follows.json`
- Progress: `~/.local/share/picast/progress.json`
- Now-playing cover: `~/.local/share/picast/now_playing_cover` (for MPRIS art)

## OS media controls (MPRIS)

mpv has no built-in MPRIS/D-Bus support — the optional `mpv-mpris` plugin
(`mpris.so`) provides it. `player.py` probes the standard plugin locations
(`_MPRIS_CANDIDATES`) and, if found, loads it via `--script=` on each `play()`.
It also passes:

- `--force-media-title=<episode — show>` → `xesam:title`
- `--cover-art-files=<path>` → `mpris:artUrl` (first source mpv-mpris checks)

`App._write_cover_file` dumps the already-cached cover bytes (`state.cover_images`)
to the now-playing cover path; it's synchronous and does no network I/O, so it
only works when the cover was prefetched (the normal case). No plugin → audio
still plays, just no control surface.

## Running

```bash
uv run picast          # from the repo root
uv run python -m picast
```

## Dependencies

- `rich` — terminal rendering
- `httpx` — async HTTP for PodcastIndex API
- `pillow` — image resize/encode for cover art
- `mpv` (system) — audio playback via subprocess + IPC socket
- `mpv-mpris` (system, optional) — `mpris.so` plugin for OS media controls
