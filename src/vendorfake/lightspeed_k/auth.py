"""Who a presented V1 bearer is (``Authorization: bearer``, matched case-insensitively, RFC 7235).
No revocation path: a refresh revokes nothing (D-010), so ``TOKEN_REVOKED`` is never raised."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vendorfake.core.kernel.types import (
    AuthCredential,
    AuthMode,
    AuthResult,
    HandlerArgs,
    UnitContext,
    UnitError,
    UnitErrorKind,
)
from vendorfake.lightspeed_k.entities import COL, TokenEntity
from vendorfake.lightspeed_k.surface.common import BEARER_AUTH, LightspeedKDeps, is_past_ms

__all__ = ["STATEMENT", "LightspeedKAuth", "find_token"]

STATEMENT = (
    "Built from Lightspeed's public documentation only, without sandbox or partner access; "
    "konyklabs is not affiliated with, endorsed by, or connected to Lightspeed."
)


def find_token(ctx: UnitContext, access_token: str) -> TokenEntity | None:
    found = ctx.store.collection(COL.tokens).find(lambda entity: entity.get("access_token") == access_token)
    return None if found is None else TokenEntity.from_entity(found)


def _refuse(kind: UnitErrorKind, detail: str, reason: str) -> UnitError:
    return UnitError(kind, detail=detail, info={"reason": reason})


class LightspeedKAuth:
    """V1 bearer authentication. Satisfies ``AuthAdapter``."""

    __slots__ = ("_deps",)

    def __init__(self, deps: LightspeedKDeps) -> None:
        self._deps = deps

    def describe(self) -> Mapping[str, str]:
        return {
            "bearer": (
                "Authorization: bearer {access_token} from POST /oauth/token (V1); the scheme is matched "
                "case-insensitively"
            ),
            "grants": (
                "authorization_code (parameters in the query string) and refresh_token (form body); a refresh "
                "token is single use; the previous access token stays valid until it expires"
            ),
            "scopes": " ".join(self._deps.config.scopes),
            "refusals": (
                "401 token missing/unknown/expired; 403 missing orders-api scope; 400 missing or non-integer "
                "businessLocationId; 404 unknown location or menu"
            ),
            "statement": STATEMENT,
        }

    def credentials(self, ctx: UnitContext) -> Sequence[AuthCredential]:
        offered: list[AuthCredential] = []
        for entity in ctx.store.collection(COL.tokens).all():
            token = TokenEntity.from_entity(entity)
            if is_past_ms(token.expires_at_ms, ctx.clock):
                continue
            offered.append(
                AuthCredential(
                    label=token.id,
                    mode=BEARER_AUTH,
                    headers={"authorization": f"bearer {token.access_token}"},
                    scopes=token.scopes,
                    summary=f"V1 token for client {token.client_id}.",
                )
            )
        return tuple(offered)

    def resolve(self, args: HandlerArgs, mode: AuthMode) -> AuthResult:
        header = args.header("authorization")
        if not header:
            raise _refuse(
                UnitErrorKind.UNAUTHORIZED, "An Authorization: bearer header is required.", "no_authorization_header"
            )
        scheme, _, value = header.partition(" ")
        value = value.strip()
        if scheme.lower() != "bearer" or not value:
            raise _refuse(
                UnitErrorKind.UNAUTHORIZED,
                "The Authorization header must use the bearer scheme.",
                "not_a_bearer_header",
            )
        token = find_token(args.ctx, value)
        if token is None:
            raise _refuse(UnitErrorKind.UNAUTHORIZED, "The access token is not valid.", "unknown_token")
        if is_past_ms(token.expires_at_ms, args.ctx.clock):
            raise _refuse(
                UnitErrorKind.TOKEN_EXPIRED,
                "The access token has expired; refresh it or authorize again.",
                "access_token_expired",
            )
        return AuthResult(
            principal_id=token.client_id,
            scopes=token.scopes,
            token_id=token.id,
            meta={"client_id": token.client_id},
        )
