"""Lightspeed Restaurant K-Series on V1 authentication (D-016), as a vendorfake vendor.
``VENDOR`` is a fresh definition on every access, through :func:`__getattr__`."""

from __future__ import annotations

from vendorfake.core.kernel.types import VendorDefinition
from vendorfake.lightspeed_k.auth import STATEMENT, LightspeedKAuth
from vendorfake.lightspeed_k.capabilities import (
    LIGHTSPEED_K_CAPABILITIES,
    LIGHTSPEED_K_NOT_MODELED,
    LIGHTSPEED_K_NOT_SUPPORTED,
    LIGHTSPEED_K_NOT_SUPPORTED_ROLES,
)
from vendorfake.lightspeed_k.config import LightspeedKConfig, resolve_lightspeed_k_config
from vendorfake.lightspeed_k.entities import COL
from vendorfake.lightspeed_k.errors import LIGHTSPEED_K_ERROR_TABLE, LightspeedKErrorShaper
from vendorfake.lightspeed_k.events import LightspeedKEventMapper
from vendorfake.lightspeed_k.ids import LightspeedKIds
from vendorfake.lightspeed_k.signer import LightspeedKBasicSigner, verify_basic_auth
from vendorfake.lightspeed_k.vendor import (
    LIGHTSPEED_K_ROLES,
    VENDOR_NAME,
    LightspeedKVendor,
    create_lightspeed_k_vendor,
)

__all__ = [
    "COL",
    "LIGHTSPEED_K_CAPABILITIES",
    "LIGHTSPEED_K_ERROR_TABLE",
    "LIGHTSPEED_K_NOT_MODELED",
    "LIGHTSPEED_K_NOT_SUPPORTED",
    "LIGHTSPEED_K_NOT_SUPPORTED_ROLES",
    "LIGHTSPEED_K_ROLES",
    "STATEMENT",
    "VENDOR",
    "VENDOR_NAME",
    "LightspeedKAuth",
    "LightspeedKBasicSigner",
    "LightspeedKConfig",
    "LightspeedKErrorShaper",
    "LightspeedKEventMapper",
    "LightspeedKIds",
    "LightspeedKVendor",
    "create_lightspeed_k_vendor",
    "resolve_lightspeed_k_config",
    "verify_basic_auth",
]


def __getattr__(name: str) -> VendorDefinition:
    if name == "VENDOR":
        return create_lightspeed_k_vendor()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
