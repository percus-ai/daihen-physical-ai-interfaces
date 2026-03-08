"""Typed source registry for tab-session realtime streams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Response

from interfaces_backend.models.realtime import (
    ProfilesActiveSubscription,
    TabSessionSubscription,
    TrainingJobCoreSubscription,
    TrainingJobLogsSubscription,
    TrainingJobMetricsSubscription,
    TrainingJobProvisionSubscription,
)


@dataclass(frozen=True)
class RealtimeSourcePollResult:
    payload: dict[str, Any] | None = None
    error: str | None = None


class TabRealtimeSourceRegistry:
    """Resolves supported subscriptions to typed async source handlers."""

    def interval_for(self, subscription: TabSessionSubscription) -> float:
        if isinstance(subscription, ProfilesActiveSubscription):
            return 5.0
        if isinstance(subscription, TrainingJobProvisionSubscription):
            return 2.0
        if isinstance(subscription, TrainingJobCoreSubscription):
            return 5.0
        if isinstance(subscription, TrainingJobMetricsSubscription):
            return 5.0
        if isinstance(subscription, TrainingJobLogsSubscription):
            return 1.0
        raise RuntimeError(f"Unsupported subscription type: {type(subscription).__name__}")

    async def poll(self, subscription: TabSessionSubscription) -> RealtimeSourcePollResult:
        try:
            if isinstance(subscription, ProfilesActiveSubscription):
                from interfaces_backend.api.profiles import get_active_profile_status

                snapshot = await get_active_profile_status()
                return RealtimeSourcePollResult(payload=snapshot.model_dump(mode="json"))

            if isinstance(subscription, TrainingJobCoreSubscription):
                from interfaces_backend.api.training import get_job

                snapshot = await get_job(subscription.params.job_id)
                payload = snapshot.model_dump(mode="json")
                payload.pop("provision_operation", None)
                return RealtimeSourcePollResult(payload=payload)

            if isinstance(subscription, TrainingJobProvisionSubscription):
                from interfaces_backend.api.training import get_job_provision_operation

                try:
                    snapshot = await get_job_provision_operation(subscription.params.job_id)
                except HTTPException as exc:
                    if exc.status_code == 404:
                        return RealtimeSourcePollResult(payload={"provision_operation": None})
                    raise
                return RealtimeSourcePollResult(
                    payload={"provision_operation": snapshot.model_dump(mode="json")}
                )

            if isinstance(subscription, TrainingJobMetricsSubscription):
                from interfaces_backend.api.training import get_job_metrics

                snapshot = await get_job_metrics(
                    job_id=subscription.params.job_id,
                    response=Response(),
                    limit=subscription.params.limit or 1000,
                )
                return RealtimeSourcePollResult(payload=snapshot.model_dump(mode="json"))

            if isinstance(subscription, TrainingJobLogsSubscription):
                return RealtimeSourcePollResult(
                    error="training.job.logs is not implemented in tab-session realtime yet"
                )
        except HTTPException as exc:
            return RealtimeSourcePollResult(error=f"{exc.status_code}: {exc.detail}")
        except Exception as exc:  # noqa: BLE001
            return RealtimeSourcePollResult(error=str(exc))

        return RealtimeSourcePollResult(error=f"Unsupported subscription kind: {subscription.kind}")


_tab_realtime_source_registry: TabRealtimeSourceRegistry | None = None


def get_tab_realtime_source_registry() -> TabRealtimeSourceRegistry:
    global _tab_realtime_source_registry
    if _tab_realtime_source_registry is None:
        _tab_realtime_source_registry = TabRealtimeSourceRegistry()
    return _tab_realtime_source_registry
