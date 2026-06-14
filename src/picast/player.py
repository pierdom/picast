"""mpv subprocess wrapper with Unix socket IPC."""
from __future__ import annotations

import json
import os
import socket as _socket
import subprocess
import threading
import time
from pathlib import Path

_SOCK = str(Path.home() / ".local" / "share" / "picast" / "mpv.sock")

# Candidate locations for the mpv-mpris plugin (mpris.so). Loading it explicitly
# means OS media controls (MPRIS/D-Bus) work regardless of the user's mpv.conf.
_MPRIS_CANDIDATES = (
    "/usr/lib/mpv-mpris/mpris.so",
    "/usr/lib/x86_64-linux-gnu/mpv-mpris/mpris.so",
    "/usr/lib64/mpv-mpris/mpris.so",
    "/etc/mpv/scripts/mpris.so",
    str(Path.home() / ".config" / "mpv" / "scripts" / "mpris.so"),
    "/usr/share/mpv/scripts/mpris.so",
)


def _find_mpris() -> str | None:
    for path in _MPRIS_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


class MpvPlayer:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._paused = False
        self._current_episode_id: int | None = None
        self._mpris = _find_mpris()

    # ── public ────────────────────────────────────────────────────────────────

    def play(
        self,
        url: str,
        episode_id: int = 0,
        start_pos: float = 0.0,
        title: str | None = None,
        cover_path: str | None = None,
    ) -> None:
        with self._lock:
            self._kill()
            try:
                os.unlink(_SOCK)
            except FileNotFoundError:
                pass
            args = [
                "mpv", "--no-video", "--really-quiet",
                f"--input-ipc-server={_SOCK}",
            ]
            if self._mpris:
                args.append(f"--script={self._mpris}")
            if title:
                args.append(f"--force-media-title={title}")
            if cover_path:
                # mpv-mpris reads mpris:artUrl from the cover-art-files property.
                args.append(f"--cover-art-files={cover_path}")
            if start_pos > 0:
                args.append(f"--start={start_pos}")
            args.append(url)
            self._proc = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._paused = False
            self._current_episode_id = episode_id

    def pause_toggle(self) -> None:
        self._cmd({"command": ["cycle", "pause"]})
        self._paused = not self._paused

    def seek(self, delta: int) -> None:
        self._cmd({"command": ["seek", delta, "relative"]})

    def seek_abs(self, position: float) -> None:
        self._cmd({"command": ["seek", position, "absolute"]})

    def stop(self) -> None:
        with self._lock:
            self._kill()
            self._current_episode_id = None

    def get_property(self, prop: str) -> float | None:
        if not os.path.exists(_SOCK):
            return None
        try:
            with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(_SOCK)
                s.sendall(json.dumps({"command": ["get_property", prop]}).encode() + b"\n")
                data = b""
                while b"\n" not in data:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                result = json.loads(data.split(b"\n")[0])
                if result.get("error") == "success":
                    val = result.get("data")
                    return float(val) if val is not None else None
        except Exception:
            pass
        return None

    @property
    def running(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def episode_id(self) -> int | None:
        return self._current_episode_id

    # ── private ───────────────────────────────────────────────────────────────

    def _kill(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
            try:
                self._proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        self._proc = None
        self._paused = False

    def _cmd(self, payload: dict) -> None:
        for _ in range(15):
            if os.path.exists(_SOCK):
                break
            time.sleep(0.1)
        try:
            with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(_SOCK)
                s.sendall(json.dumps(payload).encode() + b"\n")
        except Exception:
            pass
