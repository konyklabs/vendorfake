"""The vendor definition: identity, roles, and the declared webhooks role (D-010, D-016)."""

from __future__ import annotations

from tests.unit.lightspeed_k.harness import Harness
from vendorfake import create_unit
from vendorfake.core.kernel.types import VendorDefinition
from vendorfake.lightspeed_k import VENDOR, LightspeedKVendor, create_lightspeed_k_vendor
from vendorfake.lightspeed_k.capabilities import (
    LIGHTSPEED_K_CAPABILITIES,
    LIGHTSPEED_K_NOT_SUPPORTED,
    LIGHTSPEED_K_NOT_SUPPORTED_ROLES,
)
from vendorfake.lightspeed_k.vendor import LIGHTSPEED_K_ROLES
from vendorfake.registry import ROLE_NAMES, available_vendors, resolve_vendor


def test_the_registry_offers_lightspeed_k() -> None:
    assert "lightspeed-k" in available_vendors()
    assert resolve_vendor("lightspeed-k").name == "lightspeed-k"


def test_vendor_is_a_fresh_definition_on_every_access() -> None:
    import vendorfake.lightspeed_k as package

    assert package.VENDOR is not package.VENDOR


def test_identity() -> None:
    definition: VendorDefinition = VENDOR
    assert definition.name == "lightspeed-k"
    assert definition.display_name == "Lightspeed Restaurant K-Series (V1 authentication, unofficial)"
    assert definition.api_version is None
    assert definition.signer is not None
    assert definition.events is not None
    assert definition.magic is None
    assert dict(definition.machines) == {}
    assert isinstance(create_lightspeed_k_vendor(), LightspeedKVendor)


def test_roles_cover_the_vocabulary_and_every_role_is_declared() -> None:
    declared = {row.name for row in LIGHTSPEED_K_CAPABILITIES}
    assert set(LIGHTSPEED_K_ROLES) == set(ROLE_NAMES)
    assert LIGHTSPEED_K_ROLES["webhooks"] == "webhooks"
    assert {value for value in LIGHTSPEED_K_ROLES.values() if value is not None} <= declared
    assert LIGHTSPEED_K_ROLES["orders"] == "order_and_pay"
    assert dict(LIGHTSPEED_K_NOT_SUPPORTED_ROLES) == {}
    assert dict(LIGHTSPEED_K_NOT_SUPPORTED) == {}
    assert {"webhooks", "webhooks.chaos"} <= declared
    assert VENDOR.not_supported_roles == LIGHTSPEED_K_NOT_SUPPORTED_ROLES  # type: ignore[attr-defined]


def test_asking_for_the_webhooks_role_builds_a_unit() -> None:
    built = create_unit(vendor="lightspeed-k", capabilities=["webhooks"])
    try:
        assert built.context.capabilities.is_enabled("webhooks")
    finally:
        built.stop()


def test_info_publishes_roles_reasons_and_the_statement(h: Harness) -> None:
    body = h.api.get("/__unit/info").json()
    vendor = body["vendor"]
    assert vendor["roles"]["webhooks"] == "webhooks"
    assert body["not_supported"] == {}
    assert "not affiliated" in body["auth"]["statement"]


def test_every_route_is_under_oauth_order_and_pay_or_webhooks() -> None:
    paths = [route.path for route in VENDOR.routes]
    assert len(paths) == 10
    assert all(path.startswith(("/oauth/", "/o/op/", "/o/wh/")) for path in paths)
    assert [route.operation_id for route in VENDOR.routes] == [
        "OauthAuthorize",
        "OauthToken",
        "apeLookupBusinesses",
        "apeLoadMenus",
        "apeGetMenuByIdV2",
        "apePlaceToGoOrder",
        "apeCreateWebhookOo",
        "apeUpdateWebhookOo",
        "apeGetWebhookOo",
        "apeDeleteWebhookEndpoint",
    ]
