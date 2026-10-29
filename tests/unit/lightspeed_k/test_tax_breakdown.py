"""POST /tp/v1/business-locations/{businessLocationId}/tax-breakdown (source.json tax-preview-apiTaxBreakdown)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tests.unit.lightspeed_k.conftest import VIRTUAL
from tests.unit.lightspeed_k.harness import LEDGER, LOCATION, SURFACE, Harness, harness, tax_breakdown_path
from vendorfake.lightspeed_k.seed import constants as c
from vendorfake.lightspeed_k.surface.order_and_pay import menu_item
from vendorfake.lightspeed_k.surface.tax_breakdown import Pricing, price, price_line, rate_string

PATH = tax_breakdown_path(LOCATION)
ROUTE = "POST /tp/v1/business-locations/{businessLocationId}/tax-breakdown"
ORDER: dict[str, Any] = {"items": [{"sku": "UNITK-001", "quantity": 2}, {"sku": "UNITK-002"}]}
EXPECTED: dict[str, Any] = {
    "transactions": [
        {
            "sku": "UNITK-001",
            "quantity": 2.0,
            "unitPrice": 12.5,
            "netAmount": 25.0,
            "grossAmount": 27.5,
            "taxAmount": 2.5,
        },
        {
            "sku": "UNITK-002",
            "quantity": 1.0,
            "unitPrice": 4.0,
            "netAmount": 3.64,
            "grossAmount": 4.0,
            "taxAmount": 0.36,
        },
    ],
    "taxLines": [
        {
            "description": "10% VAT",
            "taxRate": "1.10",
            "netAmount": 25.0,
            "grossAmount": 27.5,
            "taxAmount": 2.5,
            "taxIncluded": False,
        },
        {
            "description": "10% VAT",
            "taxRate": "1.10",
            "netAmount": 3.64,
            "grossAmount": 4.0,
            "taxAmount": 0.36,
            "taxIncluded": True,
        },
    ],
    "totalNetAmountInCents": 2864,
    "totalGrossAmountInCents": 3150,
    "totalTaxAmountInCents": 286,
    "amountDue": 31.5,
}
EMPTY: dict[str, Any] = {
    "transactions": [],
    "taxLines": [],
    "totalNetAmountInCents": 0,
    "totalGrossAmountInCents": 0,
    "totalTaxAmountInCents": 0,
    "amountDue": 0.0,
}
TOTALS = ("totalNetAmountInCents", "totalGrossAmountInCents", "totalTaxAmountInCents")


def wire(res: Any) -> dict[str, Any]:
    return {key: value for key, value in res.json().items() if key != "unit_error"}


def items(*lines: dict[str, Any]) -> dict[str, Any]:
    return {"items": list(lines)}


# --- pure arithmetic -------------------------------------------------------------------------------------------------

TABLE = [
    (12.50, 1, [10], True, 1136, [114], 1250),
    (4.00, 1, [10], True, 364, [36], 400),
    (12.50, 1, [10], False, 1250, [125], 1375),
    (12.50, 2, [10], False, 2500, [250], 2750),
    (12.50, 2, [10], True, 2273, [227], 2500),
    (0.05, 1, [10], False, 5, [1], 6),
    (0.25, 1, [10], False, 25, [3], 28),
    (12.50, 0.5, [10], False, 625, [63], 688),
    (3.00, 1, [], False, 300, [], 300),
    (3.00, 1, [], True, 300, [], 300),
    (10.00, 1, [5, 7], False, 1000, [50, 70], 1120),
    (11.20, 1, [5, 7], True, 1000, [50, 70], 1120),
    (4.00, 1, [5, 5], True, 364, [18, 18], 400),
    (0.125, 1, [100], False, 13, [13], 26),
    (1.00, 0.3, [8.875], False, 30, [3], 33),
]


@pytest.mark.parametrize(("unit_price", "qty", "percentages", "included", "net", "parts", "gross"), TABLE)
def test_price_line_is_half_up_per_line_and_per_part(
    unit_price: float, qty: float, percentages: list[float], included: bool, net: int, parts: list[int], gross: int
) -> None:
    got = price_line(unit_price, Decimal(str(qty)), percentages, included)
    assert (got[0], list(got[1]), got[2]) == (net, parts, gross)
    assert got[0] + sum(got[1]) == got[2]


def test_rounding_is_per_line_not_per_order() -> None:
    basket = [(12.5, 2, [10], True), (4.0, 1, [10], True)]
    tax = sum(sum(price_line(p, Decimal(str(q)), r, i)[1]) for p, q, r, i in basket)
    assert tax == 263


@pytest.mark.parametrize(
    ("percentage", "rate"),
    [(20, "1.20"), (10.0, "1.10"), (8.875, "1.08875"), (0, "1.00"), (5.5, "1.055"), (7.7, "1.077"), (100, "2.00")],
)
def test_rate_string(percentage: float, rate: str) -> None:
    assert rate_string(percentage) == rate


def test_price_of_nothing_is_empty_arrays_and_zeros() -> None:
    assert price([]) == EMPTY


# 1e300 overflows one line's cents; 7e15 of UNITK-001 fits as a line (8.75e18) but its gross (9.625e18) does not.
OVERFLOWING_LINE = Decimal("1e300")
OVERFLOWING_TOTAL = Decimal("7e15")


def test_a_line_beyond_int64_cents_overflows_in_price_line() -> None:
    with pytest.raises(OverflowError, match="line amount"):
        price_line(12.5, OVERFLOWING_LINE, [10.0], False)


def test_a_gross_beyond_int64_cents_overflows_in_price_though_its_line_fits() -> None:
    assert price_line(12.5, OVERFLOWING_TOTAL, [10.0], False)[2] >= 2**63
    line = Pricing("UNITK-001", OVERFLOWING_TOTAL, 12.5, (10.0,), ("10% VAT",), False)
    with pytest.raises(OverflowError, match="order total"):
        price([line])


# --- the priced body -------------------------------------------------------------------------------------------------


def test_the_seeded_order_prices_to_the_worked_example(h: Harness) -> None:
    res = h.post(PATH, ORDER)
    assert res.status == 200, res.text
    body = res.json()
    assert wire(res) == EXPECTED
    for key in TOTALS:
        assert type(body[key]) is int, key
    assert isinstance(body["amountDue"], float)
    for row in body["transactions"] + body["taxLines"]:
        for key in ("netAmount", "grossAmount", "taxAmount"):
            assert isinstance(row[key], float), (row, key)
    assert round(body["amountDue"] * 100) == body["totalGrossAmountInCents"]
    assert body["taxLines"][0]["taxRate"] == "1.10" and isinstance(body["taxLines"][0]["taxRate"], str)
    assert [line["taxIncluded"] for line in body["taxLines"]] == [False, True]


@pytest.mark.parametrize("payload", [{}, {"items": []}])
def test_an_empty_order_is_zeros(h: Harness, payload: dict[str, Any]) -> None:
    res = h.post(PATH, payload)
    assert res.status == 200, res.text
    assert wire(res) == EMPTY


def test_quantity_defaults_to_one(h: Harness) -> None:
    res = h.post(PATH, items({"sku": "UNITK-002"}))
    assert res.status == 200, res.text
    assert res.json()["transactions"][0]["quantity"] == 1.0


def test_the_same_sku_twice_is_two_lines(h: Harness) -> None:
    res = h.post(PATH, items({"sku": "UNITK-002"}, {"sku": "UNITK-002"}))
    assert res.status == 200, res.text
    assert [row["sku"] for row in res.json()["transactions"]] == ["UNITK-002", "UNITK-002"]


def test_a_sub_item_is_its_own_line_at_parent_times_sub_quantity(h: Harness) -> None:
    payload = items({"sku": "UNITK-001", "quantity": 3, "subItems": [{"sku": "UNITK-002", "quantity": 2}]})
    res = h.post(PATH, payload)
    assert res.status == 200, res.text
    lines = res.json()["transactions"]
    assert [(row["sku"], row["quantity"]) for row in lines] == [("UNITK-001", 3.0), ("UNITK-002", 6.0)]


def test_the_account_profile_code_changes_nothing(h: Harness) -> None:
    res = h.post(PATH, {**ORDER, "accountProfileCode": "AAP-TOGO"})
    assert res.status == 200, res.text
    assert wire(res) == EXPECTED


def test_the_breakdown_is_a_read(h: Harness) -> None:
    before = len(h.api.get("/__unit/journal").json()["entries"])
    first = h.post(PATH, ORDER)
    second = h.post(PATH, ORDER)
    assert first.status == second.status == 200
    assert wire(first) == wire(second)
    assert len(h.api.get("/__unit/journal").json()["entries"]) == before


# --- refusals --------------------------------------------------------------------------------------------------------


def refused(res: Any, status: int, kind: str) -> dict[str, Any]:
    assert res.status == status, res.text
    body = res.json()
    assert body["status"] == str(status) and isinstance(body["status"], str)
    assert body["unit_error"]["kind"] == kind
    return dict(body)


def test_an_empty_body_is_missing_field(h: Harness) -> None:
    body = refused(
        h.post(PATH, raw_body=b"", headers={**h.auth, "content-type": "application/json"}), 400, "missing_field"
    )
    assert body["apiSubExceptions"][0]["field"] == "body"


def test_malformed_json_is_invalid_json(h: Harness) -> None:
    refused(h.post(PATH, raw_body=b"{", headers={**h.auth, "content-type": "application/json"}), 400, "invalid_json")


def test_a_non_object_body_is_invalid_value(h: Harness) -> None:
    body = refused(h.post(PATH, []), 400, "invalid_value")
    assert body["unit_error"]["field"] == "body"


def test_a_missing_sku_is_missing_field(h: Harness) -> None:
    body = refused(h.post(PATH, items({"quantity": 1})), 400, "missing_field")
    assert body["apiSubExceptions"][0]["field"] == "items.0.sku"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (items({"sku": "U" * 26}), "items.0.sku"),
        (items({"sku": "UNITK-001", "subItems": [{"sku": "U" * 26}]}), "items.0.subItems.0.sku"),
    ],
)
def test_a_sku_over_25_characters_is_refused_by_validation(h: Harness, payload: dict[str, Any], field: str) -> None:
    body = refused(h.post(PATH, payload), 400, "invalid_value")
    assert [(e["field"], e["type"]) for e in body["unit_error"]["errors"]] == [(field, "string_too_long")]
    assert "rejectedValue" not in body["apiSubExceptions"][0]


def test_a_sku_of_25_characters_passes_validation_and_reaches_the_menu(h: Harness) -> None:
    body = refused(h.post(PATH, items({"sku": "U" * 25})), 400, "invalid_value")
    assert body["apiSubExceptions"][0]["rejectedValue"] == "U" * 25


@pytest.mark.parametrize(
    "line",
    [
        {"sku": "UNITK-001", "quantity": "2"},
        {"sku": "UNITK-001", "quantity": True},
        {"sku": "UNITK-001", "quantity": 0},
        {"sku": "UNITK-001", "quantity": -1},
    ],
)
def test_a_bad_line_is_invalid_value(h: Harness, line: dict[str, Any]) -> None:
    refused(h.post(PATH, items(line)), 400, "invalid_value")


def test_a_nan_quantity_is_invalid_value(h: Harness) -> None:
    raw = b'{"items":[{"sku":"UNITK-001","quantity":NaN}]}'
    refused(h.post(PATH, raw_body=raw, headers={**h.auth, "content-type": "application/json"}), 400, "invalid_value")


def test_an_unknown_sku_is_400_with_one_sub_exception(h: Harness) -> None:
    body = refused(h.post(PATH, items({"sku": c.SEED_UNKNOWN_SKU})), 400, "invalid_value")
    assert body["apiSubExceptions"] == [
        {
            "field": "items.0.sku",
            "rejectedValue": "UNITK-404",
            "message": "Unknown SKU UNITK-404 at business location 100000000101",
        }
    ]


def test_an_unknown_sub_item_sku_names_its_path(h: Harness) -> None:
    payload = items({"sku": "UNITK-001", "subItems": [{"sku": c.SEED_UNKNOWN_SKU}]})
    body = refused(h.post(PATH, payload), 400, "invalid_value")
    assert body["apiSubExceptions"][0]["field"] == "items.0.subItems.0.sku"


@pytest.mark.parametrize("quantity", [float(OVERFLOWING_LINE), float(OVERFLOWING_TOTAL)], ids=["line", "total"])
def test_a_line_or_total_beyond_int64_cents_is_invalid_value(h: Harness, quantity: float) -> None:
    body = refused(h.post(PATH, items({"sku": "UNITK-001", "quantity": quantity})), 400, "invalid_value")
    assert body["unit_error"]["field"] == "items"


@pytest.mark.parametrize("location", ["0", "-5", "abc"])
def test_a_bad_location_is_400(h: Harness, location: str) -> None:
    body = refused(h.post(tax_breakdown_path(location), ORDER), 400, "invalid_value")
    assert body["unit_error"]["field"] == "businessLocationId"


def test_an_unknown_location_is_404_in_the_string_envelope(h: Harness) -> None:
    body = refused(h.post(tax_breakdown_path(999), ORDER), 404, "not_found")
    assert body["apiSubExceptions"][0]["field"] == "businessLocationId"


def test_a_financial_only_token_is_the_kernel_403_absorbed_by_the_deviations(h: Harness) -> None:
    before = LEDGER.row(ROUTE).deviated
    res = h.post(PATH, ORDER, headers=h.read_auth)
    assert res.status == 403, res.text
    body = res.json()
    assert body["status"] == 403 and type(body["status"]) is int
    assert body["unit_error"]["kind"] == "forbidden_scope"
    if SURFACE is not None:
        assert LEDGER.row(ROUTE).deviated == before + 2


def test_no_token_is_401(h: Harness) -> None:
    res = h.post(PATH, ORDER, headers={})
    assert res.status == 401, res.text


def test_an_unavailable_rule_answers_the_string_envelope(h: Harness) -> None:
    rule = {"id": "down", "scope": "request", "fault": "unavailable", "match": {"route": ROUTE}, "when": {"times": 1}}
    assert h.api.post("/__unit/chaos/rules", rule).status == 200
    res = h.post(PATH, ORDER)
    assert res.status == 503, res.text
    body = wire(res)
    assert set(body) == {"status", "message", "apiSubExceptions"}
    assert (body["status"], body["apiSubExceptions"]) == ("503", [])


# --- profiles --------------------------------------------------------------------------------------------------------


def test_orders_only_serves_the_route(profile_harness: Callable[..., Iterator[Harness]]) -> None:
    for started in profile_harness("orders-only"):
        res = started.post(PATH, ORDER)
        assert res.status == 200, res.text


def test_oauth_only_disables_the_route(profile_harness: Callable[..., Iterator[Harness]]) -> None:
    # /__unit/routes lists every route with its capability; the capability listing says what is served.
    for started in profile_harness("oauth-only"):
        rows = started.api.get("/__unit/capabilities").json()["capabilities"]
        order_and_pay = next(row for row in rows if row["name"] == "order_and_pay")
        assert order_and_pay["enabled"] is False
        assert ROUTE in order_and_pay["routes"]
        res = started.post(PATH, ORDER)
        assert res.status == 501, res.text
        assert res.json()["unit_error"]["kind"] == "capability_disabled"


# --- the walk --------------------------------------------------------------------------------------------------------

SECOND_LOCATION = 100000000102


def _overlay() -> dict[str, Any]:
    doc = copy.deepcopy(json.loads(c.DEFAULT_SEED_PATH.read_text(encoding="utf-8")))
    doc["businesses"][0]["businessLocations"].append({"id": SECOND_LOCATION, "name": "Unit K Bistro - Second Street"})
    mains = doc["menus"][0]["menuEntryGroups"][0]["menuEntry"]
    mains.append({"@type": "menuItem", "productName": "Unit Note", "productPrice": 0.0})
    mains.append(
        {
            "@type": "group",
            "id": "100000000302",
            "name": "Sides",
            "menuEntry": [{"@type": "menuItem", "productName": "Unit Fries", "productPrice": 3.0, "sku": "UNITK-003"}],
        }
    )
    doc["menus"].append(
        {
            "ikentooMenuId": 100000000202,
            "menuName": "Unit Dinner Menu",
            "businessLocationIds": [c.SEED_BUSINESS_LOCATION_ID],
            "menuEntryGroups": [
                {
                    "@type": "group",
                    "id": "100000000303",
                    "name": "Dinner",
                    "menuEntry": [
                        {
                            "@type": "menuItem",
                            "productName": "Unit Burger Late",
                            "productPrice": 99.0,
                            "sku": "UNITK-001",
                        }
                    ],
                }
            ],
        }
    )
    doc["menus"].append(
        {
            "ikentooMenuId": 100000000203,
            "menuName": "Unit Second Street Menu",
            "businessLocationIds": [SECOND_LOCATION],
            "menuEntryGroups": [
                {
                    "@type": "group",
                    "id": "100000000304",
                    "name": "Elsewhere",
                    "menuEntry": [
                        {"@type": "menuItem", "productName": "Unit Far Away", "productPrice": 1.0, "sku": "UNITK-900"}
                    ],
                }
            ],
        }
    )
    return doc


def test_menu_item_walks_groups_skips_entries_without_a_sku_and_keeps_the_first_menu(tmp_path: Path) -> None:
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(_overlay()), encoding="utf-8")
    for started in harness(env={**VIRTUAL, "VENDORFAKE_SEED": str(path)}):
        ctx = started.unit.context
        location = c.SEED_BUSINESS_LOCATION_ID
        deep = menu_item(ctx, location, "UNITK-003")
        assert deep is not None and deep["productName"] == "Unit Fries"
        assert menu_item(ctx, location, "UNITK-900") is None
        assert menu_item(ctx, SECOND_LOCATION, "UNITK-900") is not None
        first = menu_item(ctx, location, "UNITK-001")
        assert first is not None and first["productPrice"] == 12.5
        assert menu_item(ctx, location, c.SEED_UNKNOWN_SKU) is None
