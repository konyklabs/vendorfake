"""lightspeed-k error shaping: one table, four bodies chosen by the refusal. Every status is JUDGMENT
but the 503's and the to-go 409's; see ``docs/vendors/lightspeed-k.md`` and each row's ``note``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vendorfake.core.kernel.shaping import (
    Provenance,
    assert_error_table_total,
    mechanism_headers,
    sidecar_headers,
    unit_error_sidecar,
)
from vendorfake.core.kernel.types import ShapedError, UnitContext, UnitError, UnitErrorKind, UnitRequest
from vendorfake.core.util.json import compact

__all__ = [
    "ENVELOPE_INFO_KEY",
    "LIGHTSPEED_K_ERROR_TABLE",
    "OAUTH_ERROR_INFO_KEY",
    "STATUS_STRING_ENVELOPE",
    "LightspeedKErrorMapping",
    "LightspeedKErrorShaper",
]

OAUTH_ERROR_INFO_KEY = "oauth_error"
ENVELOPE_INFO_KEY = "envelope"
STATUS_STRING_ENVELOPE = "status_string"
_ENVELOPE_NOTE = (
    "Lightspeed documents only 'a 4xx error will be returned'; this body is the Order and Pay tag's one named "
    "error component (apePaymentBadRequestError) without timestamp and path, generalised to every refusal."
)


@dataclass(frozen=True, slots=True)
class LightspeedKErrorMapping:
    """One row: a core error kind on this vendor's wire."""

    status: int
    provenance: Provenance
    title: str
    message: str
    note: str | None = None

    def as_json(self) -> dict[str, Any]:
        return compact(
            {
                "status": self.status,
                "provenance": self.provenance,
                "title": self.title,
                "message": self.message,
                "note": self.note,
            }
        )


_M = LightspeedKErrorMapping
LIGHTSPEED_K_ERROR_TABLE: dict[UnitErrorKind, LightspeedKErrorMapping] = {
    UnitErrorKind.BAD_REQUEST: _M(
        400, "judgment", "Bad Request", "The request could not be understood.", _ENVELOPE_NOTE
    ),
    UnitErrorKind.INVALID_JSON: _M(400, "judgment", "Bad Request", "The request body is not valid JSON."),
    UnitErrorKind.MISSING_FIELD: _M(400, "judgment", "Bad Request", "A required parameter is missing."),
    UnitErrorKind.INVALID_VALUE: _M(400, "judgment", "Bad Request", "A parameter value is not valid."),
    UnitErrorKind.NOT_FOUND: _M(404, "judgment", "Not Found", "The requested resource was not found."),
    UnitErrorKind.METHOD_NOT_ALLOWED: _M(
        405, "judgment", "Method Not Allowed", "The HTTP method is not allowed on this resource."
    ),
    UnitErrorKind.UNAUTHORIZED: _M(
        401,
        "judgment",
        "Unauthorized",
        "The access token is missing or not valid.",
        "'If an access token becomes invalid or expired, a 4xx error will be returned' "
        "(v1-managing-access-tokens); 401 is RFC 6750 s3.1.",
    ),
    UnitErrorKind.TOKEN_EXPIRED: _M(
        401, "judgment", "Unauthorized", "The access token has expired; refresh it or authorize again."
    ),
    UnitErrorKind.TOKEN_REVOKED: _M(
        401,
        "judgment",
        "Unauthorized",
        "The access token was revoked.",
        "Never raised: a refresh leaves the previous access token valid (D-010).",
    ),
    UnitErrorKind.FORBIDDEN_SCOPE: _M(
        403, "judgment", "Forbidden", "The access token does not carry the orders-api scope this endpoint requires."
    ),
    UnitErrorKind.CAPABILITY_DISABLED: _M(
        501, "judgment", "Not Implemented", "This capability is not enabled on this unit."
    ),
    UnitErrorKind.VERSION_CONFLICT: _M(
        409, "judgment", "Conflict", "The supplied version does not match the current version."
    ),
    UnitErrorKind.IDEMPOTENCY_CONFLICT: _M(
        409, "judgment", "Conflict", "A conflicting request with the same key was already processed."
    ),
    UnitErrorKind.INVALID_CURSOR: _M(400, "judgment", "Bad Request", "The cursor is not valid for this request."),
    UnitErrorKind.INVALID_TRANSITION: _M(
        409, "judgment", "Conflict", "The entity cannot be changed in its current state."
    ),
    UnitErrorKind.CONFLICT: _M(
        409,
        "documented",
        "Conflict",
        "reference has already been used",
        "apePlaceToGoOrder declares 409 {status:'fail', msg:'reference has already been used <ref>'} under */* "
        "(source.json, fetched 2026-10-29) for a thirdPartyReference already spent.",
    ),
    UnitErrorKind.RATE_LIMITED: _M(
        429,
        "judgment",
        "Too Many Requests",
        "Rate limit exceeded.",
        "K-Series documents no rate limit; the status is the core's and nothing here throttles.",
    ),
    UnitErrorKind.TIMEOUT: _M(504, "judgment", "Gateway Timeout", "Gateway timeout."),
    UnitErrorKind.UNAVAILABLE: _M(
        503,
        "documented",
        "Service Unavailable",
        "Service unavailable.",
        "503 and its body {status:'503', timestamp, message, apiSubExceptions} are declared on apeGetMenuByIdV2 "
        "(source.json, fetched 2026-10-29); this unit answers that envelope, without timestamp, for every 503. "
        "The fault that produces it is this project's. The tax breakdown's own 400 and 404 answer the same envelope, "
        "with one apiSubExceptions entry naming the field.",
    ),
    UnitErrorKind.INTERNAL: _M(500, "judgment", "Internal Server Error", "Internal server error."),
}


