"""What an endpoint receives: one notification per order status change, to the endpoint the order names, with
HTTP Basic when the endpoint was registered with it (tutorial; source.json webhooks "apeOrder notification")."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from typing import Any

import pytest

from tests.unit.lightspeed_k.harness import TO_GO, WEBHOOK, Harness, harness
from vendorfake.core.webhooks.sink import MemorySink, SinkRequest
from vendorfake.lightspeed_k.entities import COL
from vendorfake.lightspeed_k.retry import LIGHTSPEED_K_RETRY_SCHEDULE_MS, LIGHTSPEED_K_TIME_SCALE
from vendorfake.lightspeed_k.seed.constants import SEED_BUSINESS_LOCATION_ID, SEED_ITEM_SKUS, SEED_UNKNOWN_SKU

URL_A = "https://receiver-a.example.test/hooks"
URL_B = "https://receiver-b.example.test/hooks"


@pytest.fixture
def sink() -> MemorySink:
    return MemorySink()


@pytest.fixture
def d(sink: MemorySink) -> Iterator[Harness]:
    yield from harness(sink=sink)


def register(h: Harness, endpoint: str, url: str, **members: Any) -> None:
    res = h.put(WEBHOOK, {"endpointId": endpoint, "url": url, **members})
    assert res.status == 200, res.text


def order(h: Harness, endpoint: str, *, reference: str = "unit-k-order-1", sku: str = SEED_ITEM_SKUS[0]) -> None:
    res = h.post(
        TO_GO,
        {
            "businessLocationId": SEED_BUSINESS_LOCATION_ID,
            "thirdPartyReference": reference,
            "endpointId": endpoint,
            "customerInfo": {"firstName": "Ada"},
            "items": [{"quantity": 1, "sku": sku}],
        },
    )
    assert res.status == 200, res.text
    h.drain()


def received(sink: MemorySink, url: str | None = None) -> list[SinkRequest]:
    return [request for request in sink.received if url is None or request.url == url]


def payload(request: SinkRequest) -> dict[str, Any]:
    return dict(json.loads(bytes(request.body).decode("utf-8")))


def lowered(request: SinkRequest) -> dict[str, str]:
    return {name.lower(): value for name, value in request.headers.items()}


def order_id(h: Harness, reference: str = "unit-k-order-1") -> str:
    row = h.unit.context.store.collection(COL.orders).find(lambda e: e["thirdPartyReference"] == reference)
    assert row is not None
    return str(row["id"])


def test_an_order_reaches_only_the_endpoint_it_names_in_the_success_shape(d: Harness, sink: MemorySink) -> None:
    register(d, "A", URL_A)
    register(d, "B", URL_B)
    order(d, "A")
    (only,) = received(sink)
    assert only.url == URL_A
    body = payload(only)
    assert set(body) == {"thirdPartyReference", "businessLocationId", "status", "ikentooAccountIdentifier", "type"}
    assert (body["status"], body["type"], body["thirdPartyReference"]) == ("SUCCESS", "ORDER", "unit-k-order-1")
    assert body["businessLocationId"] == SEED_BUSINESS_LOCATION_ID
    headers = lowered(only)
    assert headers["content-type"] == "application/json"
    assert "authorization" not in headers


def test_an_unknown_sku_delivers_the_failure_shape(d: Harness, sink: MemorySink) -> None:
    register(d, "A", URL_A)
    order(d, "A", sku=SEED_UNKNOWN_SKU)
    (only,) = received(sink)
    assert payload(only) == {
        "status": "FAILURE",
        "reason": f"Unknown SKU {SEED_UNKNOWN_SKU} at business location {SEED_BUSINESS_LOCATION_ID}",
        "thirdPartyReference": "unit-k-order-1",
    }


def test_basic_auth_is_the_registered_user_pass(d: Harness, sink: MemorySink) -> None:
    register(d, "A", URL_A, withBasicAuth=True, username="user", password="pass")
    order(d, "A")
    (only,) = received(sink)
    assert lowered(only)["authorization"] == "Basic " + base64.b64encode(b"user:pass").decode()


def test_a_glob_like_endpoint_id_routes_to_itself_only(d: Harness, sink: MemorySink) -> None:
    register(d, "A*", URL_A)
    register(d, "AB", URL_B)
    order(d, "AB")
    assert [request.url for request in received(sink)] == [URL_B]


def test_an_unregistered_endpoint_is_accepted_and_delivers_nothing(d: Harness, sink: MemorySink) -> None:
    order(d, "NOBODY")
    assert received(sink) == []


def test_a_control_plane_wildcard_also_hears_the_order(d: Harness, sink: MemorySink) -> None:
    register(d, "A", URL_A)
    made = d.api.post(
        "/__unit/webhooks/subscriptions",
        {"id": "everything", "notification_url": URL_B, "signature_key": "", "event_types": ["*"]},
    )
    assert made.status == 201, made.text
    order(d, "A")
    assert sorted(request.url for request in received(sink)) == [URL_A, URL_B]


def test_the_pos_stand_in_drives_the_next_status(d: Harness, sink: MemorySink) -> None:
    register(d, "A", URL_A)
    order(d, "A")
    oid = order_id(d)
    res = d.api.post("/__unit/state/update", {"collection": "orders", "id": oid, "patch": {"status": "READY_FOR_PICKUP"}})
    assert res.status == 200, res.text
    d.drain()
    statuses = [payload(request)["status"] for request in received(sink, URL_A)]
    assert statuses == ["SUCCESS", "READY_FOR_PICKUP"]
    bogus = d.api.post("/__unit/state/update", {"collection": "orders", "id": oid, "patch": {"status": "BOGUS"}})
    assert bogus.status == 200
    d.drain()
    assert len(received(sink, URL_A)) == 2


def test_webhooks_off_delivers_nothing_and_back_on_delivers(d: Harness, sink: MemorySink) -> None:
    register(d, "A", URL_A)
    original = [row["name"] for row in d.api.get("/__unit/capabilities").json()["capabilities"] if row["enabled"]]
    off = d.api.post("/__unit/capabilities", {"set": [n for n in original if not n.startswith("webhooks")]})
    assert off.status == 200
    order(d, "A", reference="while-off")
    assert received(sink) == []
    assert d.api.post("/__unit/capabilities", {"set": original}).status == 200
    order(d, "A", reference="back-on")
    assert [payload(request)["thirdPartyReference"] for request in received(sink)] == ["back-on"]


def test_info_publishes_the_judgment_retry_schedule(d: Harness) -> None:
    retry = d.api.get("/__unit/info").json()["webhooks"]["retry"]
    assert tuple(retry["schedule_ms"]) == LIGHTSPEED_K_RETRY_SCHEDULE_MS
    assert retry["time_scale"] == pytest.approx(LIGHTSPEED_K_TIME_SCALE)


def test_an_update_after_queueing_leaves_the_queued_credential(sink: MemorySink) -> None:
    sink.respond_with = lambda request, index: 500 if index == 0 else 200
    for h in harness(sink=sink, env={"VENDORFAKE_CLOCK": "virtual"}):
        register(h, "A", URL_A, withBasicAuth=True, username="user", password="old")
        res = h.post(
            TO_GO,
            {
                "businessLocationId": SEED_BUSINESS_LOCATION_ID,
                "thirdPartyReference": "queued",
                "endpointId": "A",
                "customerInfo": {"firstName": "Ada"},
                "items": [{"quantity": 1, "sku": SEED_ITEM_SKUS[0]}],
            },
        )
        assert res.status == 200
        h.api.post("/__unit/clock/advance", {"ms": 0, "drain": False})
        updated = h.post(
            WEBHOOK, {"endpointId": "A", "url": URL_A, "withBasicAuth": True, "username": "user", "password": "new"}
        )
        assert updated.status == 200
        h.drain()
        old = "Basic " + base64.b64encode(b"user:old").decode()
        assert len(sink.received) >= 2
        assert all(lowered(request)["authorization"] == old for request in sink.received)
