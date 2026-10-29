"""The V1 token lifecycle: the authorize stand-in and POST /oauth/token (v1-overview, v1-faq)."""

from __future__ import annotations

import base64
import json
import re
from typing import Any

import pytest

from tests.unit.lightspeed_k.harness import BUSINESSES, FORM, TOKEN, Harness, bearer, redirect_query
from vendorfake.lightspeed_k.seed.constants import (
    SEED_ACCESS_TOKEN,
    SEED_CLIENT_ID,
    SEED_CLIENT_SECRET,
    SEED_REDIRECT_URI,
    SEED_REFRESH_TOKEN,
)

UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
V2_BASIC = "Basic " + base64.b64encode(f"devp-v2-unit-client:{SEED_CLIENT_SECRET}".encode()).decode()


def _basic(client_id: str, secret: str) -> str:
    return "Basic " + base64.b64encode(f"{client_id}:{secret}".encode()).decode()


def _reason(res: Any) -> str:
    return str(res.json()["unit_error"]["reason"])


def _arm(h: Harness, fault: str, route: str) -> None:
    rule = {"id": f"{fault}-once", "scope": "request", "fault": fault, "match": {"route": route}, "when": {"times": 1}}
    armed = h.api.post("/__unit/chaos/rules", rule)
    assert armed.status == 200, armed.text


# -- GET /oauth/authorize -----------------------------------------------------


def test_authorize_redirects_with_a_six_character_code_and_the_state(h: Harness) -> None:
    res = h.authorize()
    assert res.status == 302
    location = res.header("location") or ""
    assert location.startswith(f"{SEED_REDIRECT_URI}?code=")
    query = redirect_query(res)
    assert re.fullmatch(r"[A-Za-z0-9]{6}", query["code"])
    assert query["state"] == "opaque-consumer-state"


@pytest.mark.parametrize("name", ["client_id", "redirect_uri", "scope"])
def test_each_missing_parameter_is_400(h: Harness, name: str) -> None:
    res = h.authorize(**{name: None})
    assert res.status == 400
    assert res.json()["error"] == "invalid_request"


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"response_type": "token"}, "response_type_not_code"),
        ({"response_type": None}, "response_type_not_code"),
        ({"redirect_uri": "https://elsewhere.example/cb"}, "redirect_uri_mismatch"),
        ({"client_id": "someone-else"}, "unknown_client"),
        ({"client_id": "devp-v2-unit-client"}, "v2_client_id"),
    ],
)
def test_authorize_refusals_are_400_with_a_reason(h: Harness, overrides: dict[str, str | None], reason: str) -> None:
    res = h.authorize(**overrides)
    assert res.status == 400
    assert _reason(res) == reason


def test_an_unknown_scope_is_invalid_scope(h: Harness) -> None:
    res = h.authorize(scope="orders-api payroll")
    assert res.status == 400
    assert res.json()["error"] == "invalid_scope"


def test_a_plus_separated_scope_is_two_scopes(h: Harness) -> None:
    assert h.authorize(scope="financial-api+orders-api").status == 302


def test_an_armed_denial_redirects_with_access_denied_and_the_state(h: Harness) -> None:
    _arm(h, "authorize_denied", "GET /oauth/authorize")
    res = h.authorize()
    assert res.status == 302
    query = redirect_query(res)
    assert query == {"error": "access_denied", "state": "opaque-consumer-state"}
    assert h.unit.context.store.collection("auth_codes").size == 0


# -- POST /oauth/token: the code exchange ---------------------------------------


