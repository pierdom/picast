"""Persistence: followed podcasts + per-episode playback progress."""
from __future__ import annotations

import json
import time
from pathlib import Path

_DATA_DIR = Path.home() / ".local" / "share" / "picast"
_FOLLOWS_PATH = _DATA_DIR / "follows.json"
_PROGRESS_PATH = _DATA_DIR / "progress.json"


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


# ── follows ───────────────────────────────────────────────────────────────────

def get_follows() -> dict[str, dict]:
    """Return {feed_id_str: {id, title, artwork, ...}}."""
    return _load(_FOLLOWS_PATH)


def follow(podcast: dict) -> None:
    follows = get_follows()
    follows[str(podcast["id"])] = {
        **podcast,
        "artwork": podcast.get("artwork", "") or podcast.get("image", ""),
        "followed_at": int(time.time()),
    }
    _dump(_FOLLOWS_PATH, follows)


def unfollow(feed_id: int) -> None:
    follows = get_follows()
    follows.pop(str(feed_id), None)
    _dump(_FOLLOWS_PATH, follows)


def is_following(feed_id: int) -> bool:
    return str(feed_id) in get_follows()


# ── progress ──────────────────────────────────────────────────────────────────

def get_progress(episode_id: int) -> dict:
    return _load(_PROGRESS_PATH).get(str(episode_id), {})


def save_progress(episode_id: int, position: float, duration: float) -> None:
    all_prog = _load(_PROGRESS_PATH)
    prev = all_prog.get(str(episode_id), {})
    status = prev.get("status", "started")
    if duration > 0 and position / duration >= 0.8:
        status = "completed"
    elif position >= 5:
        status = "started"
    all_prog[str(episode_id)] = {
        "position": position,
        "duration": duration,
        "status": status,
        "updated": int(time.time()),
    }
    _dump(_PROGRESS_PATH, all_prog)


def episode_status(episode_id: int) -> str:
    """Return 'new', 'started', or 'completed'."""
    return get_progress(episode_id).get("status", "new")


def episode_position(episode_id: int) -> float:
    return get_progress(episode_id).get("position", 0.0)
