"""Order rows to order notifications (source.json webhooks "apeOrder notification"); every delivery is journal-derived."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

from vendorfake.core.kernel.types import EventMeta, JournalEntry, MappedEvent, UnitContext
from vendorfake.core.util.json import compact
from vendorfake.lightspeed_k.entities import COL

__all__ = [
    "LIGHTSPEED_K_EVENT_TYPES",
    "ORDER_STATUSES",
    "LightspeedKEventMapper",
    "endpoint_pattern",
    "event_type",
]

# DOCUMENTED source.json: the notification schema's status enum, in its order
_STATUS_ORDER = ("SUCCESS", "FAILURE", "IN_DELIVERY", "READY_FOR_PICKUP", "CLOSED", "ABANDONED", "CANCELLED")
ORDER_STATUSES: frozenset[str] = frozenset(_STATUS_ORDER)


# JUDGMENT: routing travels in the event type; quote() leaves no * : or / for the matcher to read
def event_type(status: str, endpoint_id: str) -> str:
    return f"order:{status}:{quote(endpoint_id, safe='')}"


def endpoint_pattern(endpoint_id: str) -> str:
    return event_type("*", endpoint_id)


LIGHTSPEED_K_EVENT_TYPES: tuple[str, ...] = tuple(f"order:{status}:*" for status in _STATUS_ORDER)


def _payload(row: Mapping[str, Any], status: str) -> dict[str, Any]:
    # DOCUMENTED source.json: the failure example, and apeBaseWebhookInformation plus status/type for the rest
    if status == "FAILURE":
        return compact(
            {"status": status, "reason": row.get("reason"), "thirdPartyReference": row.get("thirdPartyReference")}
        )
    return compact(
        {
            "thirdPartyReference": row.get("thirdPartyReference"),
            "businessLocationId": row.get("businessLocationId"),
            "status": status,
            "ikentooAccountIdentifier": row.get("ikentooAccountIdentifier"),
            "type": "ORDER",
        }
    )


class LightspeedKEventMapper:
    """Satisfies ``EventMapper``: an order insert, or a write that changes its status, is one notification."""

    __slots__ = ()

    def map(self, entry: JournalEntry, ctx: UnitContext) -> Sequence[MappedEvent]:
        if entry.collection != COL.orders or (entry.op == "update" and "status" not in entry.changed):
            return ()
        row = None if entry.op == "delete" else ctx.store.collection(COL.orders).get(entry.id)
        status = None if row is None else row.get("status")
        if row is None or status not in ORDER_STATUSES:
            ctx.log.warn("order notification not mapped", {"id": entry.id, "op": entry.op, "status": status})
            return ()
        body = _payload(row, str(status))

        def build(meta: EventMeta) -> object:
            return body

        return (MappedEvent(type=event_type(str(status), str(row["endpointId"])), entity_id=entry.id, build=build),)
