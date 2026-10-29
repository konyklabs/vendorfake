"""The ``vendor`` block of a lightspeed-k profile, with each documented value labelled.
``extra="forbid"``: an unknown key is a startup failure. Citations: ``surface/common.SOURCES``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vendorfake.core.config.models import merged_over

__all__ = ["V2_CLIENT_PREFIX", "LightspeedKConfig", "resolve_lightspeed_k_config"]

V2_CLIENT_PREFIX = "devp-v2"


class LightspeedKConfig(BaseModel):
    """The resolved ``vendor`` block."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    client_id: str = "unit-lightspeed-k-client-id"
    client_secret: str = "unit-lightspeed-k-client-secret"
    redirect_uri: str = "https://consumer.example/callback"
    scopes: tuple[str, ...] = ("financial-api", "orders-api")
    access_token_ttl_s: int = Field(default=3599, gt=0)  # DOCUMENTED v1-overview
    refresh_token_ttl_s: int = Field(default=14 * 86400, gt=0)  # DOCUMENTED v1-faq
    authorization_code_ttl_s: int = Field(default=600, gt=0)  # JUDGMENT RFC 6749 s4.1.2
    error_sidecar: bool = True

    @field_validator("client_id")
    @classmethod
    def _v1_client(cls, value: str) -> str:
        if value.startswith(V2_CLIENT_PREFIX):
            raise ValueError(
                f"client_id {value!r} starts with {V2_CLIENT_PREFIX!r}, a V2 (OpenID Connect) client; this unit "
                "serves V1 authentication only (reason: v2_client_id)"
            )
        return value

    @field_validator("redirect_uri")
    @classmethod
    def _https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("redirect_uri must use https (Redirect URLs require HTTPS)")  # DOCUMENTED v1-faq
        return value

    def merged_with(self, block: Mapping[str, Any]) -> LightspeedKConfig:
        return merged_over(self, block)

    @property
    def access_token_ttl_ms(self) -> int:
        return self.access_token_ttl_s * 1000

    @property
    def refresh_token_ttl_ms(self) -> int:
        return self.refresh_token_ttl_s * 1000

    @property
    def authorization_code_ttl_ms(self) -> int:
        return self.authorization_code_ttl_s * 1000


def resolve_lightspeed_k_config(raw: Mapping[str, Any] | None = None) -> LightspeedKConfig:
    """Build the config from a profile's ``vendor`` block; an empty block is legal."""
    return LightspeedKConfig.model_validate(dict(raw or {}))
