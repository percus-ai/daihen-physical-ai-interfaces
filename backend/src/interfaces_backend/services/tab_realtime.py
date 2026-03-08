"""In-memory tab-session realtime registry."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Protocol
from uuid import uuid4

from interfaces_backend.models.realtime import (
    TabSessionSubscription,
    TabSessionStateRequest,
    TabSessionStateResponse,
)

_ReplayEvent = dict[str, Any]
_PollStatus = Literal["events", "idle", "deleted", "superseded"]

REPLAY_BUFFER_MAX_EVENTS = 512
FOREGROUND_SESSION_TTL_SECONDS = 120.0
BACKGROUND_SESSION_TTL_SECONDS = 600.0
CLOSING_SESSION_TTL_SECONDS = 5.0


class _SourceRegistryProtocol(Protocol):
    def interval_for(self, subscription: TabSessionSubscription) -> float:
        ...

    async def poll(self, subscription: TabSessionSubscription, state: Any | None = None) -> Any:
        ...

    def cleanup(self, subscription: TabSessionSubscription, state: Any | None) -> None:
        ...


class TabSessionNotFoundError(RuntimeError):
    """Tab session does not exist."""


class TabSessionRevisionConflictError(RuntimeError):
    """Tab session revision is stale."""


@dataclass(frozen=True)
class TabSessionApplyResult:
    tab_session_id: str
    revision: int
    applied_at: str
    subscription_count: int


@dataclass
class _SubscriptionRuntime:
    subscription: TabSessionSubscription
    generation: int
    source_version: int = 0
    last_payload_json: str | None = None
    last_polled_mono: float = 0.0
    pending_immediate: bool = True
    source_state: Any | None = None


class TabSessionStreamHandle:
    """Stream handle bound to one session connection."""

    def __init__(
        self,
        *,
        session: "_TabSession",
        connection_id: str,
        replay_events: list[_ReplayEvent],
        source_registry: _SourceRegistryProtocol,
    ) -> None:
        self._session = session
        self._connection_id = connection_id
        self.replay_events = replay_events
        self._source_registry = source_registry

    async def poll(self, *, after_seq: int) -> tuple[_PollStatus, list[_ReplayEvent]]:
        return await self._session.poll_events(
            connection_id=self._connection_id,
            after_seq=after_seq,
            source_registry=self._source_registry,
        )

    def close(self) -> None:
        self._session.close_stream(self._connection_id)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_subscription_index(state: Optional[TabSessionStateRequest]) -> dict[str, dict[str, Any]]:
    if state is None:
        return {}
    index: dict[str, dict[str, Any]] = {}
    for subscription in state.subscriptions:
        index[subscription.subscription_id] = subscription.model_dump(mode="json")
    return index


def _state_json(state: TabSessionStateRequest) -> dict[str, Any]:
    return state.model_dump(mode="json")


def _session_ttl_seconds(visibility: str) -> float:
    if visibility == "background":
        return BACKGROUND_SESSION_TTL_SECONDS
    if visibility == "closing":
        return CLOSING_SESSION_TTL_SECONDS
    return FOREGROUND_SESSION_TTL_SECONDS


class _TabSession:
    def __init__(self, *, user_id: str, tab_session_id: str) -> None:
        self.user_id = user_id
        self.tab_session_id = tab_session_id
        self._lock = threading.RLock()
        self._state: TabSessionStateRequest | None = None
        self._revision = 0
        self._visibility = "foreground"
        self._active_connection_id: str | None = None
        self._events: deque[_ReplayEvent] = deque(maxlen=REPLAY_BUFFER_MAX_EVENTS)
        self._stream_seq = 0
        self._subscriptions: dict[str, _SubscriptionRuntime] = {}
        self._deleted = False
        self._last_touched_mono = time.monotonic()
        self._last_applied_at = _utc_now_iso()

    def _touch_unlocked(self) -> None:
        self._last_touched_mono = time.monotonic()

    def _append_event_unlocked(
        self,
        *,
        op: Literal["snapshot", "append", "control", "error"],
        payload: dict[str, Any],
        source: dict[str, Any] | None = None,
        source_version: int | None = None,
        cursor: str | None = None,
    ) -> _ReplayEvent:
        self._stream_seq += 1
        event: _ReplayEvent = {
            "v": 1,
            "stream_seq": self._stream_seq,
            "session_id": self.tab_session_id,
            "config_revision": self._revision,
            "emitted_at": _utc_now_iso(),
            "source": source,
            "op": op,
            "source_version": source_version,
            "cursor": cursor,
            "payload": payload,
        }
        self._events.append(event)
        return event

    def apply_state(self, state: TabSessionStateRequest) -> TabSessionApplyResult:
        with self._lock:
            if self._deleted:
                raise TabSessionNotFoundError(f"Tab session not found: {self.tab_session_id}")
            if state.revision <= self._revision:
                if (
                    state.revision == self._revision
                    and self._state is not None
                    and _state_json(state) == _state_json(self._state)
                ):
                    self._touch_unlocked()
                    return TabSessionApplyResult(
                        tab_session_id=self.tab_session_id,
                        revision=self._revision,
                        applied_at=self._last_applied_at,
                        subscription_count=len(self._subscriptions),
                    )
                raise TabSessionRevisionConflictError(
                    f"stale revision: current={self._revision}, requested={state.revision}"
                )

            old_subscriptions = _build_subscription_index(self._state)
            old_visibility = self._visibility
            self._state = state
            self._revision = state.revision
            self._visibility = state.lifecycle.visibility
            self._touch_unlocked()
            new_subscriptions = _build_subscription_index(self._state)
            self._reconcile_subscriptions_unlocked(state.subscriptions, force_immediate=old_visibility != self._visibility)

            added = sorted(set(new_subscriptions.keys()) - set(old_subscriptions.keys()))
            removed = sorted(set(old_subscriptions.keys()) - set(new_subscriptions.keys()))
            changed = sorted(
                key
                for key in (set(old_subscriptions.keys()) & set(new_subscriptions.keys()))
                if old_subscriptions[key] != new_subscriptions[key]
            )

            event = self._append_event_unlocked(
                op="control",
                payload={
                    "type": "state_applied",
                    "added_subscriptions": added,
                    "removed_subscriptions": removed,
                    "changed_subscriptions": changed,
                    "subscription_count": len(new_subscriptions),
                },
            )
            self._last_applied_at = event["emitted_at"]

            return TabSessionApplyResult(
                tab_session_id=self.tab_session_id,
                revision=self._revision,
                applied_at=event["emitted_at"],
                subscription_count=len(new_subscriptions),
            )

    def _reconcile_subscriptions_unlocked(
        self,
        subscriptions: list[TabSessionSubscription],
        *,
        force_immediate: bool,
    ) -> None:
        source_registry = self._source_registry()
        next_runtimes: dict[str, _SubscriptionRuntime] = {}
        for subscription in subscriptions:
            previous = self._subscriptions.get(subscription.subscription_id)
            if previous is None:
                next_runtimes[subscription.subscription_id] = _SubscriptionRuntime(
                    subscription=subscription,
                    generation=1,
                    pending_immediate=True,
                )
                continue

            previous_dump = previous.subscription.model_dump(mode="json")
            next_dump = subscription.model_dump(mode="json")
            if previous_dump == next_dump:
                next_runtimes[subscription.subscription_id] = _SubscriptionRuntime(
                    subscription=subscription,
                    generation=previous.generation,
                    source_version=previous.source_version,
                    last_payload_json=previous.last_payload_json,
                    last_polled_mono=previous.last_polled_mono,
                    pending_immediate=previous.pending_immediate or force_immediate,
                    source_state=previous.source_state,
                )
                continue

            source_registry.cleanup(previous.subscription, previous.source_state)
            next_runtimes[subscription.subscription_id] = _SubscriptionRuntime(
                subscription=subscription,
                generation=previous.generation + 1,
                pending_immediate=True,
            )
        for subscription_id, previous in self._subscriptions.items():
            if subscription_id not in next_runtimes:
                source_registry.cleanup(previous.subscription, previous.source_state)
        if self._visibility != "foreground":
            for runtime in next_runtimes.values():
                source_registry.cleanup(runtime.subscription, runtime.source_state)
                runtime.source_state = None
                runtime.pending_immediate = True
        self._subscriptions = next_runtimes

    @staticmethod
    def _source_registry() -> _SourceRegistryProtocol:
        from interfaces_backend.services.tab_realtime_sources import get_tab_realtime_source_registry

        return get_tab_realtime_source_registry()

    def open_stream(self, *, last_event_id: int | None) -> tuple[str, list[_ReplayEvent]]:
        with self._lock:
            if self._deleted:
                raise TabSessionNotFoundError(f"Tab session not found: {self.tab_session_id}")

            connection_id = uuid4().hex
            self._active_connection_id = connection_id
            self._touch_unlocked()

            if (
                last_event_id is not None
                and self._events
                and last_event_id < self._events[0]["stream_seq"] - 1
            ):
                self._append_event_unlocked(
                    op="control",
                    payload={
                        "type": "replay_gap",
                        "last_event_id": last_event_id,
                        "oldest_available_event_id": self._events[0]["stream_seq"],
                    },
                )

            self._append_event_unlocked(
                op="control",
                payload={
                    "type": "stream_connected",
                    "connection_id": connection_id,
                },
            )

            if last_event_id is None:
                replay = list(self._events)
            else:
                replay = [event for event in self._events if event["stream_seq"] > last_event_id]
            return connection_id, replay

    async def poll_events(
        self,
        *,
        connection_id: str,
        after_seq: int,
        source_registry: _SourceRegistryProtocol,
    ) -> tuple[_PollStatus, list[_ReplayEvent]]:
        pending: list[tuple[str, int, TabSessionSubscription]] = []
        now_mono = time.monotonic()
        with self._lock:
            self._touch_unlocked()
            if self._active_connection_id != connection_id:
                return "superseded", []
            existing_events = [event for event in self._events if event["stream_seq"] > after_seq]
            if self._deleted:
                return "deleted", []
            if self._visibility != "foreground":
                if existing_events:
                    return "events", existing_events
                return "idle", []
            for subscription_id, runtime in self._subscriptions.items():
                interval = source_registry.interval_for(runtime.subscription)
                should_poll = runtime.pending_immediate or runtime.last_polled_mono == 0.0
                if not should_poll and (now_mono - runtime.last_polled_mono) >= interval:
                    should_poll = True
                if should_poll:
                    pending.append(
                        (
                            subscription_id,
                            runtime.generation,
                            runtime.subscription,
                            runtime.source_state,
                        )
                    )

        for subscription_id, generation, subscription, source_state in pending:
            result = await source_registry.poll(subscription, source_state)
            with self._lock:
                current_runtime = self._subscriptions.get(subscription_id)
                if current_runtime is None or current_runtime.generation != generation:
                    source_registry.cleanup(subscription, result.next_state)
                    continue
                if self._active_connection_id != connection_id or self._deleted:
                    source_registry.cleanup(subscription, result.next_state)
                    return "superseded", []
                current_runtime.last_polled_mono = time.monotonic()
                current_runtime.pending_immediate = False
                current_runtime.source_state = result.next_state
                source_meta = {
                    "subscription_id": subscription.subscription_id,
                    "kind": subscription.kind,
                    "params": subscription.params.model_dump(mode="json"),
                    "generation": current_runtime.generation,
                }
                if result.close_state:
                    source_registry.cleanup(subscription, current_runtime.source_state)
                    current_runtime.source_state = None
                if result.error is not None:
                    error_payload = {"message": result.error}
                    encoded_error = json.dumps(error_payload, ensure_ascii=False, sort_keys=True)
                    if encoded_error == current_runtime.last_payload_json:
                        continue
                    current_runtime.last_payload_json = encoded_error
                    self._append_event_unlocked(
                        op="error",
                        source=source_meta,
                        payload=error_payload,
                    )
                    continue
                payload = result.payload or {}
                encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                if result.op != "append" and encoded == current_runtime.last_payload_json:
                    continue
                if result.op != "append":
                    current_runtime.last_payload_json = encoded
                current_runtime.source_version += 1
                self._append_event_unlocked(
                    op=result.op,
                    source=source_meta,
                    source_version=current_runtime.source_version,
                    cursor=result.cursor,
                    payload=payload,
                )

        await asyncio.sleep(0)
        with self._lock:
            if self._active_connection_id != connection_id:
                return "superseded", []
            events = [event for event in self._events if event["stream_seq"] > after_seq]
            if events:
                return "events", events
            if self._deleted:
                return "deleted", []
            return "idle", []

    def close_stream(self, connection_id: str) -> None:
        with self._lock:
            if self._active_connection_id == connection_id:
                self._active_connection_id = None
                source_registry = self._source_registry()
                for runtime in self._subscriptions.values():
                    source_registry.cleanup(runtime.subscription, runtime.source_state)
                    runtime.source_state = None
                    runtime.pending_immediate = True
                self._touch_unlocked()

    def current_state(self) -> TabSessionStateResponse:
        with self._lock:
            if self._deleted or self._state is None:
                raise TabSessionNotFoundError(f"Tab session not found: {self.tab_session_id}")
            return TabSessionStateResponse(
                tab_session_id=self.tab_session_id,
                revision=self._revision,
                lifecycle=self._state.lifecycle,
                route=self._state.route,
                subscriptions=self._state.subscriptions,
            )

    def mark_deleted(self, *, reason: str) -> None:
        with self._lock:
            if self._deleted:
                return
            source_registry = self._source_registry()
            for runtime in self._subscriptions.values():
                source_registry.cleanup(runtime.subscription, runtime.source_state)
                runtime.source_state = None
            self._append_event_unlocked(
                op="control",
                payload={
                    "type": "session_deleted",
                    "reason": reason,
                },
            )
            self._deleted = True
            self._active_connection_id = None
            self._touch_unlocked()

    def is_expired(self, *, now_mono: float) -> bool:
        with self._lock:
            if self._active_connection_id is not None:
                return False
            ttl = _session_ttl_seconds(self._visibility)
            return (now_mono - self._last_touched_mono) >= ttl


class TabRealtimeRegistry:
    """Tab-session registry used by realtime control + stream API."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[tuple[str, str], _TabSession] = {}

    def _cleanup_expired_sessions(self) -> None:
        now_mono = time.monotonic()
        expired: list[_TabSession] = []
        with self._lock:
            expired_keys = [
                key
                for key, session in self._sessions.items()
                if session.is_expired(now_mono=now_mono)
            ]
            for key in expired_keys:
                session = self._sessions.pop(key, None)
                if session is not None:
                    expired.append(session)
        for session in expired:
            session.mark_deleted(reason="expired")

    def _session_key(self, *, user_id: str, tab_session_id: str) -> tuple[str, str]:
        return user_id, tab_session_id

    def apply_state(
        self,
        *,
        user_id: str,
        tab_session_id: str,
        state: TabSessionStateRequest,
    ) -> TabSessionApplyResult:
        self._cleanup_expired_sessions()
        with self._lock:
            key = self._session_key(user_id=user_id, tab_session_id=tab_session_id)
            session = self._sessions.get(key)
            if session is None:
                session = _TabSession(user_id=user_id, tab_session_id=tab_session_id)
                self._sessions[key] = session
        return session.apply_state(state)

    def get_state(self, *, user_id: str, tab_session_id: str) -> TabSessionStateResponse:
        self._cleanup_expired_sessions()
        with self._lock:
            key = self._session_key(user_id=user_id, tab_session_id=tab_session_id)
            session = self._sessions.get(key)
        if session is None:
            raise TabSessionNotFoundError(f"Tab session not found: {tab_session_id}")
        return session.current_state()

    def open_stream(
        self,
        *,
        user_id: str,
        tab_session_id: str,
        last_event_id: int | None,
        source_registry: _SourceRegistryProtocol,
    ) -> TabSessionStreamHandle:
        self._cleanup_expired_sessions()
        with self._lock:
            key = self._session_key(user_id=user_id, tab_session_id=tab_session_id)
            session = self._sessions.get(key)
        if session is None:
            raise TabSessionNotFoundError(f"Tab session not found: {tab_session_id}")
        connection_id, replay = session.open_stream(last_event_id=last_event_id)
        return TabSessionStreamHandle(
            session=session,
            connection_id=connection_id,
            replay_events=replay,
            source_registry=source_registry,
        )

    def delete_session(self, *, user_id: str, tab_session_id: str) -> bool:
        self._cleanup_expired_sessions()
        with self._lock:
            key = self._session_key(user_id=user_id, tab_session_id=tab_session_id)
            session = self._sessions.pop(key, None)
        if session is None:
            return False
        session.mark_deleted(reason="deleted")
        return True

    def shutdown(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.mark_deleted(reason="shutdown")


_tab_realtime_registry: TabRealtimeRegistry | None = None
_tab_realtime_registry_lock = threading.Lock()


def get_tab_realtime_registry() -> TabRealtimeRegistry:
    global _tab_realtime_registry
    with _tab_realtime_registry_lock:
        if _tab_realtime_registry is None:
            _tab_realtime_registry = TabRealtimeRegistry()
    return _tab_realtime_registry


def reset_tab_realtime_registry() -> None:
    global _tab_realtime_registry
    with _tab_realtime_registry_lock:
        if _tab_realtime_registry is not None:
            _tab_realtime_registry.shutdown()
        _tab_realtime_registry = None
