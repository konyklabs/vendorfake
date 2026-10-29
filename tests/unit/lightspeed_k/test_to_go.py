"""POST /o/op/1/order/toGo (source.json apePlaceToGoOrder; the tutorial's Part 3 B and Part 4)."""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from tests.unit.lightspeed_k.conftest import VIRTUAL
from tests.unit.lightspeed_k.harness import TO_GO, Harness
from vendorfake.lightspeed_k.entities import COL
from vendorfake.lightspeed_k.seed.constants import (
    SEED_BUSINESS_LOCATION_ID,
    SEED_ITEM_SKUS,
    SEED_UNKNOWN_SKU,
)
from vendorfake.lightspeed_k.vendor import LightspeedKVendor

# The tutorial's To Go body, Part 3 B, with this unit's seeded location and SKUs.
TUTORIAL: dict[str, Any] = {
    "accountProfileCode": "AAP-TOGO",
    "businessLocationId": SEED_BUSINESS_LOCATION_ID,
    "thirdPartyReference": "unit-k-order-1",
    "endpointId": "UNIT-K-ENDPOINT",
    "customerInfo": {"firstName": "Jane"},
    "items": [{"quantity": 2, "sku": SEED_ITEM_SKUS[0]}, {"quantity": 2, "sku": SEED_ITEM_SKUS[1]}],
    "takeAway": True,
}


def body(**changes: Any) -> dict[str, Any]:
    built = copy.deepcopy(TUTORIAL)
    built.update(changes)
    return built


def without(*path: str) -> dict[str, Any]:
    built = copy.deepcopy(TUTORIAL)
    target = built
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    return built


def wire(res: Any) -> dict[str, Any]:
    return {key: value for key, value in res.json().items() if key != "unit_error"}


def orders(h: Harness) -> list[dict[str, Any]]:
    return list(h.unit.context.store.collection(COL.orders).all())


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (without("businessLocationId"), "businessLocationId"),
        (without("thirdPartyReference"), "thirdPartyReference"),
        (without("endpointId"), "endpointId"),
        (without("customerInfo"), "customerInfo"),
        (without("customerInfo", "firstName"), "customerInfo.firstName"),
        (body(items=[{"sku": "UNITK-001"}]), "items.0.quantity"),
        (body(items=[{"quantity": 1}]), "items.0.sku"),
        (body(payment={"paymentMethod": "OOPAYMENT"}), "payment.paymentAmount"),
    ],
)
def test_a_missing_required_member_is_missing_field(h: Harness, payload: dict[str, Any], field: str) -> None:
    res = h.post(TO_GO, payload)
    assert res.status == 400, res.text
    assert res.json()["unit_error"]["kind"] == "missing_field"
    assert res.json()["unit_error"]["field"] == field


FUTURE = "2026-10-29T13:00:00.000+00:00"


@pytest.mark.parametrize(
    "payload",
    [
        body(thirdPartyReference="R" * 49),
        body(thirdPartyReference=""),
        body(customerInfo={"firstName": "F" * 129}),
        body(customerInfo={"firstName": ""}),
        body(items=[{"quantity": 1, "sku": "S" * 26}]),
        body(items=[{"quantity": "1", "sku": "UNITK-001"}]),
        body(businessLocationId=str(SEED_BUSINESS_LOCATION_ID)),
        body(collectionCode="ABCDEFGHI"),
        body(scheduledTimeForOrderAsIso8601="2026-10-29T11:00:00.000+00:00"),
        body(scheduledTimeForOrderAsIso8601="2026-10-29T13:00:00.000"),
        body(orderCollectionTimeAsIso8601="2026-10-29T11:59:59.000+00:00"),
        body(orderCollectionTimeAsIso8601="not a time"),
        body(maxTimeToAttemptOrderDeliverToPos=59999),
        body(
            items=[{"quantity": 1, "sku": "UNITK-001", "discountAmountOverride": 1.0, "discountPercentOverride": 5.0}]
        ),
    ],
)
def test_a_documented_constraint_is_invalid_value(virtual: Harness, payload: dict[str, Any]) -> None:
    res = virtual.post(TO_GO, payload)
    assert res.status == 400, res.text
    assert res.json()["unit_error"]["kind"] == "invalid_value"
    assert orders(virtual) == []