class LightspeedKErrorShaper:
    """Turns a :class:`UnitError` into this vendor's body. Satisfies ``ErrorShaper``."""

    __slots__ = ("_sidecar",)

    def __init__(self, *, sidecar: bool = True) -> None:
        self._sidecar = sidecar

    def shape(self, err: UnitError, ctx: UnitContext, *, describing: bool = False) -> ShapedError:
        mapping = LIGHTSPEED_K_ERROR_TABLE[err.kind]
        info = dict(err.info or {})
        detail = err.detail or mapping.message
        headers = mechanism_headers(err, retry_after_header=True)
        oauth = info.get(OAUTH_ERROR_INFO_KEY)
        body: dict[str, Any]
        if isinstance(oauth, str) and oauth:
            # JUDGMENT RFC 6749 s5.2: V1 documents no token-endpoint error body
            body = {"error": oauth, "error_description": detail}
            if oauth == "invalid_client":
                headers["www-authenticate"] = "Basic"
        elif err.kind is UnitErrorKind.UNAVAILABLE or info.get(ENVELOPE_INFO_KEY) == STATUS_STRING_ENVELOPE:
            # DOCUMENTED source.json: the */* envelope of apeGetMenuByIdV2's 503, tax-preview-apiTaxBreakdown's 400/403/404/503
            keyed = info.get(ENVELOPE_INFO_KEY) == STATUS_STRING_ENVELOPE and err.field
            subs = [compact({"field": err.field, "rejectedValue": info.get("rejected_value"), "message": detail})]
            body = {"status": str(mapping.status), "message": detail, "apiSubExceptions": subs if keyed else []}
        elif err.kind is UnitErrorKind.CONFLICT:
            # DOCUMENTED source.json: apePlaceToGoOrder 409 under */*
            body = {"status": "fail", "msg": detail}
        else:
            body = {"status": mapping.status, "error": mapping.title, "message": detail}
        if self._sidecar:
            sidecar = unit_error_sidecar(err, mapping.provenance, field=err.field or None)
            mode = ctx.config.errors.sidecar
            if mode != "headers":
                body["unit_error"] = sidecar
            if mode != "body":
                headers.update(sidecar_headers(sidecar))
        return ShapedError(status=mapping.status, body=body, headers=headers)

    def not_found(self, req: UnitRequest, ctx: UnitContext, *, describing: bool = False) -> ShapedError:
        return self.shape(
            UnitError(
                UnitErrorKind.NOT_FOUND,
                detail=(
                    f"{req.method} {req.path} is not a route on this Lightspeed K-Series unit. "
                    "GET /__unit/routes lists the surface this profile serves."
                ),
                info={"path": req.path, "method": req.method, "profile": ctx.config.profile},
            ),
            ctx,
            describing=describing,
        )

    def describe(self) -> dict[str, Any]:
        return {kind.value: mapping.as_json() for kind, mapping in LIGHTSPEED_K_ERROR_TABLE.items()}


assert_error_table_total(LIGHTSPEED_K_ERROR_TABLE, name="LIGHTSPEED_K_ERROR_TABLE")
