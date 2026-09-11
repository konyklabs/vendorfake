"""Who may reach the control plane: the optional ``VENDORFAKE_CONTROL_TOKEN`` check the kernel and the ASGI adapter
share. JUDGMENT -- no vendor documents how a fake guards its own control plane."""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from typing import Final

from vendorfake.core.kernel.router import INTERNAL_PATH_PREFIX, split_path
from vendorfake.core.kernel.types import UnitError, UnitErrorKind

__all__ = [
    "CONTROL_TOKEN_ENV",
    "CONTROL_TOKEN_HEADER",
    "HEALTH_PATH",
    "control_access_error",
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
