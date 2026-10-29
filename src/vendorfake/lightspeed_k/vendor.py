"""The lightspeed-k vendor definition: Lightspeed Restaurant K-Series, V1 authentication, slice 1 of D-016.
One instance per unit (``VENDOR`` is minted per access); ``hydrate`` re-resolves the config and reseeds ids."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from vendorfake.core.config.models import ProfileDocument
from vendorfake.core.kernel.types import (
    AuthAdapter,
    CapabilityDecl,
    ErrorShaper,
    EventMapper,
    MagicTriggerSpec,
    Route,
    Signer,
    UnitContext,
    UnitRequest,
    VendorDefinition,
)
from vendorfake.core.state.machine import MachineDef
from vendorfake.lightspeed_k.auth import LightspeedKAuth
from vendorfake.lightspeed_k.capabilities import (
    LIGHTSPEED_K_CAPABILITIES,
    LIGHTSPEED_K_NOT_SUPPORTED,
    LIGHTSPEED_K_NOT_SUPPORTED_ROLES,
)
from vendorfake.lightspeed_k.config import LightspeedKConfig, resolve_lightspeed_k_config
from vendorfake.lightspeed_k.errors import LightspeedKErrorShaper
from vendorfake.lightspeed_k.ids import LightspeedKIds
from vendorfake.lightspeed_k.seed.hydrate import hydrate_lightspeed_k
from vendorfake.lightspeed_k.surface.oauth import oauth_routes
from vendorfake.lightspeed_k.surface.order_and_pay import order_and_pay_routes

__all__ = ["LIGHTSPEED_K_ROLES", "VENDOR_NAME", "LightspeedKVendor", "create_lightspeed_k_vendor"]

_PACKAGE_DIR = Path(__file__).resolve().parent
VENDOR_NAME = "lightspeed-k"
# orders-api reads business information and menus, and reads and writes orders (source.json securitySchemes)
LIGHTSPEED_K_ROLES: Mapping[str, str | None] = {
    "auth": "auth",
    "orders": "order_and_pay",
    "webhooks": None,
    "chaos": "chaos",
}
_VOLATILE_FIELDS: tuple[str, ...] = ("expires_at_ms", "created_at_ms", "used_at_ms")
_OPAQUE_FIELDS: tuple[str, ...] = ("document",)


class LightspeedKVendor:
    """One lightspeed-k vendor, for one unit. Satisfies ``VendorDefinition``."""

    __slots__ = ("_auth", "_base_config", "_config", "_errors", "_ids", "_routes")

    def __init__(self, *, config: LightspeedKConfig | None = None, seed: int = 1) -> None:
        self._base_config = LightspeedKConfig() if config is None else config
        self._config = self._base_config
        self._ids = LightspeedKIds(seed)
        self._errors = LightspeedKErrorShaper(sidecar=self._config.error_sidecar)
        self._auth = LightspeedKAuth(self)
        self._routes: tuple[Route, ...] | None = None

    @property
    def name(self) -> str:
        return VENDOR_NAME

    @property
    def display_name(self) -> str:
        return "Lightspeed Restaurant K-Series (V1 authentication, unofficial)"

    @property
    def api_version(self) -> str | None:
        return None

    @property
    def config(self) -> LightspeedKConfig:
        return self._config

    @property
    def ids(self) -> LightspeedKIds:
        return self._ids

    @property
    def capabilities(self) -> Sequence[CapabilityDecl]:
        return LIGHTSPEED_K_CAPABILITIES

    @property
    def not_supported(self) -> Mapping[str, str]:
        return LIGHTSPEED_K_NOT_SUPPORTED

    @property
    def not_supported_roles(self) -> Mapping[str, str]:
        return LIGHTSPEED_K_NOT_SUPPORTED_ROLES

    @property
    def roles(self) -> Mapping[str, str | None]:
        return LIGHTSPEED_K_ROLES

    @property
    def routes(self) -> Sequence[Route]:
        if self._routes is None:
            self._routes = oauth_routes(self) + order_and_pay_routes(self)
        return self._routes

    @property
    def errors(self) -> ErrorShaper:
        return self._errors

    @property
    def auth(self) -> AuthAdapter:
        return self._auth

    @property
    def signer(self) -> Signer | None:
        return None

    @property
    def events(self) -> EventMapper | None:
        return None

    @property
    def magic(self) -> MagicTriggerSpec | None:
        return None

    @property
    def machines(self) -> Mapping[str, MachineDef]:
        return {}

    @property
    def retry_defaults(self) -> ProfileDocument:
        return ProfileDocument()

    @property
    def volatile_fields(self) -> Sequence[str]:
        return _VOLATILE_FIELDS

    @property
    def opaque_fields(self) -> Sequence[str]:
        return _OPAQUE_FIELDS

    @property
    def profile_dir(self) -> Path:
        return _PACKAGE_DIR / "profiles"

    @property
    def base_dir(self) -> Path:
        return _PACKAGE_DIR

    def hydrate(self, ctx: UnitContext, seed: object) -> None:
        block = dict(ctx.config.vendor_config)
        self._config = self._base_config if not block else self._base_config.merged_with(block)
        self._ids.reseed(ctx.config.chaos.seed)
        self._errors = LightspeedKErrorShaper(sidecar=self._config.error_sidecar)
        hydrate_lightspeed_k(ctx, seed, self._config)

    def decorate(self, headers: dict[str, str], ctx: UnitContext, req: UnitRequest) -> None:
        headers["x-unit-vendor"] = ctx.vendor.name


def create_lightspeed_k_vendor(*, vendor_config: dict[str, Any] | None = None, seed: int = 1) -> VendorDefinition:
    """Build a lightspeed-k vendor; the return annotation is the protocol, so mypy checks the conformance."""
    return LightspeedKVendor(config=resolve_lightspeed_k_config(vendor_config), seed=seed)
