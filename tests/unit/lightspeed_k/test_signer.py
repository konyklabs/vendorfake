"""HTTP Basic on order notifications (tutorial: "authenticate the requests being sent to your endpoint"), checked
independently: RFC 7617 is base64 of user-pass, so the expected header is computed here, never read off the signer."""

from __future__ import annotations

import base64

import pytest

from vendorfake.core.kernel.types import PreparedEvent, SignInput
from vendorfake.core.webhooks.models import DeliveryMetadata, DeliveryOutcome
from vendorfake.lightspeed_k.retry import (
    CONTENT_TYPE,
    INITIAL_DELIVERY_HEADER,
    RETRY_NUMBER_HEADER,
    RETRY_REASON_HEADER,
)
from vendorfake.lightspeed_k.signer import (
    LIGHTSPEED_K_SIGNER_PROPERTIES,
    LightspeedKBasicSigner,
    verify_basic_auth,
)
from vendorfake.lightspeed_k.vendor import create_lightspeed_k_vendor

FIRST_SENT_AT = "2026-10-29T12:00:00.000Z"
EVENT = PreparedEvent(
    type="order:SUCCESS:UNIT-K-ENDPOINT",
    event_id="e1",
    entity_id="order-1",
    created_at=FIRST_SENT_AT,
    body={},
)


def sign_input(*, url: str = "https://a.test/hooks", secret: str = "user:pass", body: bytes = b"{}", attempt: int = 1):
    return SignInput(notification_url=url, raw_body=body, secret=secret, attempt=attempt, event=EVENT)


def meta(*, retry_number: int = 0, reason: DeliveryOutcome | None = None) -> DeliveryMetadata:
    return DeliveryMetadata(
        event=EVENT,
        subscription_id="UNIT-K-ENDPOINT",
        notification_url="https://a.test/hooks",
        attempt=retry_number + 1,
        retry_number=retry_number,
        retry_reason=reason,
        initial_delivery_at=FIRST_SENT_AT,
    )


@pytest.fixture
def signer() -> LightspeedKBasicSigner:
    built = create_lightspeed_k_vendor().signer
    assert isinstance(built, LightspeedKBasicSigner)
    return built


def test_an_empty_secret_sends_no_header(signer: LightspeedKBasicSigner) -> None:
    assert dict(signer.sign(sign_input(secret=""))) == {}


def test_user_pass_is_base64_basic(signer: LightspeedKBasicSigner) -> None:
    assert dict(signer.sign(sign_input())) == {"Authorization": "Basic dXNlcjpwYXNz"}
    assert base64.b64decode("dXNlcjpwYXNz") == b"user:pass"


def test_a_key_with_no_colon_still_gets_a_header(signer: LightspeedKBasicSigner) -> None:
    secret = "conformance-signature-key-one"
    expected = "Basic " + base64.b64encode(secret.encode()).decode()
    assert dict(signer.sign(sign_input(secret=secret))) == {"Authorization": expected}


def test_only_the_secret_moves_the_header(signer: LightspeedKBasicSigner) -> None:
    base = dict(signer.sign(sign_input()))
    assert dict(signer.sign(sign_input(url="https://b.test/other"))) == base
    assert dict(signer.sign(sign_input(body=b'{"different": true}'))) == base
    assert dict(signer.sign(sign_input(attempt=3))) == base
    assert dict(signer.sign(sign_input(secret="user:other"))) != base


def test_properties_are_the_declared_ones(signer: LightspeedKBasicSigner) -> None:
    assert signer.properties == LIGHTSPEED_K_SIGNER_PROPERTIES
    assert LIGHTSPEED_K_SIGNER_PROPERTIES.url_bound is False
    assert LIGHTSPEED_K_SIGNER_PROPERTIES.body_bound is False
    assert LIGHTSPEED_K_SIGNER_PROPERTIES.secret_bound is True
    assert LIGHTSPEED_K_SIGNER_PROPERTIES.signature_headers == ("authorization",)


def test_first_attempt_headers_carry_no_retry_metadata(signer: LightspeedKBasicSigner) -> None:
    assert dict(signer.headers(meta())) == {"content-type": CONTENT_TYPE, INITIAL_DELIVERY_HEADER: FIRST_SENT_AT}
    assert CONTENT_TYPE == "application/json"


def test_a_retry_adds_the_number_and_the_reason(signer: LightspeedKBasicSigner) -> None:
    headers = dict(signer.headers(meta(retry_number=2, reason=DeliveryOutcome.TIMEOUT)))
    assert headers == {
        "content-type": CONTENT_TYPE,
        INITIAL_DELIVERY_HEADER: FIRST_SENT_AT,
        RETRY_NUMBER_HEADER: "2",
        RETRY_REASON_HEADER: "timeout",
    }


def test_verify_basic_auth_is_case_insensitive_on_the_name() -> None:
    header = "Basic " + base64.b64encode(b"unit-k-user:unit-k-password").decode()
    assert verify_basic_auth({"authorization": header}, "unit-k-user", "unit-k-password")
    assert verify_basic_auth({"Authorization": header}, "unit-k-user", "unit-k-password")
    assert not verify_basic_auth({"authorization": header}, "unit-k-user", "wrong")
    assert not verify_basic_auth({}, "unit-k-user", "unit-k-password")


def test_describe_labels_basic_as_documented(signer: LightspeedKBasicSigner) -> None:
    text = " ".join(signer.describe().values())
    assert "DOCUMENTED" in text and "JUDGMENT" in text and "NOT FOUND" in text
