"""Async PodcastIndex API client."""
from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx

_BASE = "https://api.podcastindex.org/api/1.0"
_UA = "picast/0.1.0"


def _headers(key: str, secret: str) -> dict[str, str]:
    ts = str(int(time.time()))
    auth = hashlib.sha1(f"{key}{secret}{ts}".encode()).hexdigest()
    return {
        "X-Auth-Key": key,
        "X-Auth-Date": ts,
        "Authorization": auth,
        "User-Agent": _UA,
    }


class PodcastIndexAPI:
    def __init__(self, api_key: str, api_secret: str) -> None:
        self._key = api_key
        self._secret = api_secret
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "PodcastIndexAPI":
        self._client = httpx.AsyncClient(timeout=15)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()

    def _h(self) -> dict[str, str]:
        return _headers(self._key, self._secret)

    async def trending(self, max: int = 20, lang: str = "en") -> list[dict]:
        r = await self._client.get(  # type: ignore[union-attr]
            f"{_BASE}/podcasts/trending",
            params={"max": max, "lang": lang},
            headers=self._h(),
        )
        r.raise_for_status()
        return r.json().get("feeds", [])

    async def search(self, query: str, max: int = 20) -> list[dict]:
        r = await self._client.get(  # type: ignore[union-attr]
            f"{_BASE}/search/byterm",
            params={"q": query, "max": max},
            headers=self._h(),
        )
        r.raise_for_status()
        return r.json().get("feeds", [])

    async def episodes(self, feed_id: int, max: int = 20) -> list[dict]:
        r = await self._client.get(  # type: ignore[union-attr]
            f"{_BASE}/episodes/byfeedid",
            params={"id": feed_id, "max": max},
            headers=self._h(),
        )
        r.raise_for_status()
        return r.json().get("items", [])

    async def podcast(self, feed_id: int) -> dict:
        r = await self._client.get(  # type: ignore[union-attr]
            f"{_BASE}/podcasts/byfeedid",
            params={"id": feed_id},
            headers=self._h(),
        )
        r.raise_for_status()
        return r.json().get("feed", {})

    async def fetch_image(self, url: str) -> bytes | None:
        if not url:
            return None
        try:
            r = await self._client.get(url, headers={"User-Agent": _UA}, timeout=8, follow_redirects=True)  # type: ignore[union-attr]
            if r.is_success and r.content:
                return r.content
        except Exception:
            pass
        return None
