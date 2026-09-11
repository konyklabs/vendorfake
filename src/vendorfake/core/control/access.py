"""Who may reach the control plane: the optional ``VENDORFAKE_CONTROL_TOKEN`` check the kernel and the ASGI adapter
share. JUDGMENT -- no vendor documents how a fake guards its own control plane."""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

from vendorfake.core.kernel.router import INTERNAL_PATH_PREFIX, split_path
from vendorfake.core.kernel.types import UnitError, UnitErrorKind

__all__ = [
    "CONTROL_TOKEN_ENV",
    "CONTROL_TOKEN_HEADER",
    "HEALTH_PATH",
    "ambient_control_token",
    "control_access_error",
    "control_token_hint",
    "control_token_hooks",
    "names_control_plane",
]

CONTROL_TOKEN_HEADER: Final = "vendorfake-control-token"
CONTROL_TOKEN_ENV: Final = "VENDORFAKE_CONTROL_TOKEN"
HEALTH_PATH: Final = "/__unit/health"
"""The one route a token never guards, so a healthcheck needs no secret."""

_NAMESPACE: Final = INTERNAL_PATH_PREFIX.strip("/")


def names_control_plane(path: str) -> bool:
    """True when the router reads ``path`` as the control plane: segment-wise, so ``//__unit/info`` counts too."""
    segments = split_path(path)
    return bool(segments) and segments[0] == _NAMESPACE


def control_access_error(method: str, path: str, headers: Mapping[str, str], token: str | None) -> UnitError | None:
    """The refusal this request draws, or ``None``; ``headers`` are lower-cased, as every binding builds them."""
    if not token or not names_control_plane(path):
        return None
    if method.upper() in ("GET", "HEAD") and split_path(path) == split_path(HEALTH_PATH):
        return None
    presented = headers.get(CONTROL_TOKEN_HEADER, "")
    if hmac.compare_digest(presented.encode("utf-8"), token.encode("utf-8")):
        return None
    return UnitError(
        UnitErrorKind.UNAUTHORIZED,
        detail="The control plane requires the vendorfake-control-token header.",
        field=CONTROL_TOKEN_HEADER,
    )


def ambient_control_token(environ: Mapping[str, str]) -> str | None:
    """``VENDORFAKE_CONTROL_TOKEN`` for a client addressing a running unit; blank reads as unset."""
    return environ.get(CONTROL_TOKEN_ENV) or None


def control_token_hooks(
    token: str | None, *, base_path: str = ""
) -> tuple[list[Callable[[Any], None]], list[Callable[[Any], Awaitable[None]]]]:
    """``httpx`` request hooks, sync and async, sending ``token`` on control-plane paths below ``base_path`` and never to
    the vendor surface; a header the caller set wins. Empty without a token. Duck-typed: the core imports no client."""
    if token is None:
        return [], []
    value: str = token
    prefix = base_path.rstrip("/")

    def attach(request: Any) -> None:
        path = str(request.url.path)
        if prefix and (path == prefix or path.startswith(f"{prefix}/")):
            path = path[len(prefix) :]
        if names_control_plane(path) and CONTROL_TOKEN_HEADER not in request.headers:
            request.headers[CONTROL_TOKEN_HEADER] = value

    async def attach_async(request: Any) -> None:
        attach(request)

    return [attach], [attach_async]


def control_token_hint(status: int, token: str | None) -> str:
    """What a client's error says about a 401 from a control plane, or ``""`` for any other answer."""
    if status != 401:
        return ""
    if token is None:
        return (
            f"The control plane requires a token: export {CONTROL_TOKEN_ENV} with the unit's token "
            "(a variable, never a flag, which process listings show)."
        )
    return f"{CONTROL_TOKEN_ENV} is set, but the unit refused it."
