"""The error table: exhaustive, labelled, and three body shapes chosen by the refusal."""

from __future__ import annotations

from vendorfake.core.kernel.types import UnitError, UnitErrorKind
from vendorfake.core.kernel.unit import make_request
from vendorfake.lightspeed_k.errors import (
    ENVELOPE_INFO_KEY,
    LIGHTSPEED_K_ERROR_TABLE,
    OAUTH_ERROR_INFO_KEY,
    STATUS_STRING_ENVELOPE,
    TO_GO_CONFLICT_ENVELOPE,
    LightspeedKErrorShaper,
)
from vendorfake.lightspeed_k.vendor import LightspeedKVendor

from .conftest import fake_ctx
from .harness import Harness


def test_the_table_covers_every_core_error_kind_with_a_provenance() -> None:
    assert set(LIGHTSPEED_K_ERROR_TABLE) == set(UnitErrorKind)
    for kind, row in LIGHTSPEED_K_ERROR_TABLE.items():
        assert row.provenance in ("documented", "judgment"), kind
        assert 400 <= row.status < 600 and row.title and row.message, kind


def test_unavailable_is_the_one_documented_row() -> None:
    documented = {kind for kind, row in LIGHTSPEED_K_ERROR_TABLE.items() if row.provenance == "documented"}
    assert documented == {UnitErrorKind.UNAVAILABLE}


def test_the_marked_conflict_answers_envelope_c_and_reports_documented() -> None:
    err = UnitError(
        UnitErrorKind.CONFLICT,
        detail="reference has already been used R1",
        field="thirdPartyReference",
        info={ENVELOPE_INFO_KEY: TO_GO_CONFLICT_ENVELOPE},
    )
    shaped = LightspeedKErrorShaper().shape(err, fake_ctx(error_sidecar_mode="headers"))
    assert shaped.status == 409
    assert shaped.body == {"status": "fail", "msg": "reference has already been used R1"}
    with_sidecar = LightspeedKErrorShaper().shape(err, fake_ctx())
    assert with_sidecar.body["unit_error"]["status_provenance"] == "documented"


def test_the_other_409_kinds_and_an_unmarked_conflict_keep_envelope_a() -> None:
    kinds = (
        UnitErrorKind.CONFLICT,
        UnitErrorKind.VERSION_CONFLICT,
        UnitErrorKind.IDEMPOTENCY_CONFLICT,
        UnitErrorKind.INVALID_TRANSITION,
    )
    for kind in kinds:
        shaped = LightspeedKErrorShaper().shape(UnitError(kind), fake_ctx(error_sidecar_mode="headers"))
        assert shaped.status == 409
        assert set(shaped.body) == {"status", "error", "message"}, kind
        assert LightspeedKErrorShaper().shape(UnitError(kind), fake_ctx()).body["unit_error"]["status_provenance"] == (
            "judgment"
        ), kind


def test_envelope_a_has_status_error_message_and_no_timestamp_or_path() -> None:
    shaped = LightspeedKErrorShaper().shape(
        UnitError(UnitErrorKind.NOT_FOUND, detail="Menu 1 was not found."), fake_ctx()
    )
    assert shaped.status == 404
    assert set(shaped.body) == {"status", "error", "message", "unit_error"}
    assert (shaped.body["status"], shaped.body["error"], shaped.body["message"]) == (
        404,
        "Not Found",
        "Menu 1 was not found.",
    )
    bare = LightspeedKErrorShaper().shape(UnitError(UnitErrorKind.NOT_FOUND), fake_ctx(error_sidecar_mode="headers"))
    assert set(bare.body) == {"status", "error", "message"}


def test_unavailable_answers_envelope_b_with_a_string_status() -> None:
    shaped = LightspeedKErrorShaper().shape(
        UnitError(UnitErrorKind.UNAVAILABLE), fake_ctx(error_sidecar_mode="headers")
    )
    assert shaped.status == 503
    assert shaped.body == {"status": "503", "message": "Service unavailable.", "apiSubExceptions": []}


