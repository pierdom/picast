"""Main application: asyncio event loop + state machine."""
from __future__ import annotations

import asyncio
import signal
import sys
import time

from picast import config, store
from picast.api import PodcastIndexAPI
from picast.keys import (
    BACKSPACE,
    CTRL_C,
    DOWN,
    ENTER,
    ESCAPE,
    LEFT,
    RIGHT,
    SPACE,
    TAB,
    UP,
    KeyReader,
)
from picast.player import MpvPlayer
from picast.ui.renderer import Renderer, RenderState


# How long a stored follow's metadata stays fresh before we re-fetch it.
_FOLLOW_REFRESH_TTL = 3600  # seconds


def _follow_is_stale(podcast: dict) -> bool:
    """True if a stored follow is missing core fields or its data has aged out."""
    if not podcast.get("description") or not podcast.get("newestItemPubdate"):
        return True
    return time.time() - (podcast.get("refreshed_at") or 0) > _FOLLOW_REFRESH_TTL


def _sort_by_recency(podcasts: list[dict]) -> list[dict]:
    return sorted(podcasts, key=lambda p: p.get("newestItemPubdate") or 0, reverse=True)


class App:
    def __init__(self) -> None:
        self.state = RenderState()
        self.renderer = Renderer()
        self.keys = KeyReader()
        self.player = MpvPlayer()
        self._running = False
        self._api: PodcastIndexAPI | None = None
        self._pending_fetch: asyncio.Task | None = None
        self._render_event: asyncio.Event | None = None

    # ── entry point ───────────────────────────────────────────────────────────

    async def run(self) -> None:
        api_key, api_secret = config.get_api_credentials()
        if not api_key or not api_secret:
            api_key, api_secret = config.prompt_and_save_credentials()
        if not api_key or not api_secret:
            print("No credentials — exiting.", file=sys.stderr)
            return

        self._running = True
        self._render_event = asyncio.Event()
        self._render_event.set()  # render immediately on start
        loop = asyncio.get_running_loop()

        async with PodcastIndexAPI(api_key, api_secret) as api:
            self._api = api
            self.renderer.enter_screen()
            self.keys.start(loop)

            # Intercept SIGTERM/SIGINT for clean exit
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._request_stop)

            try:
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self._render_loop(), name="render")
                    tg.create_task(self._key_loop(), name="keys")
                    tg.create_task(self._player_poll_loop(), name="player_poll")
                    tg.create_task(self._initial_load(), name="initial_load")
            except* (asyncio.CancelledError, KeyboardInterrupt):
                pass
            finally:
                self._shutdown()

    # ── dirty / render ────────────────────────────────────────────────────────

    def _mark_dirty(self) -> None:
        if self._render_event is not None:
            self._render_event.set()

    # ── loops ─────────────────────────────────────────────────────────────────

    async def _render_loop(self) -> None:
        """Render only when state changes; fall back to 1 s tick for progress bar.

        The render runs in a thread-pool executor so key events are never blocked
        by the (potentially slow) Rich layout computation.  A 50 ms post-render
        sleep lets rapid keypresses batch into one redraw instead of triggering
        one expensive render per key.
        """
        loop = asyncio.get_running_loop()
        while self._running:
            try:
                await asyncio.wait_for(self._render_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            self._render_event.clear()
            await loop.run_in_executor(None, self.renderer.render, self.state)
            await asyncio.sleep(0.016)  # batch rapid updates, cap at ~60 fps

    async def _key_loop(self) -> None:
        async for key in self.keys:
            if not self._running:
                break
            await self._handle_key(key)
            self._mark_dirty()

    async def _player_poll_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while self._running:
            if self.player.running:
                pos = await loop.run_in_executor(None, self.player.get_property, "time-pos")
                dur = await loop.run_in_executor(None, self.player.get_property, "duration")
                if pos is not None:
                    self.state.playback_position = pos
                if dur is not None:
                    self.state.playback_duration = dur
                self.state.is_playing = self.player.running and not self.player.paused
                # Persist progress
                if self.state.now_playing_episode and pos is not None:
                    ep_id = self.state.now_playing_episode.get("id", 0)
                    await loop.run_in_executor(
                        None,
                        store.save_progress,
                        ep_id,
                        pos,
                        dur or 0.0,
                    )
                    self.state.episode_statuses[ep_id] = store.episode_status(ep_id)
                self._mark_dirty()
            else:
                if self.state.is_playing:
                    self.state.is_playing = False
                    self._mark_dirty()
            await asyncio.sleep(0.5)

    async def _initial_load(self) -> None:
        await self._load_following_home()

    # ── key handling ──────────────────────────────────────────────────────────

    async def _handle_key(self, key: str) -> None:
        if key == CTRL_C or (key == "q" and not self.state.search_mode):
            self._request_stop()
            return

        if self.state.search_mode:
            await self._handle_search_key(key)
            return

        match key:
            case k if k == UP or k == "k":
                self._move_cursor(-1)
            case k if k == DOWN or k == "j":
                self._move_cursor(1)
            case k if k == ENTER:
                await self._handle_enter()
            case k if k == SPACE:
                self._handle_space()
            case k if k == LEFT:
                self.player.seek(-10)
            case k if k == RIGHT:
                self.player.seek(10)
            case k if k == "l":
                await self._go_right()
            case k if k == "/":
                self.state.search_mode = True
                self.state.search_query = ""
            case k if k == "p":
                if self.state.selected_podcast:
                    asyncio.ensure_future(
                        self._play_latest(self.state.selected_podcast)
                    )
            case k if k == "f":
                self._handle_follow()
            case k if k == "F":
                await self._show_following()
            case k if k == ESCAPE or k == "h":
                await self._go_back()
            case k if k == TAB:
                # Toggle between following and home
                if self.state.view in ("home", "search", "following"):
                    if self.state.view == "following":
                        await self._load_following_home()
                    else:
                        await self._show_following()
                elif self.state.view == "podcast":
                    # Tab in episode view goes back to card grid
                    await self._go_back()

    async def _handle_search_key(self, key: str) -> None:
        if key == ESCAPE:
            self.state.search_mode = False
            self.state.search_query = ""
        elif key == ENTER:
            query = self.state.search_query.strip()
            self.state.search_mode = False
            if query:
                await self._search(query)
        elif key == BACKSPACE:
            self.state.search_query = self.state.search_query[:-1]
        elif key == SPACE:
            self.state.search_query += " "
        elif len(key) == 1 and key.isprintable():
            self.state.search_query += key

    # ── navigation actions ────────────────────────────────────────────────────

    def _move_cursor(self, delta: int) -> None:
        if self.state.view in ("home", "following", "search"):
            n = len(self.state.podcasts)
            if n:
                self.state.podcast_cursor = max(0, min(n - 1, self.state.podcast_cursor + delta))
                asyncio.ensure_future(self._on_podcast_cursor_change())
        elif self.state.view == "podcast":
            n = len(self.state.episodes)
            if n:
                self.state.episode_cursor = max(0, min(n - 1, self.state.episode_cursor + delta))

    async def _on_podcast_cursor_change(self) -> None:
        """Auto-load episodes for the highlighted podcast (debounced)."""
        if not self.state.podcasts:
            return
        p = self.state.podcasts[self.state.podcast_cursor]
        pid = p.get("id", 0)
        if self.state.selected_podcast and self.state.selected_podcast.get("id") == pid:
            return
        self.state.selected_podcast = p
        self._mark_dirty()

        # Cancel any pending episode fetch
        if self._pending_fetch:
            self._pending_fetch.cancel()
            self._pending_fetch = None

        # Fetch image if not already cached
        if pid not in self.state.cover_images and self._api:
            url = p.get("artwork", "") or p.get("image", "")
            if url:
                asyncio.ensure_future(self._fetch_image_for(pid, url))

        # Debounced episode load
        self._pending_fetch = asyncio.ensure_future(
            self._load_episodes_debounced(p, pid)
        )

    async def _handle_enter(self) -> None:
        if self.state.view in ("home", "following", "search"):
            if not self.state.podcasts:
                return
            # Focus the right panel (episode list)
            self.state.view = "podcast"
            self.state.episode_cursor = 0
            # If episodes not yet loaded for this podcast, trigger load now
            p = self.state.podcasts[self.state.podcast_cursor]
            pid = p.get("id", 0)
            if self.state.episodes_for_pod != pid:
                self.state.episodes = []
                self.state.episodes_for_pod = pid
                if self._api:
                    asyncio.ensure_future(self._load_episodes_now(p, pid))
        elif self.state.view == "podcast":
            if not self.state.episodes:
                return
            ep = self.state.episodes[self.state.episode_cursor]
            self._play_episode(ep)

    def _handle_space(self) -> None:
        if self.player.running:
            self.player.pause_toggle()
            self.state.is_playing = not self.player.paused

    def _handle_follow(self) -> None:
        p = self.state.selected_podcast
        if not p:
            return
        fid = p.get("id", 0)
        if store.is_following(fid):
            store.unfollow(fid)
            self.state.following_ids.discard(fid)
            self.state.status = f"Unfollowed {p.get('title', '')}"
        else:
            store.follow(p)
            self.state.following_ids.add(fid)
            self.state.status = f"Following {p.get('title', '')}"
        asyncio.ensure_future(self._clear_status())

    async def _clear_status(self) -> None:
        await asyncio.sleep(2)
        self.state.status = ""
        self._mark_dirty()

    async def _go_back(self) -> None:
        if self.state.view == "podcast":
            # Return to card grid without clearing episodes (smooth UX)
            self.state.view = "home"

    async def _go_right(self) -> None:
        if self.state.view in ("home", "following", "search"):
            await self._handle_enter()

    async def _show_following(self) -> None:
        follows = store.get_follows()
        self.state.podcasts = _sort_by_recency(list(follows.values()))
        self.state.following_ids = {int(k) for k in follows}
        self.state.following_count = len(self.state.podcasts)
        self.state.podcast_cursor = 0
        self.state.view = "following"
        self.state.selected_podcast = None
        if self.state.podcasts and self._api:
            # Fire and forget — don't block key handling on image downloads
            asyncio.ensure_future(self._prefetch_images(self.state.podcasts))
            for p in self.state.podcasts:
                if _follow_is_stale(p):
                    asyncio.ensure_future(self._refresh_follow_metadata(p))
        if self.state.podcasts:
            await self._on_podcast_cursor_change()

    # ── podcast/episode loading ───────────────────────────────────────────────

    async def _load_following_home(self) -> None:
        """Load followed podcasts as the home screen."""
        follows = store.get_follows()
        self.state.following_ids = {int(k) for k in follows}
        self.state.podcasts = _sort_by_recency(list(follows.values()))
        self.state.following_count = len(self.state.podcasts)
        self.state.podcast_cursor = 0
        self.state.view = "home"
        self.state.selected_podcast = None
        if self.state.podcasts and self._api:
            # Fire and forget — don't block key handling on image downloads
            asyncio.ensure_future(self._prefetch_images(self.state.podcasts))
            # Refresh metadata for any follow that's missing core fields or stale
            for p in self.state.podcasts:
                if _follow_is_stale(p):
                    asyncio.ensure_future(self._refresh_follow_metadata(p))
        if self.state.podcasts:
            await self._on_podcast_cursor_change()

    async def _refresh_follow_metadata(self, podcast: dict) -> None:
        """Fetch full feed data for a stored follow and backfill missing fields."""
        if not self._api:
            return
        feed_id = podcast.get("id", 0)
        try:
            full = await self._api.podcast(feed_id)
            if not full:
                return
            # byfeedid's newestItemPubdate is unreliable (often empty); fall back to
            # lastUpdateTime, then the previously-stored value, so the card date is fresh.
            newest = (
                full.get("newestItemPubdate")
                or full.get("lastUpdateTime")
                or podcast.get("newestItemPubdate")
            )
            updated = {
                **podcast,
                **full,
                "newestItemPubdate": newest,
                "followed_at": podcast.get("followed_at", 0),
                "refreshed_at": int(time.time()),
            }
            store.follow(updated)
            for i, p in enumerate(self.state.podcasts):
                if p.get("id") == feed_id:
                    self.state.podcasts[i] = updated
                    if self.state.selected_podcast and self.state.selected_podcast.get("id") == feed_id:
                        self.state.selected_podcast = updated
                    break
            self.state.podcasts = _sort_by_recency(self.state.podcasts)
            # Fetch image if the refreshed metadata brought a URL we didn't have before
            if feed_id not in self.state.cover_images:
                url = updated.get("artwork", "") or updated.get("image", "")
                if url and self._api:
                    asyncio.ensure_future(self._fetch_image_for(feed_id, url))
            self._mark_dirty()
        except Exception:
            pass

    async def _preprocess_and_mark_dirty(self, pid: int, data: bytes) -> None:
        """Run PIL preprocessing in background, then trigger a render to show the image."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.renderer.preprocess_image, pid, data)
        self._mark_dirty()

    async def _prefetch_images(self, podcasts: list[dict]) -> None:
        """Fetch images for a list of podcasts concurrently; mark dirty as each arrives."""
        if not self._api:
            return

        async def fetch_one(p: dict) -> None:
            pid = p.get("id", 0)
            if pid in self.state.cover_images:
                return
            url = p.get("artwork", "") or p.get("image", "")
            if url:
                try:
                    data = await self._api.fetch_image(url)  # type: ignore[union-attr]
                    if data:
                        self.state.cover_images[pid] = data
                        self._mark_dirty()  # render immediately (placeholder visible)
                        # PIL pre-encode runs in background; fires another render when done
                        asyncio.ensure_future(self._preprocess_and_mark_dirty(pid, data))
                except Exception:
                    pass

        await asyncio.gather(*[fetch_one(p) for p in podcasts])

    async def _fetch_image_for(self, pid: int, url: str) -> None:
        """Fetch and cache image for a single podcast id."""
        if not self._api:
            return
        try:
            data = await self._api.fetch_image(url)
            if data:
                self.state.cover_images[pid] = data
                self._mark_dirty()  # render immediately (placeholder visible)
                asyncio.ensure_future(self._preprocess_and_mark_dirty(pid, data))
        except Exception:
            pass

    async def _load_episodes_debounced(self, podcast: dict, pid: int) -> None:
        """Wait briefly then load episodes, so rapid cursor moves don't spam the API."""
        await asyncio.sleep(0.25)
        if not self._api:
            return
        if not self.state.selected_podcast or self.state.selected_podcast.get("id") != pid:
            return
        if self.state.episodes_for_pod == pid:
            return
        await self._load_episodes_now(podcast, pid)

    async def _load_episodes_now(self, podcast: dict, pid: int) -> None:
        """Immediately load episodes for the given podcast."""
        if not self._api:
            return
        self.state.episodes_for_pod = pid
        self.state.episodes = []
        self.state.episode_cursor = 0
        try:
            episodes = await self._api.episodes(pid, max=20)
            if self.state.selected_podcast and self.state.selected_podcast.get("id") == pid:
                self.state.episodes = episodes
                self.state.episode_statuses = {
                    ep["id"]: store.episode_status(ep["id"])
                    for ep in episodes if ep.get("id")
                }
                # The newest episode's date is the most accurate "last update" source.
                # Update whenever it differs from the stored value.
                if episodes:
                    ts = episodes[0].get("datePublished", 0) or 0
                    if ts and ts != (podcast.get("newestItemPubdate") or 0):
                        podcast["newestItemPubdate"] = ts
                        if store.is_following(pid):
                            store.follow(podcast)
                        for i, p in enumerate(self.state.podcasts):
                            if p.get("id") == pid:
                                self.state.podcasts[i] = podcast
                                break
                        self.state.podcasts = _sort_by_recency(self.state.podcasts)
                self._mark_dirty()
        except Exception:
            pass

    async def _search(self, query: str) -> None:
        if not self._api:
            return
        self.state.status = f'Searching "{query}"...'
        self.state.loading = True
        self._mark_dirty()
        try:
            results = await self._api.search(query)
            self.state.podcasts = results
            self.state.following_count = 0
            self.state.podcast_cursor = 0
            self.state.view = "search"
            self.state.selected_podcast = None
            if results:
                asyncio.ensure_future(self._prefetch_images(results))
                await self._on_podcast_cursor_change()
            else:
                self.state.status = "No results"
                asyncio.ensure_future(self._clear_status())
        except Exception as exc:
            self.state.status = f"Error: {exc}"
            asyncio.ensure_future(self._clear_status())
        finally:
            self.state.loading = False
            if self.state.status.startswith("Searching"):
                self.state.status = ""
            self._mark_dirty()

    async def _play_latest(self, podcast: dict) -> None:
        """Fetch the latest episode of podcast and start playback immediately."""
        if not self._api:
            return
        feed_id = podcast.get("id", 0)
        podcast_title = podcast.get("title", "")
        self.state.status = "Loading…"
        self._mark_dirty()
        try:
            episodes = await self._api.episodes(feed_id, max=1)
            if not episodes:
                self.state.status = "No episodes"
                asyncio.ensure_future(self._clear_status())
                return
            self._play_episode(episodes[0], podcast_title=podcast_title)
        except Exception as exc:
            self.state.status = f"Error: {exc}"
            asyncio.ensure_future(self._clear_status())
        else:
            self.state.status = ""
        self._mark_dirty()

    def _play_episode(self, episode: dict, podcast_title: str | None = None) -> None:
        ep_id = episode.get("id", 0)
        url = episode.get("enclosureUrl", "")
        if not url:
            self.state.status = "No audio URL"
            asyncio.ensure_future(self._clear_status())
            return
        start_pos = store.episode_position(ep_id)
        self.player.play(url, episode_id=ep_id, start_pos=start_pos)
        self.state.now_playing_episode = episode
        if podcast_title is not None:
            self.state.now_playing_podcast_title = podcast_title
        elif self.state.selected_podcast:
            self.state.now_playing_podcast_title = self.state.selected_podcast.get("title", "")
        else:
            self.state.now_playing_podcast_title = ""
        self.state.is_playing = True
        self.state.playback_position = start_pos
        self.state.playback_duration = episode.get("duration", 0) or 0.0

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def _request_stop(self) -> None:
        self._running = False
        for task in asyncio.all_tasks():
            task.cancel()

    def _shutdown(self) -> None:
        self.keys.stop()
        self.player.stop()
        self.renderer.exit_screen()
