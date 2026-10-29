"""What this vendor can be asked to do, and the core-gated capabilities slice 1 excuses (D-016, D-010)."""

from __future__ import annotations

from collections.abc import Mapping

from vendorfake.core.kernel.types import CapabilityDecl

__all__ = [
    "LIGHTSPEED_K_CAPABILITIES",
    "LIGHTSPEED_K_NOT_MODELED",
    "LIGHTSPEED_K_NOT_SUPPORTED",
    "LIGHTSPEED_K_NOT_SUPPORTED_ROLES",
]

LIGHTSPEED_K_CAPABILITIES: tuple[CapabilityDecl, ...] = (
    CapabilityDecl(
        name="auth",
        summary=(
            "V1 authentication: POST /oauth/token for both documented grants (code exchange from the query "
            "string, refresh from a form body, HTTP Basic client auth, single-use refresh) and a stand-in "
            "GET /oauth/authorize that issues the single-use code."
        ),
    ),
    CapabilityDecl(
        name="order_and_pay",
        summary=(
            "Order and Pay reads under the orders-api scope: the businesses and locations the token sees, a "
            "location's menus, and one menu in its V2 shape."
        ),
    ),
    CapabilityDecl(
        name="chaos",
        summary="Request-scope fault injection: timeouts, server errors, the documented 503, token expiry.",
        kind="behavior",
    ),
)

_WEBHOOKS_REASON = (
    "slice 1 of D-016 serves the V1 token lifecycle and three Order and Pay reads; webhook registration and "
    "order-notification delivery arrive with slice 2 (konyklabs/roadmap#179)"
)
LIGHTSPEED_K_NOT_SUPPORTED: Mapping[str, str] = {
    "webhooks": _WEBHOOKS_REASON,
    "webhooks.chaos": "no webhook delivery exists to fault; see webhooks",
}
LIGHTSPEED_K_NOT_SUPPORTED_ROLES: Mapping[str, str] = {"webhooks": _WEBHOOKS_REASON}

LIGHTSPEED_K_NOT_MODELED: Mapping[str, str] = {
    "v2-oidc": "V2 authentication (OpenID Connect at auth.lsk-prod.app, the URLs source.json's securitySchemes "
    "names) is D-016 slice 3; a devp-v2 client id is refused with reason v2_client_id.",
    "token-exchange": "The V1-to-V2 token-exchange grant is slice 3.",
    "userinfo": "GET /oauth/userinfo is slice 3.",
    "menu-v1-load": "GET /o/op/1/menu/load/{menuId}, deprecated 2026-05-15 (changes, #dbf0c552), is not served.",
    "account-profile-pricing": "accountProfile is accepted and ignored: one price per item, whatever the profile.",
    "per-token-location-binding": "One unit is one merchant account: every token sees every seeded business.",
    "rate-limits": "K-Series documents no rate limit; nothing throttles.",
    "error-envelope-timestamp-path": "apePaymentBadRequestError's timestamp and path are omitted: C10 compares the "
    "two bindings' bytes, which a wall-clock instant never agrees on, and the shaper never sees the path.",
    "prior-access-token-revocation": "A refresh leaves the previous access token valid until its own expiry: "
    "nothing on the V1 pages documents revoking it (D-010).",
}
