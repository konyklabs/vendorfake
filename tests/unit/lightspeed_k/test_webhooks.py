"""The webhook endpoint CRUD under /o/wh/1/webhook (source.json apeCreateWebhookOo, apeUpdateWebhookOo,
apeGetWebhookOo, apeDeleteWebhookEndpoint; the apeWebhookEndpoint schema)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from tests.unit.lightspeed_k.harness import WEBHOOK, Harness, webhook_path
from vendorfake.core.webhooks.models import SUBSCRIPTION_COLLECTION
from vendorfake.lightspeed_k.events import endpoint_pattern

URL = "https://receiver.example.test/hooks"
ENDPOINT = "UNIT-K-ENDPOINT"


def register(h: Harness, endpoint: str = ENDPOINT, **members: Any) -> Any:
    return h.put(WEBHOOK, {"endpointId": endpoint, "url": URL, **members})


def wire(res: Any) -> dict[str, Any]:
    return {key: value for key, value in res.json().items() if key != "unit_error"}


def stored(h: Harness, endpoint: str = ENDPOINT) -> dict[str, Any] | None:
    return h.unit.context.store.collection(SUBSCRIPTION_COLLECTION).get(endpoint)


def test_put_echoes_every_documented_default(h: Harness) -> None:
    res = register(h)
    assert res.status == 200, res.text
    assert res.json() == {
        "endpointId": ENDPOINT,
        "url": URL,
        "withBasicAuth": False,
        "provideAccount": False,
        "expandTransactions": False,
        "expandPayments": False,
        "subscribeTo": [],
    }
    entity = stored(h)
    assert entity is not None
    assert entity["event_types"] == [endpoint_pattern(ENDPOINT)]
    assert entity["signature_key"] == ""
    assert entity["notification_url"] == URL


def test_basic_credentials_become_the_signature_key_and_the_password_is_echoed(h: Harness) -> None:
    res = register(h, withBasicAuth=True, username="user", password="pass")
    assert res.status == 200, res.text
    assert res.json()["username"] == "user" and res.json()["password"] == "pass"
    entity = stored(h)
    assert entity is not None and entity["signature_key"] == "user:pass"


def test_a_second_put_for_the_same_id_is_400_on_endpoint_id(h: Harness) -> None:
    assert register(h).status == 200
    res = register(h)
    assert res.status == 400
    assert res.json()["unit_error"]["field"] == "endpointId"


def test_endpoint_ids_are_case_sensitive(h: Harness) -> None:
    assert register(h, "MY-ID").status == 200
    assert register(h, "my-id").status == 200
    assert h.get(webhook_path("MY-ID")).json()["endpointId"] == "MY-ID"
    assert h.get(webhook_path("my-id")).json()["endpointId"] == "my-id"


def test_post_resets_the_three_flags_and_keeps_every_other_member(h: Harness) -> None:
    subscribe = [{"name": "DELIVERED", "resource": "order"}]
    created = register(
        h,
        withBasicAuth=True,
        username="user",
        password="pass",
        provideAccount=True,
        expandTransactions=True,
        expandPayments=True,
        subscribeTo=subscribe,
    )
    assert created.status == 200 and created.json()["provideAccount"] is True
    updated = h.post(WEBHOOK, {"endpointId": ENDPOINT, "url": "https://receiver.example.test/other"})
    assert updated.status == 200, updated.text
    expected = {
        "endpointId": ENDPOINT,
        "url": "https://receiver.example.test/other",
        "withBasicAuth": True,
        "username": "user",
        "password": "pass",
        "provideAccount": False,
        "expandTransactions": False,
        "expandPayments": False,
        "subscribeTo": subscribe,
    }
    assert updated.json() == expected
    assert h.get(webhook_path(ENDPOINT)).json() == expected
    entity = stored(h)
    assert entity is not None
    assert entity["notification_url"] == "https://receiver.example.test/other"
    assert entity["signature_key"] == "user:pass"


def test_post_for_an_unknown_id_is_404(h: Harness) -> None:
    res = h.post(WEBHOOK, {"endpointId": "NOPE", "url": URL})
    assert res.status == 404
    assert wire(res)["message"] == "endpoint ID not found for NOPE"


def test_get_for_an_unknown_id_is_the_documented_404(h: Harness) -> None:
    res = h.get(webhook_path("MISSING-ENDPOINT"))
    assert res.status == 404
    assert wire(res) == {"status": 404, "error": "Not Found", "message": "endpoint ID not found for MISSING-ENDPOINT"}


def test_delete_answers_200_empty_then_get_is_404(h: Harness) -> None:
    assert register(h).status == 200
    res = h.delete(webhook_path(ENDPOINT))
    assert res.status == 200
    assert res.text == ""
    assert h.get(webhook_path(ENDPOINT)).status == 404
    assert h.delete(webhook_path(ENDPOINT)).status == 404
    assert stored(h) is None


@pytest.mark.parametrize(
    ("members", "kind", "field"),
    [
        ({"url": "http://169.254.169.254/x"}, "invalid_value", "url"),
        ({"subscribeTo": [{"name": "X", "resource": "nope"}]}, "invalid_value", "subscribeTo.0.resource"),
        ({"withBasicAuth": True, "username": "user"}, "missing_field", "password"),
        ({"withBasicAuth": "yes"}, "invalid_value", "withBasicAuth"),
    ],
)
def test_put_refuses(h: Harness, members: dict[str, Any], kind: str, field: str) -> None:
    res = register(h, **members)
    assert res.status == 400, res.text
    assert res.json()["unit_error"]["kind"] == kind
    assert res.json()["unit_error"]["field"] == field
    assert stored(h) is None


def test_put_without_endpoint_id_or_url_is_missing_field(h: Harness) -> None:
    for payload, field in (({"url": URL}, "endpointId"), ({"endpointId": ENDPOINT}, "url")):
        res = h.put(WEBHOOK, payload)
        assert res.status == 400
        assert res.json()["unit_error"]["field"] == field


def test_a_control_plane_subscriber_reads_back_with_defaults(h: Harness) -> None:
    made = h.api.post(
        "/__unit/webhooks/subscriptions",
        {"id": "CP-ENDPOINT", "notification_url": URL, "signature_key": "k", "event_types": ["*"]},
    )
    assert made.status == 201, made.text
    assert h.get(webhook_path("CP-ENDPOINT")).json() == {
        "endpointId": "CP-ENDPOINT",
        "url": URL,
        "withBasicAuth": False,
        "provideAccount": False,
        "expandTransactions": False,
        "expandPayments": False,
        "subscribeTo": [],
    }


def test_the_routes_are_absent_on_orders_only(profile_harness: Callable[..., Iterator[Harness]]) -> None:
    for h in profile_harness("orders-only"):
        assert register(h).status in (404, 501)
        assert h.get(webhook_path(ENDPOINT)).status in (404, 501)


# DOCUMENTED source.json: all four operations declare security [{OAuth2: [orders-api]}]
CALLS = (
    ("PUT", WEBHOOK, {"endpointId": ENDPOINT, "url": URL}),
    ("POST", WEBHOOK, {"endpointId": ENDPOINT, "url": "https://receiver.example.test/other"}),
    ("GET", webhook_path(ENDPOINT), None),
    ("DELETE", webhook_path(ENDPOINT), None),
)


def call(h: Harness, method: str, path: str, body: Any, headers: dict[str, str]) -> Any:
    if method in ("PUT", "POST"):
        return getattr(h, method.lower())(path, body, headers=headers)
    return getattr(h, method.lower())(path, headers=headers)


@pytest.mark.parametrize(("method", "path", "body"), CALLS, ids=[f"{m} {p}" for m, p, _ in CALLS])
def test_every_endpoint_route_needs_an_orders_api_bearer(h: Harness, method: str, path: str, body: Any) -> None:
    assert register(h, withBasicAuth=True, username="user", password="pass").status == 200
    anonymous = call(h, method, path, body, {})
    assert anonymous.status == 401, anonymous.text
    assert "pass" not in anonymous.text
    forbidden = call(h, method, path, body, h.read_auth)
    assert forbidden.status == 403, forbidden.text
    assert forbidden.json()["unit_error"]["kind"] == "forbidden_scope"
    assert "pass" not in forbidden.text
    entity = stored(h)
    assert entity is not None
    assert entity["notification_url"] == URL and entity["signature_key"] == "user:pass"


def test_post_refuses_a_link_local_url_and_keeps_the_stored_one(h: Harness) -> None:
    assert register(h).status == 200
    res = h.post(WEBHOOK, {"endpointId": ENDPOINT, "url": "http://169.254.169.254/latest/meta-data"})
    assert res.status == 400, res.text
    assert res.json()["unit_error"]["kind"] == "invalid_value"
    assert res.json()["unit_error"]["field"] == "url"
    entity = stored(h)
    assert entity is not None and entity["notification_url"] == URL


@pytest.mark.parametrize("method", ["PUT", "POST"])
def test_an_empty_endpoint_id_is_400_on_endpoint_id(h: Harness, method: str) -> None:
    res = call(h, method, WEBHOOK, {"endpointId": "", "url": URL}, h.auth)
    assert res.status == 400, res.text
    assert res.json()["unit_error"]["kind"] == "invalid_value"
    assert res.json()["unit_error"]["field"] == "endpointId"
    assert stored(h, "") is None
