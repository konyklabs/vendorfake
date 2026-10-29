"""What this vendor can be asked to do, and what it does not model (D-016, D-010)."""

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
            "Order and Pay under the orders-api scope: the businesses and locations the token sees, a "
            "location's menus, one menu in its V2 shape, the to-go order write, and the tax breakdown of a proposed "
            "order priced from the seeded menu."
        ),
    ),
    CapabilityDecl(
        name="webhooks",
        summary=(
            "Order-notification delivery from the journal to the endpoint an order names, HTTP Basic when "
            "registered with it, endpoint CRUD under /o/wh/1/webhook, and a JUDGMENT retry schedule."
        ),
    ),
    CapabilityDecl(
        name="chaos",
        summary="Request-scope fault injection: timeouts, server errors, the documented 503, token expiry.",
        kind="behavior",
    ),
    CapabilityDecl(
        name="webhooks.chaos",
        summary="Delivery faults: duplication, reordering, dropped acknowledgements, delay.",
        kind="behavior",
        requires=("webhooks", "chaos"),
    ),
)

LIGHTSPEED_K_NOT_SUPPORTED: Mapping[str, str] = {}
LIGHTSPEED_K_NOT_SUPPORTED_ROLES: Mapping[str, str] = {}

LIGHTSPEED_K_NOT_MODELED: Mapping[str, str] = {
    "v2-oidc": "V2 authentication (OpenID Connect at auth.lsk-prod.app, the URLs source.json's securitySchemes "
    "names) is deferred until a consumer asks (konyklabs/roadmap#184); a devp-v2 client id is refused with reason "
    "v2_client_id.",
    "token-exchange": "The V1-to-V2 token-exchange grant is deferred until a consumer asks (konyklabs/roadmap#184).",
    "userinfo": "GET /oauth/userinfo is deferred until a consumer asks (konyklabs/roadmap#184).",
    "menu-v1-load": "GET /o/op/1/menu/load/{menuId}, deprecated 2026-05-15 (changes, #dbf0c552), is not served.",
    "account-profile-pricing": "accountProfile on the menu load and accountProfileCode on the tax breakdown are "
    "accepted and ignored: one price per item, whatever the profile.",
    "tax-code-name": "The seeded menu carries no tax code or tax name, so taxLines omit taxCode and taxName.",
    "conditional-tax-rules": "conditionalTaxRules is false on the seeded menu and no rule changes a rate; the "
    "breakdown reads taxes[].percentage and taxIncludedInPrice only.",
    "modifier-pricing": "subItems on the tax breakdown are priced as menu items at their own productPrice; "
    "menuModifierGroups are not read and the to-go order's modifiers are not priced.",
    "per-token-location-binding": "One unit is one merchant account: every token sees every seeded business.",
    "rate-limits": "K-Series documents no rate limit; nothing throttles.",
    "error-envelope-timestamp-path": "apePaymentBadRequestError's timestamp and path are omitted, and so is the "
    "to-go and webhook 400s' errors[]: C10 compares the two bindings' bytes, which a wall-clock instant never "
    "agrees on, and the shaper never sees the path.",
    "order-lifecycle-source": "No POS: after SUCCESS an order's READY_FOR_PICKUP, CANCELLED, IN_DELIVERY, CLOSED or "
    "ABANDONED is driven with POST /__unit/state/update on collection orders, and each change is delivered.",
    "account-snapshot": "provideAccount, expandTransactions and expandPayments are stored, echoed and reset; no "
    "notification carries the account object.",
    "order-delivered-event": "apeEventResource lists order: DELIVERED as subscribable; its meaning is not documented "
    "and it is never emitted.",
    "subscribe-to-filtering": "subscribeTo is stored and echoed; every order status change is delivered whatever it holds.",
    "payment-item-order-api-notifications": "Only order notifications are delivered; payment, item and order_api "
    "resources are accepted in subscribeTo and never emitted.",
    "webhook-business-locations": "The three /business-locations webhook operations, needed only for item and "
    "order_api notifications, are not served.",
    "local-orders": "apeLocalOrder (dine-in) is not served.",
    "scheduled-dispatch": "scheduledTimeForOrderAsIso8601 is validated and stored; the order still reaches the POS at once.",
    "pos-delivery-timeout": "maxTimeToAttemptOrderDeliverToPos is validated (60000 minimum) and never elapses.",
    "second-confirmation": "The tutorial's two confirmation webhooks exist only as screenshots; one notification is "
    "sent per status change.",
    "prior-access-token-revocation": "A refresh leaves the previous access token valid until its own expiry: "
    "nothing on the V1 pages documents revoking it (D-010).",
}
