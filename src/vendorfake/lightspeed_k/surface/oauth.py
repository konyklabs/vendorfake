"""V1 authentication: the authorize stand-in and ``POST /oauth/token`` (v1-overview, v1-faq).
Neither is an operation in source.json, whose securitySchemes names the V2 URLs; both are EXCUSED."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from vendorfake.core.kernel.reply import json_, redirect
from vendorfake.core.kernel.types import HandlerArgs, ReplyInit, Route, UnitContext, UnitError, UnitErrorKind
from vendorfake.lightspeed_k.config import V2_CLIENT_PREFIX
from vendorfake.lightspeed_k.entities import COL, AuthorizationCodeEntity, RefreshTokenEntity, TokenEntity
from vendorfake.lightspeed_k.errors import OAUTH_ERROR_INFO_KEY
from vendorfake.lightspeed_k.paths import OAUTH_AUTHORIZE, OAUTH_TOKEN
from vendorfake.lightspeed_k.surface.common import LightspeedKDeps, is_past_ms

__all__ = ["CAPABILITY", "STAND_IN", "LightspeedKOAuthSurface", "oauth_routes"]

CAPABILITY = "auth"
STAND_IN = "Stand-in (the real consent screen is on api.lsk.lightspeed.app)"
_V2_TOKEN_URL = "https://auth.lsk-prod.app/realms/k-series/protocol/openid-connect/token"
_V2_DETAIL = (
    f"client_id starts with {V2_CLIENT_PREFIX!r}, a V2 API client; V2 authentication (OpenID Connect, "
    f"{_V2_TOKEN_URL}) is deferred until a consumer asks (konyklabs/roadmap#184). "
    "This unit serves V1 authentication only."
)
_GRANT_CODE = "authorization_code"
_GRANT_REFRESH = "refresh_token"


def _err(kind: UnitErrorKind, detail: str, *, field: str, reason: str, oauth: str) -> UnitError:
    return UnitError(kind, detail=detail, field=field, info={"reason": reason, OAUTH_ERROR_INFO_KEY: oauth})


def _missing(field: str, oauth: str = "invalid_request") -> UnitError:
    return _err(UnitErrorKind.MISSING_FIELD, f"{field} is required.", field=field, reason="missing", oauth=oauth)


def _grant(detail: str, *, field: str, reason: str) -> UnitError:
    return _err(UnitErrorKind.INVALID_VALUE, detail, field=field, reason=reason, oauth="invalid_grant")


def _client(detail: str, reason: str) -> UnitError:
    return _err(UnitErrorKind.UNAUTHORIZED, detail, field="authorization", reason=reason, oauth="invalid_client")


class LightspeedKOAuthSurface:
    """The two V1 routes, bound to one vendor's config and id stream."""

    __slots__ = ("_deps",)

    def __init__(self, deps: LightspeedKDeps) -> None:
        self._deps = deps

    def routes(self) -> tuple[Route, ...]:
        return (
            Route(
                method="GET",
                path=OAUTH_AUTHORIZE,
                capability=CAPABILITY,
                handler=self.authorize,
                operation_id="OauthAuthorize",
                summary=f"{STAND_IN}: approves and redirects to redirect_uri with a single-use code and the state.",
            ),
            Route(
                method="POST",
                path=OAUTH_TOKEN,
                capability=CAPABILITY,
                handler=self.token,
                operation_id="OauthToken",
                summary=(
                    "V1 token endpoint, HTTP Basic client auth: the code exchange reads the query string, the "
                    "refresh grant the form body; a refresh token is single use."
                ),
            ),
        )

    # DOCUMENTED v1-overview: response_type=code, client_id, scope, redirect_uri required; state optional
    def authorize(self, args: HandlerArgs) -> ReplyInit:
        config = self._deps.config
        client_id = args.query("client_id")
        if not client_id:
            raise _missing("client_id")
        if client_id.startswith(V2_CLIENT_PREFIX):
            raise _err(
                UnitErrorKind.INVALID_VALUE,
                _V2_DETAIL,
                field="client_id",
                reason="v2_client_id",
                oauth="invalid_request",
            )
        if client_id != config.client_id:
            raise _err(
                UnitErrorKind.INVALID_VALUE,
                f"Unknown client_id {client_id!r}.",
                field="client_id",
                reason="unknown_client",
                oauth="invalid_request",
            )
        if args.query("response_type") != "code":
            raise _err(
                UnitErrorKind.INVALID_VALUE,
                "response_type must be 'code'.",
                field="response_type",
                reason="response_type_not_code",
                oauth="invalid_request",
            )
        redirect_uri = args.query("redirect_uri")
        if not redirect_uri:
            raise _missing("redirect_uri")
        # JUDGMENT RFC 6749 s3.1.2.3: exact match
        if redirect_uri != config.redirect_uri:
            raise _err(
                UnitErrorKind.INVALID_VALUE,
                "redirect_uri does not match the one registered for this client.",
                field="redirect_uri",
                reason="redirect_uri_mismatch",
                oauth="invalid_request",
            )
        scopes = _split_scopes(args.query("scope"))
        if not scopes:
            raise _missing("scope")
        unknown = [scope for scope in scopes if scope not in config.scopes]
        if unknown:
            raise _err(
                UnitErrorKind.INVALID_VALUE,
                f"scope names {unknown}, which this client does not carry.",
                field="scope",
                reason="unknown_scope",
                oauth="invalid_scope",
            )
        state = args.query("state")
        # JUDGMENT RFC 6749 s4.1.2.1: a declined consent redirects with error=access_denied
        if args.consume_fault("authorize_denied") is not None:
            return redirect(_with_query(redirect_uri, {"error": "access_denied", "state": state}))
        code = self._deps.ids.code()
        args.ctx.store.collection(COL.auth_codes).insert(
            AuthorizationCodeEntity(
                id=code,
                client_id=client_id,
                scopes=scopes,
                redirect_uri=redirect_uri,
                state=state,
                expires_at_ms=int(args.ctx.clock.now()) + config.authorization_code_ttl_ms,
            ).to_entity(),
            {"operation_id": "OauthAuthorize"},
        )
        return redirect(_with_query(redirect_uri, {"code": code, "state": state}))

    def token(self, args: HandlerArgs) -> ReplyInit:
        body = _body(args)
        client_id = self._client(args)
        grant_type = args.query("grant_type") or _text(body.get("grant_type"))
        if not grant_type:
            raise _missing("grant_type")
        if grant_type == _GRANT_CODE:
            return json_(self._exchange(args, body, client_id))
        if grant_type == _GRANT_REFRESH:
            return json_(self._refresh(args, body, client_id))
        raise _err(
            UnitErrorKind.INVALID_VALUE,
            f"grant_type {grant_type!r} is not supported; V1 documents authorization_code and refresh_token.",
            field="grant_type",
            reason="unsupported_grant_type",
            oauth="unsupported_grant_type",
        )

    # DOCUMENTED v1-overview: client_id:client_secret, base64-encoded, as the Authorization header
    def _client(self, args: HandlerArgs) -> str:
        header = args.header("authorization") or ""
        scheme, _, encoded = header.partition(" ")
        try:
            decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
        except (binascii.Error, ValueError):
            decoded = ""
        client_id, colon, secret = decoded.partition(":")
        if scheme.lower() != "basic" or not colon:
            raise _client(
                "HTTP Basic client authentication (client_id:client_secret) is required.", "no_basic_client_auth"
            )
        # DOCUMENTED v1-overview: a client_id beginning devp-v2 is a V2 API client
        if client_id.startswith(V2_CLIENT_PREFIX):
            raise _client(_V2_DETAIL, "v2_client_id")
        config = self._deps.config
        if client_id != config.client_id or secret != config.client_secret:
            raise _client("The client credentials are not valid.", "client_credentials_mismatch")
        return client_id

    # DOCUMENTED v1-overview: grant_type, code and redirect_uri "must be passed as query parameters"
    def _exchange(self, args: HandlerArgs, body: Mapping[str, Any], client_id: str) -> dict[str, Any]:
        values: dict[str, str] = {}
        for name in ("code", "redirect_uri"):
            value = args.query(name)
            if not value:
                if _text(body.get(name)):
                    raise _err(
                        UnitErrorKind.INVALID_VALUE,
                        f"{name} must be passed as a query parameter on the V1 code exchange, not in the body.",
                        field=name,
                        reason="v1_exchange_reads_query_parameters",
                        oauth="invalid_request",
                    )
                raise _missing(name)
            values[name] = value
        ctx = args.ctx
        codes = ctx.store.collection(COL.auth_codes)
        stored = codes.get(values["code"])
        if stored is None:
            raise _grant("The authorization code is not valid.", field="code", reason="code_unknown")
        record = AuthorizationCodeEntity.from_entity(stored)
        if record.used_at_ms is not None:
            raise _grant(
                "The authorization code was already used; codes are single use.", field="code", reason="code_used"
            )
        if is_past_ms(record.expires_at_ms, ctx.clock):
            raise _grant("The authorization code expired.", field="code", reason="code_expired")
        if values["redirect_uri"] != record.redirect_uri:
            raise _grant(
                "redirect_uri does not match the one the code was issued for.",
                field="redirect_uri",
                reason="redirect_uri_mismatch",
            )
        now = int(ctx.clock.now())
        codes.update(record.id, lambda draft: draft.__setitem__("used_at_ms", now), meta={"operation_id": "OauthToken"})
        return self._mint(ctx, client_id=client_id, scopes=record.scopes, now=now)

    # DOCUMENTED v1-overview: the refresh values "must be passed in the request body"; v1-faq: single use
    def _refresh(self, args: HandlerArgs, body: Mapping[str, Any], client_id: str) -> dict[str, Any]:
        presented = _text(body.get("refresh_token"))
        if not presented:
            if args.query("refresh_token"):
                raise _err(
                    UnitErrorKind.INVALID_VALUE,
                    "refresh_token must be passed in the request body on the V1 refresh, not the query string.",
                    field="refresh_token",
                    reason="v1_refresh_reads_form_body",
                    oauth="invalid_request",
                )
            raise _missing("refresh_token")
        ctx = args.ctx
        refresh_tokens = ctx.store.collection(COL.refresh_tokens)
        found = refresh_tokens.find(lambda entity: entity.get("refresh_token") == presented)
        if found is None:
            raise _grant("The refresh token is not valid.", field="refresh_token", reason="refresh_token_unknown")
        record = RefreshTokenEntity.from_entity(found)
        if record.used_at_ms is not None:
            raise _grant(
                "The refresh token was already used; refresh tokens can only be used once.",
                field="refresh_token",
                reason="refresh_token_reused",
            )
        if is_past_ms(record.expires_at_ms, ctx.clock):
            raise _grant("The refresh token expired.", field="refresh_token", reason="refresh_token_expired")
        if record.client_id != client_id:
            raise _grant(
                "The refresh token was issued to another client.",
                field="refresh_token",
                reason="refresh_token_foreign_client",
            )
        now = int(ctx.clock.now())
        refresh_tokens.update(
            record.id, lambda draft: draft.__setitem__("used_at_ms", now), meta={"operation_id": "OauthToken"}
        )
        return self._mint(ctx, client_id=client_id, scopes=record.scopes, now=now)

    def _mint(self, ctx: UnitContext, *, client_id: str, scopes: Sequence[str], now: int) -> dict[str, Any]:
        config = self._deps.config
        ids = self._deps.ids
        access, refresh = ids.uuid(), ids.uuid()
        token_id, refresh_id = ids.uuid(), ids.uuid()
        meta = {"operation_id": "OauthToken"}
        ctx.store.collection(COL.tokens).insert(
            TokenEntity(
                id=token_id,
                access_token=access,
                client_id=client_id,
                scopes=tuple(scopes),
                expires_at_ms=now + config.access_token_ttl_ms,
                created_at_ms=now,
                refresh_token_id=refresh_id,
            ).to_entity(),
            meta,
        )
        ctx.store.collection(COL.refresh_tokens).insert(
            RefreshTokenEntity(
                id=refresh_id,
                refresh_token=refresh,
                client_id=client_id,
                scopes=tuple(scopes),
                expires_at_ms=now + config.refresh_token_ttl_ms,
                access_token_id=token_id,
                created_at_ms=now,
            ).to_entity(),
            meta,
        )
        # DOCUMENTED v1-overview: the five members; the scope's trailing space is in both samples
        return {
            "access_token": access,
            "token_type": "bearer",
            "refresh_token": refresh,
            "expires_in": config.access_token_ttl_s,
            "scope": " ".join(scopes) + " ",
        }


def oauth_routes(deps: LightspeedKDeps) -> tuple[Route, ...]:
    return LightspeedKOAuthSurface(deps).routes()


def _body(args: HandlerArgs) -> Mapping[str, Any]:
    try:
        return args.body()
    except UnitError as exc:
        raise UnitError(
            exc.kind,
            detail=exc.detail,
            field=exc.field,
            info={"reason": "unreadable_body", OAUTH_ERROR_INFO_KEY: "invalid_request"},
        ) from exc


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _split_scopes(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    return tuple(part for part in raw.replace("+", " ").split() if part)


def _with_query(url: str, params: Mapping[str, str | None]) -> str:
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.extend((name, value) for name, value in params.items() if value is not None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
