# picast

A terminal podcast player powered by [PodcastIndex](https://podcastindex.org).

Discover and follow podcasts, browse episodes, and listen — all from the terminal, with cover art rendered inline when your terminal supports it.

## Requirements

- Python 3.11+
- [mpv](https://mpv.io) (audio playback)
- A PodcastIndex API key (free at [podcastindex.org/login](https://podcastindex.org/login))
- _Optional:_ [mpv-mpris](https://github.com/hoyon/mpv-mpris) for OS media controls (see below)

## Installation

```bash
# with uv (recommended)
uv tool install .

# or with pip
pip install .
```

## First run

```bash
picast
```

On first launch picast will prompt for your PodcastIndex API key and secret, then save them to `~/.config/picast/config.json`. You can also set them as environment variables:

```bash
export PODCAST_INDEX_API_KEY=your_key
export PODCAST_INDEX_API_SECRET=your_secret
```

## Layout

```
┌─ Following ──────────────────────┐ ┌─ Podcast title ────────────────────────────────┐
│ ╭──────────────────────────────╮ │ │ ● Episode title                                │
│ │ [art] Podcast title       ♥ │ │ │   Jan 15  ·  45:30                             │
│ │       Author                │ │ │ ● Another episode                              │
│ │       Description…          │ │ │   Jan 08  ·  1:02:11                           │
│ │       Jan 15  ● NEW         │ │ │                                                │
│ ╰──────────────────────────────╯ │ │                                                │
└──────────────────────────────────┘ └────────────────────────────────────────────────┘
┌─ ▶ Now Playing ────────────────────────────────────────────────────────────────────────┐
│  ▶ Podcast Name  Episode title                                          12:34 / 45:30  │
│  █████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│  j/k navigate  · Enter episodes  · p play latest  · Space play/pause  · ←→ seek  · …  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

Left pane (35%): podcast cards sorted by most recent episode. Right pane (65%): episode list for the selected podcast.

## Key bindings

### Navigation

| Key | Action |
|-----|--------|
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `l` / `Enter` | Move to right pane / open episodes |
| `h` / `Esc` | Move to left pane |
| `Tab` | Toggle home / following list |
| `F` | Show following list |

### Playback

| Key | Action |
|-----|--------|
| `p` | Play latest episode of selected podcast |
| `Enter` | Play selected episode (in episode pane) |
| `Space` | Play / pause |
| `←` / `→` | Seek −10 s / +10 s |

### Other

| Key | Action |
|-----|--------|
| `/` | Search podcasts |
| `f` | Follow / unfollow selected podcast |
| `q` | Quit |

## Cover art

picast auto-detects the best image protocol at startup:

- **Kitty** — full-colour, flicker-free (xterm-kitty, WezTerm, Ghostty)
- **iTerm2** — full-colour (iTerm2)
- **Half-block** — Unicode `▀` fallback for any other terminal

## OS media controls (MPRIS)

On Linux, picast integrates with the desktop's media controls (GNOME/KDE widgets,
`playerctl`, keyboard media keys) — including the episode title and podcast cover
art — when the [mpv-mpris](https://github.com/hoyon/mpv-mpris) plugin is installed:

```bash
# Arch
sudo pacman -S mpv-mpris
# Debian/Ubuntu
sudo apt install mpv-mpris
```

picast auto-detects the plugin (`mpris.so`) and loads it on playback; no config
needed. Without it, audio still plays — there's just no OS-level control surface.

## Data

| Path | Contents |
|------|----------|
| `~/.config/picast/config.json` | API credentials |
| `~/.local/share/picast/follows.json` | Followed podcasts |
| `~/.local/share/picast/progress.json` | Episode playback positions |
| `~/.local/share/picast/now_playing_cover` | Current cover, exposed to MPRIS art |
