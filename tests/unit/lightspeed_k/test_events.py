"""Order rows to order notifications (source.json webhooks "apeOrder notification": the schema's names and the
examples successfulWithoutAccountInfo / succesfulWithAccount, failure, readyForPickUp), routed by endpointId."""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit.lightspeed_k.harness import Harness
from vendorfake.core.kernel.types import EventMeta, JournalEntry
from vendorfake.core.webhooks.models import matches_event_type
from vendorfake.lightspeed_k.entities import COL
from vendorfake.lightspeed_k.events import (
    LIGHTSPEED_K_EVENT_TYPES,
    ORDER_STATUSES,
    LightspeedKEventMapper,
    endpoint_pattern,
    event_type,
)

META = EventMeta(event_id="e1", created_at="2026-10-29T12:00:00.000Z")


class Recorder:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, Any]] = []

    def debug(self, msg: str, fields: Any = None) -> None: ...
    def info(self, msg: str, fields: Any = None) -> None: ...
    def error(self, msg: str, fields: Any = None) -> None: ...

    def warn(self, msg: str, fields: Any = None) -> None:
        self.warnings.append((msg, fields))


class Ctx:
    """The unit's own store, with a recording logger."""

    def __init__(self, h: Harness) -> None:
        self.store = h.unit.context.store
        self.log = Recorder()


def _row(status: str, *, order_id: str = "order-1", endpoint: str = "MY-ENDPOINT") -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": order_id,
        "status": status,
        "thirdPartyReference": "unit-k-order-1",
        "businessLocationId": 100000000101,
        "endpointId": endpoint,
        "created_at_ms": 0,
    }
    if status == "FAILURE":
        row["reason"] = "Unknown SKU UNITK-404 at business location 100000000101"
    else:
        row["ikentooAccountIdentifier"] = "A12345.6"
    return row


def _entry(op: str, *, order_id: str = "order-1", changed: tuple[str, ...] = (), collection: str = COL.orders):
    return JournalEntry(
        seq=1,
        at="2026-10-29T12:00:00.000Z",
        collection=collection,
        id=order_id,
        op=op,  # type: ignore[arg-type]
        from_version=None,
        to_version=1,
        changed=changed,
    )


def _store(h: Harness, row: dict[str, Any]) -> None:
    h.unit.context.store.collection(COL.orders).insert(row, {"operation_id": "test"})


def test_the_status_vocabulary_is_the_documented_enum() -> None:
    assert {
        "SUCCESS",
        "FAILURE",
        "IN_DELIVERY",
        "READY_FOR_PICKUP",
        "CLOSED",
        "ABANDONED",
        "CANCELLED",
    } == ORDER_STATUSES
    assert "CHECK_WAS_UPDATED" not in ORDER_STATUSES
    assert len(LIGHTSPEED_K_EVENT_TYPES) == len(ORDER_STATUSES)


def test_a_success_insert_maps_to_one_event_in_the_success_shape(h: Harness) -> None:
    _store(h, _row("SUCCESS"))
    (event,) = LightspeedKEventMapper().map(_entry("insert"), Ctx(h))  # type: ignore[arg-type]
    assert event.type == "order:SUCCESS:MY-ENDPOINT"
    assert event.entity_id == "order-1"
    body = event.build(META)
    assert set(body) == {"thirdPartyReference", "businessLocationId", "status", "ikentooAccountIdentifier", "type"}
    assert body["type"] == "ORDER" and body["status"] == "SUCCESS"


def test_a_failure_insert_maps_to_the_failure_shape(h: Harness) -> None:
    _store(h, _row("FAILURE"))
    (event,) = LightspeedKEventMapper().map(_entry("insert"), Ctx(h))  # type: ignore[arg-type]
    body = event.build(META)
    assert body == {
        "status": "FAILURE",
        "reason": "Unknown SKU UNITK-404 at business location 100000000101",
        "thirdPartyReference": "unit-k-order-1",
    }


