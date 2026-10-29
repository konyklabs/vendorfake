"""JUDGMENT, all of it: K-Series documents no retry policy (NOT FOUND, source.json and the tutorial, fetched 2026-10-29)."""

from __future__ import annotations

from collections.abc import Mapping

from vendorfake.core.config.models import ProfileDocument, RetryPolicy, WebhooksSection
from vendorfake.core.webhooks.models import DeliveryOutcome

__all__ = [
    "CONTENT_TYPE",
    "INITIAL_DELIVERY_HEADER",
    "LIGHTSPEED_K_RETRY_SCHEDULE_MS",
    "LIGHTSPEED_K_TIMEOUT_MS",
    "LIGHTSPEED_K_TIME_SCALE",
    "RETRY_NUMBER_HEADER",
    "RETRY_REASONS",
    "RETRY_REASON_HEADER",
    "lightspeed_k_retry_defaults",
]

LIGHTSPEED_K_RETRY_SCHEDULE_MS: tuple[int, ...] = (60_000, 300_000, 900_000, 3_600_000)
LIGHTSPEED_K_TIME_SCALE = 1 / 6000
LIGHTSPEED_K_TIMEOUT_MS = 10_000
CONTENT_TYPE = "application/json"  # DOCUMENTED source.json: the webhook requestBody media type
INITIAL_DELIVERY_HEADER = "x-vendorfake-initial-delivery"
RETRY_NUMBER_HEADER = "x-vendorfake-retry-number"
RETRY_REASON_HEADER = "x-vendorfake-retry-reason"
RETRY_REASONS: Mapping[DeliveryOutcome, str] = {outcome: outcome.value for outcome in DeliveryOutcome}


def lightspeed_k_retry_defaults() -> ProfileDocument:
    return ProfileDocument(
        webhooks=WebhooksSection(
            retry=RetryPolicy(
                schedule_ms=LIGHTSPEED_K_RETRY_SCHEDULE_MS,
                time_scale=LIGHTSPEED_K_TIME_SCALE,
                timeout_ms=LIGHTSPEED_K_TIMEOUT_MS,
            )
        )
    )