def test_the_envelope_key_selects_the_string_status_body() -> None:
    info = {ENVELOPE_INFO_KEY: STATUS_STRING_ENVELOPE, "rejected_value": "X"}
    err = UnitError(UnitErrorKind.INVALID_VALUE, detail="d", field="items.0.sku", info=info)
    shaped = LightspeedKErrorShaper().shape(err, fake_ctx(error_sidecar_mode="headers"))
    assert shaped.status == 400
    assert shaped.body == {
        "status": "400",
        "message": "d",
        "apiSubExceptions": [{"field": "items.0.sku", "rejectedValue": "X", "message": "d"}],
    }
    missing = UnitError(UnitErrorKind.NOT_FOUND, detail="gone", info={ENVELOPE_INFO_KEY: STATUS_STRING_ENVELOPE})
    shaped = LightspeedKErrorShaper().shape(missing, fake_ctx(error_sidecar_mode="headers"))
    assert shaped.status == 404
    assert shaped.body == {"status": "404", "message": "gone", "apiSubExceptions": []}


def test_without_the_key_envelope_a_is_unchanged() -> None:
    for err in (
        UnitError(UnitErrorKind.INVALID_VALUE, detail="d", field="items.0.sku", info={"rejected_value": "X"}),
        UnitError(UnitErrorKind.NOT_FOUND, detail="gone"),
        UnitError(UnitErrorKind.FORBIDDEN_SCOPE),
    ):
        shaped = LightspeedKErrorShaper().shape(err, fake_ctx(error_sidecar_mode="headers"))
        assert set(shaped.body) == {"status", "error", "message"}, err.kind
        assert type(shaped.body["status"]) is int and shaped.body["status"] == shaped.status, err.kind


def test_the_oauth_key_selects_the_rfc_body_and_invalid_client_adds_basic() -> None:
    err = UnitError(UnitErrorKind.UNAUTHORIZED, detail="no", info={OAUTH_ERROR_INFO_KEY: "invalid_client"})
    shaped = LightspeedKErrorShaper().shape(err, fake_ctx(error_sidecar_mode="headers"))
    assert shaped.status == 401
    assert shaped.body == {"error": "invalid_client", "error_description": "no"}
    assert shaped.headers["www-authenticate"] == "Basic"
    grant = UnitError(UnitErrorKind.INVALID_VALUE, detail="used", info={OAUTH_ERROR_INFO_KEY: "invalid_grant"})
    shaped = LightspeedKErrorShaper().shape(grant, fake_ctx(error_sidecar_mode="headers"))
    assert shaped.status == 400 and shaped.body["error"] == "invalid_grant"
    assert "www-authenticate" not in shaped.headers


def test_describe_publishes_twenty_rows() -> None:
    assert len(LightspeedKErrorShaper().describe()) == len(UnitErrorKind) == 20


def test_describing_twice_is_equal_and_draws_nothing() -> None:
    vendor = LightspeedKVendor()
    before = vendor.ids.draw_count
    err = UnitError(UnitErrorKind.UNAVAILABLE)
    first = vendor.errors.shape(err, fake_ctx(), describing=True)
    second = vendor.errors.shape(err, fake_ctx(), describing=True)
    assert first == second
    assert vendor.ids.draw_count == before


def test_not_found_names_the_routes_listing() -> None:
    req = make_request(method="GET", path="/nowhere")
    shaped = LightspeedKErrorShaper().not_found(req, fake_ctx())
    assert shaped.status == 404 and "GET /__unit/routes" in shaped.body["message"]


def test_a_control_plane_duplicate_subscription_is_a_judgment_409_not_the_to_go_envelope(h: Harness) -> None:
    payload = {"id": "CP-DUP", "notification_url": "http://127.0.0.1:1/x", "signature_key": "k", "event_types": ["*"]}
    assert h.api.post("/__unit/webhooks/subscriptions", payload).status == 201
    res = h.api.post("/__unit/webhooks/subscriptions", payload)
    assert res.status == 409, res.text
    body = res.json()
    assert set(body) == {"status", "error", "message", "unit_error"}
    assert body["status"] == 409 and body["error"] == "Conflict"
    assert body["unit_error"]["kind"] == "conflict"
    assert body["unit_error"]["status_provenance"] == "judgment"
    assert "envelope" not in body["unit_error"]
