"""The tax breakdown of a proposed order (source.json ``tax-preview-apiTaxBreakdown``): integer cents inside, numbers on the wire."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vendorfake.core.kernel.reply import json_
from vendorfake.core.kernel.types import HandlerArgs, ReplyInit, Route, UnitContext, UnitError, UnitErrorKind
from vendorfake.core.util.json import compact
from vendorfake.lightspeed_k.errors import ENVELOPE_INFO_KEY, STATUS_STRING_ENVELOPE
from vendorfake.lightspeed_k.paths import TAX_PREVIEW_API_TAX_BREAKDOWN
from vendorfake.lightspeed_k.seed.constants import SEED_BUSINESS_LOCATION_ID
from vendorfake.lightspeed_k.surface.common import BEARER_AUTH, SCOPE_ORDERS, LightspeedKDeps, int64_path, validate_body
from vendorfake.lightspeed_k.surface.order_and_pay import CAPABILITY, known_location, menu_item

__all__ = [
    "CAPABILITY",
    "LightspeedKTaxBreakdownSurface",
    "TaxBreakdownRequest",
    "price",
    "price_line",
    "rate_string",
    "tax_breakdown_routes",
]

OPERATION = "tax-preview-apiTaxBreakdown"
_LOCATION = "businessLocationId"
_INT64 = 2**63
_CENTS = Decimal(100)


def _d(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _fits(cents: Decimal | int) -> bool:
    return -_INT64 <= cents < _INT64


# JUDGMENT: half-up, once per line amount and once per tax part
def half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


# DOCUMENTED source.json: "1.20" means 20% tax; JUDGMENT: at least two decimals, more only as configured
def rate_string(percentage: Any) -> str:
    rate = (Decimal(1) + _d(percentage) / _CENTS).normalize()
    if int(rate.as_tuple().exponent) > -2:
        rate = rate.quantize(Decimal("0.01"))
    return str(rate)


def price_line(price: Any, quantity: Decimal, percentages: Sequence[Any], included: bool) -> tuple[int, list[int], int]:
    raw = _d(price) * quantity * _CENTS
    if not _fits(raw):
        raise OverflowError("the line amount does not fit an int64 of cents")
    amount = half_up(raw)
    rates = [_d(percentage) / _CENTS for percentage in percentages]
    if included:
        # JUDGMENT: an inclusive price is split as gross / (1 + R), each part rounded on its own
        base = Decimal(amount) / (1 + sum(rates, Decimal(0)))
        parts = [half_up(base * rate) for rate in rates]
        return amount - sum(parts), parts, amount
    parts = [half_up(amount * rate) for rate in rates]
    return amount, parts, amount + sum(parts)


@dataclass(frozen=True, slots=True)
class Pricing:
    sku: str
    quantity: Decimal
    price: Any
    percentages: tuple[Any, ...]
    descriptions: tuple[str | None, ...]
    included: bool


def price(lines: Iterable[Pricing]) -> dict[str, Any]:
    transactions: list[dict[str, Any]] = []
    taxes: dict[tuple[str | None, Any, bool], list[int]] = {}
    net_total = tax_total = gross_total = 0
    for line in lines:
        net, parts, gross = price_line(line.price, line.quantity, line.percentages, line.included)
        transactions.append(
            {
                "sku": line.sku,
                "quantity": float(line.quantity),
                "unitPrice": line.price,
                "netAmount": net / 100,
                "grossAmount": gross / 100,
                "taxAmount": sum(parts) / 100,
            }
        )
        # JUDGMENT: one tax line per (description, percentage, inclusion), first seen first; a line's net joins it once
        mine: dict[tuple[str | None, Any, bool], int] = {}
        for description, percentage, part in zip(line.descriptions, line.percentages, parts, strict=True):
            key = (description, percentage, line.included)
            mine[key] = mine.get(key, 0) + part
        for key, part in mine.items():
            sums = taxes.setdefault(key, [0, 0])
            sums[0] += net
            sums[1] += part
        net_total, tax_total, gross_total = net_total + net, tax_total + sum(parts), gross_total + gross
    if not all(_fits(total) for total in (net_total, tax_total, gross_total)):
        raise OverflowError("an order total does not fit an int64 of cents")
    # JUDGMENT: taxCode and taxName are omitted; the seeded menu carries neither
    tax_lines = [
        compact(
            {
                "description": description,
                "taxRate": rate_string(percentage),
                "netAmount": net / 100,
                "grossAmount": (net + tax) / 100,
                "taxAmount": tax / 100,
                "taxIncluded": included,
            }
        )
        for (description, percentage, included), (net, tax) in taxes.items()
    ]
    return {
        "transactions": transactions,
        "taxLines": tax_lines,
        "totalNetAmountInCents": net_total,
        "totalGrossAmountInCents": gross_total,
        "totalTaxAmountInCents": tax_total,
        "amountDue": gross_total / 100,
    }


_BODY = ConfigDict(extra="ignore", strict=True)


# JUDGMENT: quantity defaults to 1 and must be a finite number above 0
class SubLine(BaseModel):
    model_config = _BODY

    sku: str = Field(max_length=25)
    quantity: float = Field(default=1, gt=0, allow_inf_nan=False)


class Line(SubLine):
    subItems: list[SubLine] = Field(default_factory=list)


# JUDGMENT: accountProfileCode is accepted and ignored
class TaxBreakdownRequest(BaseModel):
    model_config = _BODY

    accountProfileCode: str | None = None
    items: list[Line] = Field(default_factory=list)


class LightspeedKTaxBreakdownSurface:
    """The tax breakdown, a read priced from the seeded menu."""

    __slots__ = ("_deps",)

    def __init__(self, deps: LightspeedKDeps) -> None:
        self._deps = deps

    def routes(self) -> tuple[Route, ...]:
        return (
            Route(
                method="POST",
                path=TAX_PREVIEW_API_TAX_BREAKDOWN,
                capability=CAPABILITY,
                handler=self.breakdown,
                operation_id=OPERATION,
                auth=BEARER_AUTH,
                scopes=(SCOPE_ORDERS,),
                example_params={_LOCATION: str(SEED_BUSINESS_LOCATION_ID)},
                summary=(
                    "The tax breakdown of a proposed order, priced from the seeded menu's tax lines (JUDGMENT "
                    "arithmetic); a read, so no example body."
                ),
            ),
        )

    # DOCUMENTED source.json: 400/403/404/503 answer the string-status envelope under */*
    def breakdown(self, args: HandlerArgs) -> ReplyInit:
        try:
            return self._breakdown(args)
        except UnitError as err:
            raise _status_string(err) from err

    def _breakdown(self, args: HandlerArgs) -> ReplyInit:
        ctx = args.ctx
        location = int64_path(args, _LOCATION)
        # DOCUMENTED source.json: businessLocationId has minimum 1
        if location < 1:
            raise UnitError(
                UnitErrorKind.INVALID_VALUE, detail="businessLocationId must be at least 1.", field=_LOCATION
            )
        # DOCUMENTED source.json: requestBody.required; JUDGMENT: an empty body is 400 and {} is an empty order
        if args.body_text().strip() == "":
            raise UnitError(UnitErrorKind.MISSING_FIELD, detail="A JSON request body is required.", field="body")
        order = validate_body(TaxBreakdownRequest, args.body())
        known_location(ctx, location)
        lines: list[Pricing] = []
        for n, item in enumerate(order.items):
            quantity = _d(item.quantity)
            lines.append(_pricing(ctx, location, item.sku, quantity, f"items.{n}.sku"))
            # JUDGMENT: a sub-item is its own line, right after its parent, at parent x sub quantity
            for m, sub in enumerate(item.subItems):
                lines.append(
                    _pricing(ctx, location, sub.sku, quantity * _d(sub.quantity), f"items.{n}.subItems.{m}.sku")
                )
        try:
            return json_(price(lines))
        except OverflowError as exc:
            # JUDGMENT: a valid double can still overflow an int64 of cents
            raise UnitError(
                UnitErrorKind.INVALID_VALUE, detail="The order total does not fit an int64 of cents.", field="items"
            ) from exc


def _pricing(ctx: UnitContext, location: int, sku: str, quantity: Decimal, field: str) -> Pricing:
    entry = menu_item(ctx, location, sku)
    if entry is None:
        # JUDGMENT: an unknown SKU is a 400 naming the body value, not a 404
        raise UnitError(
            UnitErrorKind.INVALID_VALUE,
            detail=f"Unknown SKU {sku} at business location {location}",
            field=field,
            info={"rejected_value": sku},
        )
    # JUDGMENT: taxes[] is authoritative; amount, defaultTaxAmount and defaultTaxPercentage are never read
    taxes = [tax for tax in entry.get("taxes") or [] if isinstance(tax, dict)]
    return Pricing(
        sku=sku,
        quantity=quantity,
        price=entry.get("productPrice", 0),
        percentages=tuple(tax.get("percentage", 0) for tax in taxes),
        descriptions=tuple(tax.get("description") for tax in taxes),
        included=bool(entry.get("taxIncludedInPrice", False)),
    )


def _status_string(err: UnitError) -> UnitError:
    info = {**(err.info or {}), ENVELOPE_INFO_KEY: STATUS_STRING_ENVELOPE}
    return UnitError(
        err.kind,
        detail=err.detail,
        field=err.field,
        info=info,
        delay_ms=err.delay_ms,
        fault=err.fault,
        rule_id=err.rule_id,
    )


def tax_breakdown_routes(deps: LightspeedKDeps) -> tuple[Route, ...]:
    return LightspeedKTaxBreakdownSurface(deps).routes()
