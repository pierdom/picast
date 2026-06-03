"""Config stored at ~/.config/picast/config.json."""
from __future__ import annotations

import json
import os
from pathlib import Path

_CONFIG_PATH = Path.home() / ".config" / "picast" / "config.json"


def load() -> dict:
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text())
        except Exception:
            pass
    return {}


def save(data: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(data, indent=2))


def get_api_credentials() -> tuple[str, str]:
    """Return (api_key, api_secret). Reads env vars first, then config file."""
    key = os.environ.get("PODCAST_INDEX_API_KEY", "")
    secret = os.environ.get("PODCAST_INDEX_API_SECRET", "")
    if key and secret:
        return key, secret

    cfg = load()
    key = cfg.get("api_key", "")
    secret = cfg.get("api_secret", "")
    return key, secret


def prompt_and_save_credentials() -> tuple[str, str]:
    """Interactive first-run credential setup (runs before entering TUI)."""
    print("\npicast needs PodcastIndex API credentials.")
    print("Get a free key at https://podcastindex.org/login\n")
    key = input("API Key:    ").strip()
    secret = input("API Secret: ").strip()
    if key and secret:
        save({"api_key": key, "api_secret": secret})
        print("\nCredentials saved to ~/.config/picast/config.json\n")
    return key, secret