def test_the_exchange_answers_exactly_the_five_documented_members(h: Harness) -> None:
    res = h.exchange(h.code())
    assert res.status == 200, res.text
    body = res.json()
    assert list(body) == ["access_token", "token_type", "refresh_token", "expires_in", "scope"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3599
    assert body["scope"] == "financial-api orders-api "
    assert UUID4.fullmatch(body["access_token"]) and UUID4.fullmatch(body["refresh_token"])
    assert h.get(BUSINESSES, headers=bearer(body["access_token"])).status == 200


def test_a_body_only_exchange_is_refused_naming_the_query_rule(h: Harness) -> None:
    code = h.code()
    form = f"grant_type=authorization_code&code={code}&redirect_uri={SEED_REDIRECT_URI}"
    res = h.api.post(TOKEN, form, headers={**FORM, **h.basic})
    assert res.status == 400
    assert res.json()["error"] == "invalid_request"
    assert _reason(res) == "v1_exchange_reads_query_parameters"


def test_a_code_is_single_use(h: Harness) -> None:
    code = h.code()
    assert h.exchange(code).status == 200
    again = h.exchange(code)
    assert again.status == 400 and again.json()["error"] == "invalid_grant"
    assert _reason(again) == "code_used"


def test_a_code_expires_after_ten_minutes(virtual: Harness) -> None:
    code = virtual.code()
    virtual.unit.context.clock.advance(600_001)
    res = virtual.exchange(code)
    assert res.status == 400 and _reason(res) == "code_expired"


def test_an_unknown_code_and_a_wrong_redirect_are_invalid_grant(h: Harness) -> None:
    unknown = h.exchange("ZZZZZZ")
    assert unknown.status == 400 and _reason(unknown) == "code_unknown"
    code = h.code()
    wrong = h.exchange(code, redirect_uri="https://elsewhere.example/cb")
    assert wrong.status == 400 and wrong.json()["error"] == "invalid_grant"
    assert _reason(wrong) == "redirect_uri_mismatch"


@pytest.mark.parametrize(
    "header,reason",
    [
        (None, "no_basic_client_auth"),
        ("Bearer abc", "no_basic_client_auth"),
        ("Basic !!!notbase64", "no_basic_client_auth"),
        ("Basic " + base64.b64encode(b"nocolon").decode(), "no_basic_client_auth"),
        (_basic(SEED_CLIENT_ID, "wrong-secret"), "client_credentials_mismatch"),
        (_basic("someone-else", SEED_CLIENT_SECRET), "client_credentials_mismatch"),
        (V2_BASIC, "v2_client_id"),
    ],
)
def test_client_authentication_refusals_are_401_invalid_client(h: Harness, header: str | None, reason: str) -> None:
    headers = {**FORM, **({"authorization": header} if header else {})}
    res = h.api.post(TOKEN, f"grant_type=refresh_token&refresh_token={SEED_REFRESH_TOKEN}", headers=headers)
    assert res.status == 401
    assert res.json()["error"] == "invalid_client"
    assert res.header("www-authenticate") == "Basic"
    assert _reason(res) == reason


def test_a_missing_and_an_unknown_grant_type(h: Harness) -> None:
    missing = h.api.post(TOKEN, None, headers=h.basic)
    assert missing.status == 400 and missing.json()["error"] == "invalid_request"
    unknown = h.api.post(TOKEN, None, query={"grant_type": "client_credentials"}, headers=h.basic)
    assert unknown.status == 400 and unknown.json()["error"] == "unsupported_grant_type"


# -- POST /oauth/token: the refresh grant ------------------------------------------


def test_a_form_refresh_issues_a_new_pair(h: Harness) -> None:
    res = h.refresh()
    assert res.status == 200, res.text
    body = res.json()
    assert body["access_token"] != SEED_ACCESS_TOKEN and body["refresh_token"] != SEED_REFRESH_TOKEN
    assert h.get(BUSINESSES, headers=bearer(body["access_token"])).status == 200


def test_a_json_refresh_is_accepted_too(h: Harness) -> None:
    body = json.dumps({"grant_type": "refresh_token", "refresh_token": SEED_REFRESH_TOKEN})
    res = h.api.post(TOKEN, body, headers={"content-type": "application/json", **h.basic})
    assert res.status == 200, res.text


def test_a_query_only_refresh_is_refused_naming_the_body_rule(h: Harness) -> None:
    query = {"grant_type": "refresh_token", "refresh_token": SEED_REFRESH_TOKEN}
    res = h.api.post(TOKEN, None, query=query, headers=h.basic)
    assert res.status == 400 and res.json()["error"] == "invalid_request"
    assert _reason(res) == "v1_refresh_reads_form_body"


def test_a_refresh_token_is_single_use_and_the_old_bearer_survives(h: Harness) -> None:
    assert h.refresh().status == 200
    again = h.refresh()
    assert again.status == 400 and again.json()["error"] == "invalid_grant"
    assert _reason(again) == "refresh_token_reused"
    # JUDGMENT (D-010): nothing documents revoking the previous access token.
    assert h.get(BUSINESSES).status == 200


def test_an_unknown_refresh_token_is_invalid_grant(h: Harness) -> None:
    res = h.refresh("not-a-refresh-token")
    assert res.status == 400 and _reason(res) == "refresh_token_unknown"


def test_the_access_token_expires_after_3599_seconds(virtual: Harness) -> None:
    body = virtual.exchange(virtual.code()).json()
    virtual.unit.context.clock.advance(3_599_000)
    res = virtual.get(BUSINESSES, headers=bearer(body["access_token"]))
    assert res.status == 401
    assert res.json()["unit_error"]["kind"] == "token_expired"


def test_the_refresh_token_expires_after_fourteen_days(virtual: Harness) -> None:
    virtual.unit.context.clock.advance(14 * 86_400_000)
    res = virtual.refresh()
    assert res.status == 400 and _reason(res) == "refresh_token_expired"


def test_a_refresh_rejected_rule_answers_envelope_a_and_leaves_the_token_usable(h: Harness) -> None:
    _arm(h, "refresh_rejected", "POST /oauth/token")
    faulted = h.refresh()
    assert faulted.status == 401
    assert faulted.json()["error"] == "Unauthorized"
    assert faulted.headers["vendorfake-fault"] == "refresh_rejected"
    assert h.refresh().status == 200


def test_a_malformed_json_body_is_invalid_json_before_client_auth(h: Harness) -> None:
    res = h.api.post(TOKEN, "{not json", headers={"content-type": "application/json"})
    assert res.status == 400
    assert res.json()["error"] == "invalid_request"
    assert res.json()["unit_error"]["kind"] == "invalid_json"
