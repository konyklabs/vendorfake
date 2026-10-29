"""The error table: exhaustive, labelled, and three body shapes chosen by the refusal."""

from __future__ import annotations

from vendorfake.core.kernel.types import UnitError, UnitErrorKind
from vendorfake.core.kernel.unit import make_request
from vendorfake.lightspeed_k.errors import (
    LIGHTSPEED_K_ERROR_TABLE,
    OAUTH_ERROR_INFO_KEY,
    LightspeedKErrorShaper,
)
from vendorfake.lightspeed_k.vendor import LightspeedKVendor

from .conftest import fake_ctx


def test_the_table_covers_every_core_error_kind_with_a_provenance() -> None:
    assert set(LIGHTSPEED_K_ERROR_TABLE) == set(UnitErrorKind)
    for kind, row in LIGHTSPEED_K_ERROR_TABLE.items():
        assert row.provenance in ("documented", "judgment"), kind
        assert 400 <= row.status < 600 and row.title and row.message, kind


def test_unavailable_is_the_one_documented_row() -> None:
    documented = {kind for kind, row in LIGHTSPEED_K_ERROR_TABLE.items() if row.provenance == "documented"}
    assert documented == {UnitErrorKind.UNAVAILABLE}


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