def test_only_a_status_update_maps(h: Harness) -> None:
    _store(h, _row("READY_FOR_PICKUP"))
    mapper, ctx = LightspeedKEventMapper(), Ctx(h)
    (event,) = mapper.map(_entry("update", changed=("status",)), ctx)  # type: ignore[arg-type]
    assert event.type == "order:READY_FOR_PICKUP:MY-ENDPOINT"
    assert event.build(META)["status"] == "READY_FOR_PICKUP"
    assert tuple(mapper.map(_entry("update", changed=("orderNote",)), ctx)) == ()  # type: ignore[arg-type]
    assert tuple(mapper.map(_entry("delete"), ctx)) == ()  # type: ignore[arg-type]


def test_an_off_enum_status_maps_to_nothing_and_warns(h: Harness) -> None:
    _store(h, _row("CHECK_WAS_UPDATED"))
    ctx = Ctx(h)
    assert tuple(LightspeedKEventMapper().map(_entry("update", changed=("status",)), ctx)) == ()  # type: ignore[arg-type]
    assert ctx.log.warnings and "order-1" in repr(ctx.log.warnings) and "CHECK_WAS_UPDATED" in repr(ctx.log.warnings)


def test_other_collections_and_missing_rows_map_to_nothing(h: Harness) -> None:
    ctx = Ctx(h)
    assert tuple(LightspeedKEventMapper().map(_entry("insert", collection=COL.menus), ctx)) == ()  # type: ignore[arg-type]
    assert tuple(LightspeedKEventMapper().map(_entry("insert", order_id="absent"), ctx)) == ()  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mine", "other"),
    [("A*", "AB"), ("A:B", "A"), ("A/B", "A"), ("A.B", "AxB"), ("*", "ANY"), ("a", "A")],
)
def test_an_endpoint_pattern_matches_only_its_own_events(mine: str, other: str) -> None:
    for status in ORDER_STATUSES:
        assert matches_event_type([endpoint_pattern(mine)], event_type(status, mine))
        assert not matches_event_type([endpoint_pattern(mine)], event_type(status, other))
        assert not matches_event_type([endpoint_pattern(other)], event_type(status, mine))


def test_the_body_never_carries_the_deprecated_or_example_only_names(h: Harness) -> None:
    for index, status in enumerate(sorted(ORDER_STATUSES)):
        order_id = f"order-{index}"
        _store(h, _row(status, order_id=order_id))
        (event,) = LightspeedKEventMapper().map(_entry("insert", order_id=order_id), Ctx(h))  # type: ignore[arg-type]
        body = event.build(META)
        assert not {"ikentooAccountId", "iKentooAccountId", "account"} & set(body)


# The example payloads' member names in source.json's webhooks "apeOrder notification", minus the account snapshot
# (never attached) and ikentooAccountId (the examples' spelling of the deprecated iKentooAccountId, never sent).
SUCCESS_EXAMPLE_KEYS = {"thirdPartyReference", "businessLocationId", "status", "ikentooAccountIdentifier", "type"}
FAILURE_EXAMPLE_KEYS = {"status", "reason", "thirdPartyReference"}


@pytest.mark.parametrize(
    ("status", "keys"),
    [
        ("SUCCESS", SUCCESS_EXAMPLE_KEYS),
        ("READY_FOR_PICKUP", SUCCESS_EXAMPLE_KEYS),
        ("CLOSED", SUCCESS_EXAMPLE_KEYS),
        ("FAILURE", FAILURE_EXAMPLE_KEYS),
    ],
)
def test_each_body_has_exactly_its_example_members(h: Harness, status: str, keys: set[str]) -> None:
    _store(h, _row(status))
    (event,) = LightspeedKEventMapper().map(_entry("insert"), Ctx(h))  # type: ignore[arg-type]
    assert set(event.build(META)) == keys
