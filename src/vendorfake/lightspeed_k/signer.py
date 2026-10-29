"""HTTP Basic on every order notification to an endpoint registered withBasicAuth (tutorial); no signature."""

from __future__ import annotations

import base64
import hmac
from collections.abc import Mapping

from vendorfake.core.kernel.types import SignerProperties, SignInput
from vendorfake.core.webhooks.models import DeliveryMetadata
from vendorfake.lightspeed_k.retry import (
    CONTENT_TYPE,
    INITIAL_DELIVERY_HEADER,
    RETRY_NUMBER_HEADER,
    RETRY_REASON_HEADER,
    RETRY_REASONS,
)
from vendorfake.lightspeed_k.surface.common import FETCHED, SOURCES

__all__ = [
    "AUTH_HEADER",
    "LIGHTSPEED_K_SIGNER_PROPERTIES",
    "LightspeedKBasicSigner",
    "basic_header",
    "verify_basic_auth",
]

AUTH_HEADER = "Authorization"
LIGHTSPEED_K_SIGNER_PROPERTIES = SignerProperties(
    url_bound=False,
    body_bound=False,
    secret_bound=True,
    signature_headers=(AUTH_HEADER.lower(),),
)


# JUDGMENT RFC 7617: base64 of the stored user-pass, encoded as stored
def basic_header(secret: str) -> str:
    return "Basic " + base64.b64encode(secret.encode("utf-8")).decode("ascii")


def verify_basic_auth(headers: Mapping[str, object], username: str, password: str) -> bool:
    expected = basic_header(f"{username}:{password}").encode("utf-8")
    for name, value in headers.items():
        if name.lower() == AUTH_HEADER.lower():
            return isinstance(value, str) and hmac.compare_digest(value.encode("utf-8"), expected)
    return False


class LightspeedKBasicSigner:
    """Satisfies ``Signer``. Stateless."""

    __slots__ = ()

    @property
    def properties(self) -> SignerProperties:
        return LIGHTSPEED_K_SIGNER_PROPERTIES

    def sign(self, payload: SignInput) -> Mapping[str, str]:
        return {} if payload.secret == "" else {AUTH_HEADER: basic_header(payload.secret)}

    # JUDGMENT: the x-vendorfake-* headers are this fake's own, retry metadata only on a retry
    def headers(self, meta: DeliveryMetadata) -> Mapping[str, str]:
        out = {"content-type": CONTENT_TYPE, INITIAL_DELIVERY_HEADER: meta.initial_delivery_at}
        if meta.is_retry:
            out[RETRY_NUMBER_HEADER] = str(meta.retry_number)
            if meta.retry_reason is not None:
                out[RETRY_REASON_HEADER] = RETRY_REASONS[meta.retry_reason]
        return out

    def describe(self) -> Mapping[str, str]:
        return {
            "header": AUTH_HEADER,
            "algorithm": "HTTP Basic (RFC 7617); no HMAC, no timestamp",
            "documented": (
                "DOCUMENTED: 'When withBasicAuth is set to true you can set a username and password for the "
                f"webhook ... to authenticate the requests being sent to your endpoint' ({SOURCES['tutorial']}, "
                f"fetched {FETCHED})."
            ),
            "not_found": "NOT FOUND: no K-Series page documents a signature, an HMAC or a timestamp header.",
            "judgment": (
                "JUDGMENT: signature_key is username:password, and any non-empty key gets a header, colon or not; "
                "an endpoint registered without Basic gets none."
            ),
            "reference": SOURCES["tutorial"],
        }
