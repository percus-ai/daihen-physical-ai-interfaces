"""Track-based realtime runtime."""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from interfaces_backend.models.realtime import RealtimeFrame

REALTIME_CONNECTION_QUEUE_SIZE = 256
_SENTINEL = object()


@dataclass(frozen=True)
class UserID:
    value: str

    def __post_init__(self) -> None:
        normalized = str(self.value or "").strip()
        if not normalized:
            raise ValueError("user_id must not be empty")
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True)
class Broadcast:
    pass


RealtimeScope = UserID | Broadcast


class RealtimeConnection:
    """One SSE connection queue."""

    def __init__(
        self,
        *,
        runtime: "RealtimeRuntime",
        scope: UserID,
        tab_id: str,
        connection_id: str | None = None,
        queue_size: int = REALTIME_CONNECTION_QUEUE_SIZE,
    ) -> None:
        self.runtime = runtime
        self.scope = scope
        self.tab_id = tab_id
        self.connection_id = connection_id or uuid4().hex
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue[RealtimeFrame | object] = asyncio.Queue(maxsize=queue_size)
        self._closed = False
        self._lock = threading.RLock()

    def enqueue(self, frame: RealtimeFrame) -> None:
        with self._lock:
            if self._closed:
                return
            if self._loop.is_closed():
                self.close()
                return
        self._loop.call_soon_threadsafe(self._enqueue_on_loop, frame)

    def close(self) -> None:
        should_close = False
        with self._lock:
            if not self._closed:
                self._closed = True
                should_close = True
        if not should_close:
            return
        self.runtime.remove_connection(self)
        if self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._enqueue_sentinel_on_loop)

    async def next_frame(self, *, timeout_seconds: float) -> RealtimeFrame | None:
        try:
            item = await asyncio.wait_for(self._queue.get(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return None
        if item is _SENTINEL:
            raise StopAsyncIteration
        return item

    def _enqueue_on_loop(self, frame: RealtimeFrame) -> None:
        with self._lock:
            if self._closed:
                return
        if self._queue.full():
            self.close()
            return
        self._queue.put_nowait(frame)

    def _enqueue_sentinel_on_loop(self) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(_SENTINEL)


class RealtimeTrack:
    """Authoritative state sequence for one kind/key."""

    def __init__(
        self,
        *,
        runtime: "RealtimeRuntime",
        scope: RealtimeScope,
        kind: str,
        key: str,
    ) -> None:
        self.runtime = runtime
        self.scope = scope
        self.kind = kind
        self.key = key
        self._lock = threading.RLock()
        self._revision = 0
        self._state: dict[str, Any] = {}
        self._pending_state: dict[str, Any] | None = None
        self._latest_frame: RealtimeFrame | None = None

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    @property
    def latest_frame(self) -> RealtimeFrame | None:
        with self._lock:
            return self._latest_frame

    @property
    def state(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def replace(self, detail: dict[str, Any], *, commit: bool = True) -> RealtimeFrame | None:
        with self._lock:
            self._pending_state = dict(detail)
            if not commit:
                return None
            return self._commit_locked()

    def patch(self, patch: dict[str, Any], *, commit: bool = True) -> RealtimeFrame | None:
        with self._lock:
            base = self._pending_state if self._pending_state is not None else self._state
            self._pending_state = {**base, **patch}
            if not commit:
                return None
            return self._commit_locked()

    def commit(self) -> RealtimeFrame:
        with self._lock:
            if self._pending_state is None:
                raise RuntimeError("No pending state to commit")
            return self._commit_locked()

    def _commit_locked(self) -> RealtimeFrame:
        next_state = self._pending_state
        if next_state is None:
            raise RuntimeError("No pending state to commit")
        revision = self._revision + 1
        frame = RealtimeFrame(
            kind=self.kind,
            key=self.key,
            revision=revision,
            detail=dict(next_state),
        )
        self._state = dict(next_state)
        self._pending_state = None
        self._revision = revision
        self._latest_frame = frame
        self.runtime.enqueue_frame(self.scope, frame)
        return frame


class RealtimeRuntime:
    """Process-local realtime track and connection registry."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tracks: dict[tuple[RealtimeScope, str, str], RealtimeTrack] = {}
        self._connections: dict[UserID, dict[str, RealtimeConnection]] = defaultdict(dict)

    def track(self, *, scope: RealtimeScope, kind: str, key: str) -> RealtimeTrack:
        if not isinstance(scope, (UserID, Broadcast)):
            raise TypeError("scope must be UserID or Broadcast")
        normalized_kind = self._normalize_identifier(kind, "kind")
        normalized_key = self._normalize_identifier(key, "key")
        track_key = (scope, normalized_kind, normalized_key)
        with self._lock:
            track = self._tracks.get(track_key)
            if track is not None:
                return track
            track = RealtimeTrack(
                runtime=self,
                scope=scope,
                kind=normalized_kind,
                key=normalized_key,
            )
            self._tracks[track_key] = track
            return track

    def open_connection(self, *, user_id: str, tab_id: str) -> RealtimeConnection:
        scope = UserID(user_id)
        normalized_tab_id = self._normalize_identifier(tab_id, "tab_id")
        connection = RealtimeConnection(
            runtime=self,
            scope=scope,
            tab_id=normalized_tab_id,
        )
        with self._lock:
            self._connections[scope][connection.connection_id] = connection
            latest_frames = [
                frame
                for (track_scope, _kind, _key), track in self._tracks.items()
                if isinstance(track_scope, Broadcast) or track_scope == scope
                for frame in [track.latest_frame]
                if frame is not None
            ]
        for frame in latest_frames:
            connection.enqueue(frame)
        return connection

    def remove_connection(self, connection: RealtimeConnection) -> None:
        with self._lock:
            scoped = self._connections.get(connection.scope)
            if scoped is None:
                return
            scoped.pop(connection.connection_id, None)
            if not scoped:
                self._connections.pop(connection.scope, None)

    def enqueue_frame(self, scope: RealtimeScope, frame: RealtimeFrame) -> None:
        with self._lock:
            if isinstance(scope, Broadcast):
                connections = [
                    connection
                    for scoped_connections in self._connections.values()
                    for connection in scoped_connections.values()
                ]
            else:
                connections = list(self._connections.get(scope, {}).values())
        for connection in connections:
            connection.enqueue(frame)

    def shutdown(self) -> None:
        with self._lock:
            connections = [
                connection
                for scoped_connections in self._connections.values()
                for connection in scoped_connections.values()
            ]
            self._connections.clear()
            self._tracks.clear()
        for connection in connections:
            connection.close()

    @staticmethod
    def _normalize_identifier(value: str, name: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{name} must not be empty")
        return normalized


_realtime_runtime: RealtimeRuntime | None = None
_realtime_runtime_lock = threading.Lock()


def get_realtime_runtime() -> RealtimeRuntime:
    global _realtime_runtime
    with _realtime_runtime_lock:
        if _realtime_runtime is None:
            _realtime_runtime = RealtimeRuntime()
    return _realtime_runtime


def reset_realtime_runtime() -> None:
    global _realtime_runtime
    with _realtime_runtime_lock:
        if _realtime_runtime is not None:
            _realtime_runtime.shutdown()
        _realtime_runtime = None
