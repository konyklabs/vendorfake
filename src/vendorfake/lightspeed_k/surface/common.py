"""What every surface is handed, the citation table, and the shared int64 readers.
A site labels its behaviour with one comment naming a :data:`SOURCES` key."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError

from vendorfake.core.config.models import unit_error_from_validation
from vendorfake.core.kernel.types import HandlerArgs, UnitError, UnitErrorKind
from vendorfake.core.time.clock import Clock
from vendorfake.lightspeed_k.config import LightspeedKConfig
from vendorfake.lightspeed_k.ids import LightspeedKIds

__all__ = [
    "BEARER_AUTH",
    "FETCHED",
    "SCOPE_ORDERS",
    "SOURCES",
    "LightspeedKDeps",
    "int64_path",
    "int64_query",
    "is_past_ms",
    "validate_body",
]

PORTAL = "https://api-portal.lsk.lightspeed.app"
SOURCES: Mapping[str, str] = {
    "source.json": "https://api-docs.lsk.lightspeed.app/source.json",
    "changes": "https://api-docs.lsk.lightspeed.app/changes",
    "v1-overview": f"{PORTAL}/quick-start/authentication/v1-authentication/v1-authorization-overview",
    "v1-faq": f"{PORTAL}/quick-start/authentication/v1-authentication/v1-authorization-faq",
    "v1-managing": f"{PORTAL}/quick-start/authentication/v1-authentication/v1-managing-access-tokens",
    "v1-about-tokens": f"{PORTAL}/quick-start/authentication/v1-authentication/v1-about-access-tokens",
    "scopes": f"{PORTAL}/quick-start/authentication/access-scopes",
    "locations": f"{PORTAL}/guides/definitions/business-locations",
    "tutorial": f"{PORTAL}/guides/tutorials/online-ordering-basics",
}
FETCHED = "2026-10-29"
BEARER_AUTH = "bearer"
SCOPE_ORDERS = "orders-api"
_INT64 = 2**63
_M = TypeVar("_M", bound=BaseModel)


@runtime_checkable
class LightspeedKDeps(Protocol):
    """What a surface needs from the vendor that owns it, read live (hydrate re-resolves both)."""

    @property
    def config(self) -> LightspeedKConfig: ...

    @property
    def ids(self) -> LightspeedKIds: ...


def is_past_ms(instant_ms: int, clock: Clock) -> bool:
    return instant_ms <= clock.now()


def _int64(raw: str | None, name: str) -> int:
    if raw is None or raw == "":
        raise UnitError(UnitErrorKind.MISSING_FIELD, detail=f"{name} is required.", field=name)
    text = raw.strip()
    digits = text[1:] if text[:1] in "+-" else text
    if not digits.isascii() or not digits.isdigit() or not -_INT64 <= int(text) < _INT64:
        raise UnitError(UnitErrorKind.INVALID_VALUE, detail=f"{name} must be an int64.", field=name)
    return int(text)


def int64_query(args: HandlerArgs, name: str) -> int:
    return _int64(args.query(name), name)


def int64_path(args: HandlerArgs, name: str) -> int:
    return _int64(args.params.get(name), name)


def validate_body(model: type[_M], body: Any, **context: Any) -> _M:
    try:
        return model.model_validate(body, context=context)
    except ValidationError as exc:
        raise unit_error_from_validation(exc) from exc
