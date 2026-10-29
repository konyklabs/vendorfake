"""The collections this vendor stores, and the three credential shapes in them.
A business or menu row is ``{"id": str(<int64 id>), "document": <wire shape>}``: the store wants a string id."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from vendorfake.core.state.store import Entity
from vendorfake.core.util.json import compact

__all__ = ["COL", "AuthorizationCodeEntity", "LightspeedKCollections", "RefreshTokenEntity", "TokenEntity"]


@dataclass(frozen=True, slots=True)
class LightspeedKCollections:
    """The store collections, named once."""

    businesses: str = "businesses"
    menus: str = "menus"
    auth_codes: str = "auth_codes"
    tokens: str = "tokens"
    refresh_tokens: str = "refresh_tokens"


COL = LightspeedKCollections()


def _str(value: Any) -> str:
    return "" if value is None else str(value)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _opt_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _strs(value: Any) -> tuple[str, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(str(item) for item in value)
    return ()


@dataclass(frozen=True, slots=True)
class TokenEntity:
    """One V1 access token, seeded or minted by ``POST /oauth/token``."""

    id: str
    access_token: str
    client_id: str
    scopes: tuple[str, ...]
    expires_at_ms: int
    created_at_ms: int
    refresh_token_id: str | None = None

    @classmethod
    def from_entity(cls, entity: Mapping[str, Any]) -> TokenEntity:
        return cls(
            id=_str(entity["id"]),
            access_token=_str(entity.get("access_token")),
            client_id=_str(entity.get("client_id")),
            scopes=_strs(entity.get("scopes")),
            expires_at_ms=_opt_int(entity.get("expires_at_ms")) or 0,
            created_at_ms=_opt_int(entity.get("created_at_ms")) or 0,
            refresh_token_id=_opt_str(entity.get("refresh_token_id")),
        )

    def to_entity(self) -> Entity:
        return compact(
            {
                "id": self.id,
                "access_token": self.access_token,
                "client_id": self.client_id,
                "scopes": list(self.scopes),
                "expires_at_ms": self.expires_at_ms,
                "created_at_ms": self.created_at_ms,
                "refresh_token_id": self.refresh_token_id,
            }
        )


@dataclass(frozen=True, slots=True)
class RefreshTokenEntity:
    """One single-use V1 refresh token, linked to the access token issued with it."""

    id: str
    refresh_token: str
    client_id: str
    scopes: tuple[str, ...]
    expires_at_ms: int
    access_token_id: str
    created_at_ms: int
    used_at_ms: int | None = None

    @classmethod
    def from_entity(cls, entity: Mapping[str, Any]) -> RefreshTokenEntity:
        return cls(
            id=_str(entity["id"]),
            refresh_token=_str(entity.get("refresh_token")),
            client_id=_str(entity.get("client_id")),
            scopes=_strs(entity.get("scopes")),
            expires_at_ms=_opt_int(entity.get("expires_at_ms")) or 0,
            access_token_id=_str(entity.get("access_token_id")),
            created_at_ms=_opt_int(entity.get("created_at_ms")) or 0,
            used_at_ms=_opt_int(entity.get("used_at_ms")),
        )

    def to_entity(self) -> Entity:
        return compact(
            {
                "id": self.id,
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "scopes": list(self.scopes),
                "expires_at_ms": self.expires_at_ms,
                "access_token_id": self.access_token_id,
                "created_at_ms": self.created_at_ms,
                "used_at_ms": self.used_at_ms,
            }
        )


@dataclass(frozen=True, slots=True)
class AuthorizationCodeEntity:
    """One single-use code from the ``GET /oauth/authorize`` stand-in; ``id`` is the code itself."""

    id: str
    client_id: str
    scopes: tuple[str, ...]
    redirect_uri: str
    expires_at_ms: int
    state: str | None = None
    used_at_ms: int | None = None

    @classmethod
    def from_entity(cls, entity: Mapping[str, Any]) -> AuthorizationCodeEntity:
        return cls(
            id=_str(entity["id"]),
            client_id=_str(entity.get("client_id")),
            scopes=_strs(entity.get("scopes")),
            redirect_uri=_str(entity.get("redirect_uri")),
            expires_at_ms=_opt_int(entity.get("expires_at_ms")) or 0,
            state=_opt_str(entity.get("state")),
            used_at_ms=_opt_int(entity.get("used_at_ms")),
        )

    def to_entity(self) -> Entity:
        return compact(
            {
                "id": self.id,
                "client_id": self.client_id,
                "scopes": list(self.scopes),
                "redirect_uri": self.redirect_uri,
                "expires_at_ms": self.expires_at_ms,
                "state": self.state,
                "used_at_ms": self.used_at_ms,
            }
        )
