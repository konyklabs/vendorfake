"""``POST /o/op/1/order/toGo`` (source.json ``apePlaceToGoOrder``; the tutorial's Part 3 B and Part 4).
The handler stores one order row; the notification comes from the journal, never from here."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, ValidationInfo
from pydantic import field_validator, model_validator

from vendorfake.core.kernel.reply import json_
from vendorfake.core.kernel.types import HandlerArgs, ReplyInit, Route, UnitContext, UnitError, UnitErrorKind
from vendorfake.core.util.json import compact
from vendorfake.lightspeed_k.entities import COL
from vendorfake.lightspeed_k.paths import APE_PLACE_TO_GO_ORDER
from vendorfake.lightspeed_k.seed.constants import (
    SEED_BUSINESS_LOCATION_ID,
    SEED_EXAMPLE_ENDPOINT_ID,
    SEED_UNKNOWN_SKU,
)
from vendorfake.lightspeed_k.surface.common import BEARER_AUTH, SCOPE_ORDERS, LightspeedKDeps, validate_body
from vendorfake.lightspeed_k.surface.order_and_pay import known_location

__all__ = ["CAPABILITY", "EXAMPLE_TO_GO", "LightspeedKToGoSurface", "ToGoOrderRequest", "to_go_routes"]

CAPABILITY = "order_and_pay"
OPERATION = "apePlaceToGoOrder"
_INT32 = 2**31
_INT64 = 2**63
_BODY = ConfigDict(extra="ignore")
EXAMPLE_TO_GO: dict[str, Any] = {
    "businessLocationId": SEED_BUSINESS_LOCATION_ID,
    "thirdPartyReference": "unit-k-example-order",
    "endpointId": SEED_EXAMPLE_ENDPOINT_ID,
    "customerInfo": {"firstName": "Ada"},
    "items": [{"quantity": 1, "sku": SEED_UNKNOWN_SKU}],
}
Number = StrictFloat | StrictInt


class CustomerInfo(BaseModel):
    model_config = _BODY

    firstName: StrictStr = Field(min_length=1, max_length=128)
    lastName: StrictStr | None = None
    thirdPartyReference: StrictStr | None = None
    email: StrictStr | None = None
    contactNumberAsE164: StrictStr | None = None


class ItemLine(BaseModel):
    model_config = _BODY

    quantity: StrictInt = Field(ge=-_INT32, lt=_INT32)
    sku: StrictStr = Field(max_length=25)
    customItemName: StrictStr | None = None
    customItemPrice: Number | None = None
    discountAmountOverride: Number | None = None
    discountPercentOverride: Number | None = None
    discountCode: StrictStr | None = None
    modifiers: list[dict[str, Any]] | None = None
    subItems: list[dict[str, Any]] | None = None

    # DOCUMENTED source.json: an amount and a percentage override are alternatives
    @model_validator(mode="after")
    def _one_override(self) -> ItemLine:
        if self.discountAmountOverride is not None and self.discountPercentOverride is not None:
            raise ValueError("at most one of discountAmountOverride and discountPercentOverride may be given")
        return self


class Payment(BaseModel):
    model_config = _BODY

    paymentAmount: Number
    paymentMethod: StrictStr | None = None
    tipAmount: Number | None = None


class ToGoOrderRequest(BaseModel):
    model_config = _BODY

    businessLocationId: StrictInt = Field(ge=-_INT64, lt=_INT64)
    thirdPartyReference: StrictStr = Field(min_length=1, max_length=48)
    endpointId: StrictStr
    customerInfo: CustomerInfo
    orderNote: StrictStr | None = None
    maxTimeToAttemptOrderDeliverToPos: StrictInt | None = Field(default=None, ge=60000, lt=_INT32)
    staffId: StrictInt | None = None
    accountProfileCode: StrictStr | None = None
    scheduledTimeForOrderAsIso8601: StrictStr | None = None
    payment: Payment | None = None
    collectionCode: StrictStr | None = Field(default=None, max_length=8)
    orderCollectionTimeAsIso8601: StrictStr | None = None
    items: list[ItemLine] = Field(default_factory=list)
    deliveryAddress: dict[str, Any] | None = None
    targetPrinterProfileId: StrictInt | None = None

    # DOCUMENTED source.json: "Must be in the future"; JUDGMENT: RFC 3339 with an offset
    @field_validator("scheduledTimeForOrderAsIso8601", "orderCollectionTimeAsIso8601")
    @classmethod
    def _future(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return value
        try:
            instant = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("must be an RFC 3339 date-time") from exc
        if instant.tzinfo is None:
            raise ValueError("must carry a UTC offset")
        now_ms = (info.context or {}).get("now_ms")
        if now_ms is not None and instant.timestamp() * 1000 <= now_ms:
            raise ValueError("must be in the future")
        return value


def _has_sku(entries: Any, sku: str) -> bool:
    return isinstance(entries, list) and any(
        isinstance(entry, dict)
        and ((entry.get("@type") == "menuItem" and entry.get("sku") == sku) or _has_sku(entry.get("menuEntry"), sku))
        for entry in entries
    )


def _sku_known(ctx: UnitContext, location: int, sku: str) -> bool:
    return any(
        location in row["business_location_ids"] and _has_sku(row["document"].get("menuEntryGroups"), sku)
        for row in ctx.store.collection(COL.menus).all()
    )


class LightspeedKToGoSurface:
    """The to-go order write, bound to one vendor's id stream."""

    __slots__ = ("_deps",)

    def __init__(self, deps: LightspeedKDeps) -> None:
        self._deps = deps

    def routes(self) -> tuple[Route, ...]:
        return (
            Route(
                method="POST",
                path=APE_PLACE_TO_GO_ORDER,
                capability=CAPABILITY,
                handler=self.place,
                operation_id=OPERATION,
                auth=BEARER_AUTH,
                scopes=(SCOPE_ORDERS,),
                example_body=EXAMPLE_TO_GO,
                summary=(
                    "A takeaway or delivery order; 200 {status: ok} means received, and the outcome arrives as a "
                    "notification at the endpoint it names. The example orders an unknown SKU, so the POS refuses "
                    "it and its reference stays free."
                ),
            ),
        )

    def place(self, args: HandlerArgs) -> ReplyInit:
        ctx = args.ctx
        order = validate_body(ToGoOrderRequest, args.body(), now_ms=ctx.clock.now())
        location = known_location(ctx, order.businessLocationId)
        orders = ctx.store.collection(COL.orders)
        reference = order.thirdPartyReference
        # DOCUMENTED source.json: "Must be unique", 409; JUDGMENT tutorial: only an order that reached the POS spends it
        if orders.find(lambda row: row.get("thirdPartyReference") == reference and row.get("status") != "FAILURE"):
            raise UnitError(
                UnitErrorKind.CONFLICT,
                detail=f"reference has already been used {reference}",
                field="thirdPartyReference",
                info={"envelope": "to_go_conflict"},
            )
        # JUDGMENT tutorial: a SKU on no menu at the location is a "problem with the order", refused by the POS
        unknown = next((line.sku for line in order.items if not _sku_known(ctx, location, line.sku)), None)
        ids = self._deps.ids
        row = {
            "id": ids.uuid(),
            "status": "SUCCESS" if unknown is None else "FAILURE",
            "reason": None if unknown is None else f"Unknown SKU {unknown} at business location {location}",
            "thirdPartyReference": reference,
            "businessLocationId": location,
            "endpointId": order.endpointId,
            "ikentooAccountIdentifier": ids.account_identifier() if unknown is None else None,
            "created_at_ms": int(ctx.clock.now()),
            "request": order.model_dump(exclude_none=True),
        }
        orders.insert(compact(row), {"operation_id": OPERATION})
        # DOCUMENTED tutorial: 200 "doesn't necessarily mean that it has been sent to the POS"
        return json_({"status": "ok"})


def to_go_routes(deps: LightspeedKDeps) -> tuple[Route, ...]:
    return LightspeedKToGoSurface(deps).routes()
