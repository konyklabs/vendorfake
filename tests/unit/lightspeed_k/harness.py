"""One started Lightspeed K-Series unit, driven in process, for the behaviour suites.

Every response goes through ``vendorfake.fidelity``'s ``ValidatingClient`` over the
K-Series extract (D-006). The extract is never committed (``vendored: false``): it
is cut from a fetch into the local cache, so a cold cache with no network drives
the suite unvalidated and the terminal summary says SKIPPED (T1, roadmap#116).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from vendorfake import create_unit
from vendorfake.core.kernel.unit import Unit
from vendorfake.core.transport.inprocess import InProcessClient, InProcessResponse
from vendorfake.core.webhooks.sink import MemorySink
from vendorfake.fidelity import Surface, load_declaration, load_extract
from vendorfake.fidelity.cache import Unavailable
from vendorfake.fidelity.validate import Ledger, ValidatingClient
from vendorfake.lightspeed_k.seed.constants import (
    SEED_ACCESS_TOKEN,
    SEED_BASIC_AUTH,
    SEED_BUSINESS_LOCATION_ID,
    SEED_CLIENT_ID,
    SEED_FINANCIAL_ONLY_ACCESS_TOKEN,
    SEED_REDIRECT_URI,
    SEED_REFRESH_TOKEN,
)

FIDELITY_ANCHOR = "vendorfake.lightspeed_k.fidelity"
LEDGER = Ledger()
FORM = {"content-type": "application/x-www-form-urlencoded"}
TOKEN = "/oauth/token"
AUTHORIZE = "/oauth/authorize"
BUSINESSES = "/o/op/data/businesses"
MENUS = "/o/op/1/menu/list"
TO_GO = "/o/op/1/order/toGo"
WEBHOOK = "/o/wh/1/webhook"
LOCATION = str(SEED_BUSINESS_LOCATION_ID)

FIDELITY_UNAVAILABLE_REASON: str | None = None
try:
    SURFACE: Surface | None = Surface(load_declaration(FIDELITY_ANCHOR), load_extract(FIDELITY_ANCHOR))
except Unavailable as exc:
    SURFACE = None
    FIDELITY_UNAVAILABLE_REASON = str(exc)


class Silent:
    """A logger that says nothing."""

    def debug(self, msg: str, fields: Mapping[str, Any] | None = None) -> None: ...
    def info(self, msg: str, fields: Mapping[str, Any] | None = None) -> None: ...
    def warn(self, msg: str, fields: Mapping[str, Any] | None = None) -> None: ...
    def error(self, msg: str, fields: Mapping[str, Any] | None = None) -> None: ...


def menu_path(menu_id: object) -> str:
    return f"/o/op/2/menu/load/{menu_id}"


@dataclass(frozen=True, slots=True)
class Harness:
    """A started unit, the client that drives it, and the seeded headers."""

    unit: Unit
    api: InProcessClient
    auth: dict[str, str]

    @property
    def read_auth(self) -> dict[str, str]:
        """The seeded bearer that carries financial-api only."""
        return {"authorization": f"bearer {SEED_FINANCIAL_ONLY_ACCESS_TOKEN}"}

    @property
    def basic(self) -> dict[str, str]:
        return {"authorization": SEED_BASIC_AUTH}

    def get(self, path: str, **kwargs: Any) -> InProcessResponse:
        kwargs.setdefault("headers", self.auth)
        return self.api.get(path, **kwargs)

    def post(self, path: str, body: Any = None, **kwargs: Any) -> InProcessResponse:
        kwargs.setdefault("headers", self.auth)
        return self.api.post(path, body, **kwargs)

    def put(self, path: str, body: Any = None, **kwargs: Any) -> InProcessResponse:
        kwargs.setdefault("headers", self.auth)
        return self.api.put(path, body, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> InProcessResponse:
        kwargs.setdefault("headers", self.auth)
        return self.api.delete(path, **kwargs)

    def drain(self) -> list[dict[str, Any]]:
        self.api.post("/__unit/webhooks/drain", {})
        return list(self.api.get("/__unit/webhooks/deliveries").json()["deliveries"])

    def authorize(self, **overrides: str | None) -> InProcessResponse:
        query: dict[str, str | None] = {
            "response_type": "code",
            "client_id": SEED_CLIENT_ID,
            "redirect_uri": SEED_REDIRECT_URI,
            "scope": "financial-api orders-api",
            "state": "opaque-consumer-state",
            **overrides,
        }
        return self.api.get(AUTHORIZE, query={k: v for k, v in query.items() if v is not None})

    def code(self, **overrides: str | None) -> str:
        res = self.authorize(**overrides)
        assert res.status == 302, res.text
        return redirect_query(res)["code"]

    def exchange(self, code: str, *, basic: str | None = None, **query: str) -> InProcessResponse:
        params = {"grant_type": "authorization_code", "code": code, "redirect_uri": SEED_REDIRECT_URI, **query}
        return self.api.post(TOKEN, None, query=params, headers={"authorization": basic or self.basic["authorization"]})

    def refresh(self, refresh_token: str = SEED_REFRESH_TOKEN, *, basic: str | None = None) -> InProcessResponse:
        body = urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token})
        return self.api.post(TOKEN, body, headers={**FORM, "authorization": basic or self.basic["authorization"]})

    def menus(self, location: str = LOCATION, **kwargs: Any) -> InProcessResponse:
        return self.get(MENUS, query={"businessLocationId": location}, **kwargs)


def webhook_path(endpoint_id: str) -> str:
    return f"{WEBHOOK}/{endpoint_id}"


def tax_breakdown_path(location: object) -> str:
    return f"/tp/v1/business-locations/{location}/tax-breakdown"


def redirect_query(res: InProcessResponse) -> dict[str, str]:
    location = res.header("location") or ""
    return {key: values[0] for key, values in parse_qs(urlsplit(location).query).items()}


def bearer(token: str) -> dict[str, str]:
    return {"authorization": f"bearer {token}"}


def harness(profile: str = "full", **kwargs: Any) -> Iterator[Harness]:
    """Start a unit on ``profile`` with ``VENDORFAKE_ERROR_SIDECAR=both``; stop it however the test ends."""
    kwargs.setdefault("sink", MemorySink())
    kwargs["env"] = {"VENDORFAKE_ERROR_SIDECAR": "both", **kwargs.pop("env", {})}
    unit = create_unit(vendor="lightspeed-k", profile=profile, logger=Silent(), **kwargs)
    api: InProcessClient = (
        InProcessClient(unit) if SURFACE is None else ValidatingClient(unit, SURFACE, LEDGER, strict_undeclared=False)
    )
    try:
        yield Harness(unit=unit, api=api, auth=bearer(SEED_ACCESS_TOKEN))
    finally:
        unit.stop()
