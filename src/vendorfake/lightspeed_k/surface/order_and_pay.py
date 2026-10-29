"""The three Order and Pay reads (source.json ``apeLookupBusinesses``, ``apeLoadMenus``, ``apeGetMenuByIdV2``).
Every body is the stored ``document``, so the fidelity validator is the oracle for its shape."""

from __future__ import annotations

import copy
from typing import Any

from vendorfake.core.kernel.reply import json_
from vendorfake.core.kernel.types import HandlerArgs, ReplyInit, Route, UnitContext, UnitError, UnitErrorKind
from vendorfake.lightspeed_k.entities import COL
from vendorfake.lightspeed_k.paths import APE_GET_MENU_BY_ID_V2, APE_LOAD_MENUS, APE_LOOKUP_BUSINESSES
from vendorfake.lightspeed_k.seed.constants import SEED_MENU_ID
from vendorfake.lightspeed_k.surface.common import BEARER_AUTH, SCOPE_ORDERS, LightspeedKDeps, int64_path, int64_query

__all__ = ["CAPABILITY", "LightspeedKOrderAndPaySurface", "known_location", "order_and_pay_routes"]

CAPABILITY = "order_and_pay"
_LOCATION = "businessLocationId"


def _not_found(detail: str, field: str, reason: str) -> UnitError:
    return UnitError(UnitErrorKind.NOT_FOUND, detail=detail, field=field, info={"reason": reason})


def _strip(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return {name: _strip(child, key) for name, child in value.items() if name != key}
    if isinstance(value, list):
        return [_strip(child, key) for child in value]
    return value


class LightspeedKOrderAndPaySurface:
    """The three reads; each declares ``orders-api``, which the kernel enforces."""

    __slots__ = ("_deps",)

    def __init__(self, deps: LightspeedKDeps) -> None:
        self._deps = deps

    def routes(self) -> tuple[Route, ...]:
        common: dict[str, Any] = {"capability": CAPABILITY, "auth": BEARER_AUTH, "scopes": (SCOPE_ORDERS,)}
        return (
            Route(
                method="GET",
                path=APE_LOOKUP_BUSINESSES,
                handler=self.businesses,
                operation_id="apeLookupBusinesses",
                summary="Every business and business location the access token sees (one merchant account per unit).",
                **common,
            ),
            Route(
                method="GET",
                path=APE_LOAD_MENUS,
                handler=self.menus,
                operation_id="apeLoadMenus",
                summary="The menus of one business location: menuName and ikentooMenuId.",
                **common,
            ),
            Route(
                method="GET",
                path=APE_GET_MENU_BY_ID_V2,
                handler=self.menu,
                operation_id="apeGetMenuByIdV2",
                summary="One menu in its V2 shape; richContent=true keeps itemRichData, accountProfile is ignored.",
                example_params={"menuId": str(SEED_MENU_ID)},
                **common,
            ),
        )

    # DOCUMENTED source.json: "all businesses and business locations associated with the access token"
    def businesses(self, args: HandlerArgs) -> ReplyInit:
        rows = args.ctx.store.collection(COL.businesses).all()
        return json_([copy.deepcopy(row["document"]) for row in rows])

    # DOCUMENTED tutorial: list the menus, then copy the ikentooMenuId to load one
    def menus(self, args: HandlerArgs) -> ReplyInit:
        location = known_location(args.ctx, int64_query(args, _LOCATION))
        rows = args.ctx.store.collection(COL.menus).all()
        return json_(
            [
                {"menuName": row["document"]["menuName"], "ikentooMenuId": row["document"]["ikentooMenuId"]}
                for row in rows
                if location in row["business_location_ids"]
            ]
        )

    # JUDGMENT: richContent=false strips itemRichData; accountProfile is accepted and ignored
    def menu(self, args: HandlerArgs) -> ReplyInit:
        menu_id = int64_path(args, "menuId")
        location = known_location(args.ctx, int64_query(args, _LOCATION))
        rich = _boolean(args.query("richContent"))
        stored = args.ctx.store.collection(COL.menus).get(str(menu_id))
        if stored is None:
            raise _not_found(f"Menu {menu_id} was not found.", "menuId", "unknown_menu")
        if location not in stored["business_location_ids"]:
            raise _not_found(
                f"Menu {menu_id} is not served at business location {location}.", "menuId", "menu_not_at_location"
            )
        document = copy.deepcopy(stored["document"])
        return json_(document if rich else _strip(document, "itemRichData"))


def order_and_pay_routes(deps: LightspeedKDeps) -> tuple[Route, ...]:
    return LightspeedKOrderAndPaySurface(deps).routes()


def known_location(ctx: UnitContext, location: int) -> int:
    for row in ctx.store.collection(COL.businesses).all():
        if any(entry.get("id") == location for entry in row["document"].get("businessLocations", [])):
            return location
    raise _not_found(f"Business location {location} was not found.", _LOCATION, "unknown_business_location")


def _boolean(raw: str | None) -> bool:
    if raw is None or raw.lower() == "false":
        return False
    if raw.lower() == "true":
        return True
    raise UnitError(UnitErrorKind.INVALID_VALUE, detail="richContent must be true or false.", field="richContent")