def test_future_times_and_the_minimum_delivery_window_are_accepted(virtual: Harness) -> None:
    payload = body(
        scheduledTimeForOrderAsIso8601=FUTURE,
        orderCollectionTimeAsIso8601="2026-10-29T14:00:00Z",
        maxTimeToAttemptOrderDeliverToPos=60000,
        payment={"paymentAmount": 14, "tipAmount": 2.0},
        collectionCode="ABC-1234",
    )
    res = virtual.post(TO_GO, payload)
    assert res.status == 200, res.text


def test_an_unknown_location_is_404(h: Harness) -> None:
    res = h.post(TO_GO, body(businessLocationId=999))
    assert res.status == 404
    assert res.json()["unit_error"]["reason"] == "unknown_business_location"


def test_the_tutorial_body_with_take_away_answers_ok_and_stores_one_success(h: Harness) -> None:
    res = h.post(TO_GO, TUTORIAL)
    assert res.status == 200, res.text
    assert res.json() == {"status": "ok"}
    (row,) = orders(h)
    assert row["status"] == "SUCCESS" and "reason" not in row
    assert row["thirdPartyReference"] == "unit-k-order-1" and row["endpointId"] == "UNIT-K-ENDPOINT"
    assert row["id"] != row["thirdPartyReference"]
    identifier = row["ikentooAccountIdentifier"]
    head, _, tail = identifier.partition(".")
    assert head[0] == "A" and head[1:].isdigit() and len(head) == 6 and tail in {str(n) for n in range(1, 10)}


def test_a_reused_reference_is_the_documented_409(h: Harness) -> None:
    assert h.post(TO_GO, TUTORIAL).status == 200
    res = h.post(TO_GO, TUTORIAL)
    assert res.status == 409
    assert wire(res) == {"status": "fail", "msg": "reference has already been used unit-k-order-1"}
    assert res.json()["unit_error"]["kind"] == "conflict"
    assert len(orders(h)) == 1


def test_an_unknown_sku_is_a_failure_and_frees_its_reference(h: Harness) -> None:
    failing = body(items=[{"quantity": 1, "sku": SEED_UNKNOWN_SKU}])
    assert h.post(TO_GO, failing).status == 200
    (row,) = orders(h)
    assert row["status"] == "FAILURE"
    assert row["reason"] == f"Unknown SKU {SEED_UNKNOWN_SKU} at business location {SEED_BUSINESS_LOCATION_ID}"
    assert "ikentooAccountIdentifier" not in row
    assert h.post(TO_GO, TUTORIAL).status == 200
    assert sorted(r["status"] for r in orders(h)) == ["FAILURE", "SUCCESS"]


def test_the_published_example_body_is_accepted_three_times(h: Harness) -> None:
    (route,) = [r for r in LightspeedKVendor().routes if r.operation_id == "apePlaceToGoOrder"]
    assert route.example_body is not None
    for _ in range(3):
        res = h.post(TO_GO, dict(route.example_body))
        assert res.status == 200, res.text
    assert [row["status"] for row in orders(h)] == ["FAILURE"] * 3


def test_a_financial_only_token_is_403(h: Harness) -> None:
    assert h.post(TO_GO, TUTORIAL, headers=h.read_auth).status == 403


def test_orders_only_stores_the_order(profile_harness: Callable[..., Iterator[Harness]]) -> None:
    for h in profile_harness("orders-only", env=VIRTUAL):
        assert h.post(TO_GO, TUTORIAL).status == 200
        assert len(orders(h)) == 1
