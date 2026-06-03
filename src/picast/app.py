"""Main application: asyncio event loop + state machine."""
from __future__ import annotations

import asyncio
import signal
import sys

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


class App:
    def __init__(self) -> None:
        self.state = RenderState()
        self.renderer = Renderer()
        self.keys = KeyReader()
        self.player = MpvPlayer()
        self._running = False
        self._api: PodcastIndexAPI | None = None
        self._pending_fetch: asyncio.Task | None = None

    # ── entry point ───────────────────────────────────────────────────────────

    async def run(self) -> None:
        api_key, api_secret = config.get_api_credentials()
        if not api_key or not api_secret:
            api_key, api_secret = config.prompt_and_save_credentials()
        if not api_key or not api_secret:
            print("No credentials — exiting.", file=sys.stderr)
            return

        self._running = True
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

    # ── loops ─────────────────────────────────────────────────────────────────

    async def _render_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while self._running:
            await loop.run_in_executor(None, self.renderer.render, self.state)
            await asyncio.sleep(0.1)

    async def _key_loop(self) -> None:
        async for key in self.keys:
            if not self._running:
                break
            await self._handle_key(key)

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
            else:
                if self.state.is_playing:
                    self.state.is_playing = False
            await asyncio.sleep(0.5)

    async def _initial_load(self) -> None:
        await self._load_trending()

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
            case k if k == "/":
                self.state.search_mode = True
                self.state.search_query = ""
            case k if k == "p":
                if self.state.view in ("home", "following") and self.state.selected_podcast:
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
                # Toggle between home and following
                if self.state.view in ("home", "following"):
                    if self.state.view == "home":
                        await self._show_following()
                    else:
                        await self._load_trending()

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
        elif len(key) == 1 and key.isprintable():
            self.state.search_query += key

    # ── navigation actions ────────────────────────────────────────────────────

    def _move_cursor(self, delta: int) -> None:
        if self.state.view in ("home", "following"):
            n = len(self.state.podcasts)
            if n:
                self.state.podcast_cursor = max(0, min(n - 1, self.state.podcast_cursor + delta))
                asyncio.ensure_future(self._on_podcast_cursor_change())
        elif self.state.view == "podcast":
            n = len(self.state.episodes)
            if n:
                self.state.episode_cursor = max(0, min(n - 1, self.state.episode_cursor + delta))

    async def _on_podcast_cursor_change(self) -> None:
        """Load details for highlighted podcast (non-blocking)."""
        if not self.state.podcasts:
            return
        p = self.state.podcasts[self.state.podcast_cursor]
        if self.state.selected_podcast and self.state.selected_podcast.get("id") == p.get("id"):
            return
        self.state.selected_podcast = p
        self.state.cover_image_bytes = None
        url = p.get("artwork", "") or p.get("image", "")
        if url and self._api:
            self.state.cover_image_bytes = await self._api.fetch_image(url)

    async def _handle_enter(self) -> None:
        if self.state.view in ("home", "following"):
            if not self.state.podcasts:
                return
            p = self.state.podcasts[self.state.podcast_cursor]
            await self._open_podcast(p)
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
        if self.state.view == "home":
            self._reorder_home_list()
        asyncio.ensure_future(self._clear_status())

    def _reorder_home_list(self) -> None:
        """Re-sort home list: followed podcasts first, trending after. Keeps cursor on same item."""
        sel_id = self.state.selected_podcast.get("id", 0) if self.state.selected_podcast else None
        fids = self.state.following_ids
        following_pods = [p for p in self.state.podcasts if p.get("id", 0) in fids]
        trending_pods = [p for p in self.state.podcasts if p.get("id", 0) not in fids]
        self.state.podcasts = following_pods + trending_pods
        self.state.following_count = len(following_pods)
        if sel_id is not None:
            for i, p in enumerate(self.state.podcasts):
                if p.get("id", 0) == sel_id:
                    self.state.podcast_cursor = i
                    break

    async def _clear_status(self) -> None:
        await asyncio.sleep(2)
        self.state.status = ""

    async def _go_back(self) -> None:
        if self.state.view == "podcast":
            self.state.view = "home"
            self.state.episodes = []
            self.state.episode_cursor = 0
            await self._load_trending()

    async def _show_following(self) -> None:
        follows = store.get_follows()
        self.state.podcasts = list(follows.values())
        self.state.following_ids = {int(k) for k in follows}
        self.state.following_count = 0  # dedicated view; no section split needed
        self.state.podcast_cursor = 0
        self.state.view = "following"
        self.state.selected_podcast = None
        self.state.cover_image_bytes = None
        if self.state.podcasts:
            await self._on_podcast_cursor_change()

    # ── podcast/episode loading ───────────────────────────────────────────────

    async def _load_trending(self) -> None:
        if not self._api:
            return
        self.state.status = "Loading trending…"
        self.state.loading = True
        try:
            podcasts = await self._api.trending(max=30)
            follows = store.get_follows()
            self.state.following_ids = {int(k) for k in follows}
            following_pods = list(follows.values())
            trending_pods = [p for p in podcasts if p.get("id", 0) not in self.state.following_ids]
            self.state.podcasts = following_pods + trending_pods
            self.state.following_count = len(following_pods)
            self.state.podcast_cursor = 0
            self.state.view = "home"
            if self.state.podcasts:
                await self._on_podcast_cursor_change()
        except Exception as exc:
            self.state.status = f"Error: {exc}"
        finally:
            self.state.loading = False
            self.state.status = ""

    async def _search(self, query: str) -> None:
        if not self._api:
            return
        self.state.status = f'Searching "{query}"...'
        self.state.loading = True
        try:
            results = await self._api.search(query)
            self.state.podcasts = results
            self.state.following_count = 0  # no section split for search results
            self.state.podcast_cursor = 0
            self.state.view = "home"
            self.state.selected_podcast = None
            self.state.cover_image_bytes = None
            if results:
                await self._on_podcast_cursor_change()
            else:
                self.state.status = "No results"
                await self._clear_status()
        except Exception as exc:
            self.state.status = f"Error: {exc}"
            await self._clear_status()
        finally:
            self.state.loading = False
            if self.state.status.startswith("Searching"):
                self.state.status = ""

    async def _open_podcast(self, podcast: dict) -> None:
        if not self._api:
            return
        self.state.view = "podcast"
        self.state.selected_podcast = podcast
        self.state.episodes = []
        self.state.episode_cursor = 0
        self.state.loading = True
        try:
            feed_id = podcast.get("id", 0)
            episodes, image_bytes = await asyncio.gather(
                self._api.episodes(feed_id, max=50),
                self._api.fetch_image(podcast.get("artwork", "") or podcast.get("image", "")),
            )
            self.state.episodes = episodes
            self.state.cover_image_bytes = image_bytes
            # Load statuses
            self.state.episode_statuses = {
                ep["id"]: store.episode_status(ep["id"]) for ep in episodes if ep.get("id")
            }
        except Exception as exc:
            self.state.status = f"Error: {exc}"
            await self._clear_status()
        finally:
            self.state.loading = False

    async def _play_latest(self, podcast: dict) -> None:
        """Fetch the latest episode of podcast and start playback immediately."""
        if not self._api:
            return
        feed_id = podcast.get("id", 0)
        podcast_title = podcast.get("title", "")  # capture before await
        self.state.status = "Loading…"
        try:
            episodes = await self._api.episodes(feed_id, max=1)
            if not episodes:
                self.state.status = "No episodes"
                await self._clear_status()
                return
            self._play_episode(episodes[0], podcast_title=podcast_title)
        except Exception as exc:
            self.state.status = f"Error: {exc}"
            await self._clear_status()
        else:
            self.state.status = ""

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
        # Cancel all tasks
        for task in asyncio.all_tasks():
            task.cancel()

    def _shutdown(self) -> None:
        self.keys.stop()
        self.player.stop()
        self.renderer.exit_screen()
