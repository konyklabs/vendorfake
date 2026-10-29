"""The three Order and Pay reads under the orders-api scope (source.json, the tutorial)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit.lightspeed_k.harness import (
    BUSINESSES,
    LEDGER,
    LOCATION,
    MENUS,
    SURFACE,
    Harness,
    bearer,
    menu_path,
)
from vendorfake.lightspeed_k.seed.constants import (
    SEED_ACCESS_TOKEN,
    SEED_BUSINESS_ID,
    SEED_BUSINESS_LOCATION_ID,
    SEED_BUSINESS_LOCATION_NAME,
    SEED_BUSINESS_NAME,
    SEED_MENU_ID,
    SEED_MENU_NAME,
)

MENU = menu_path(SEED_MENU_ID)


def _entries(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for group in groups:
        found.append(group)
        found.extend(_entries(group.get("menuEntry", [])))
    return found


def _has(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_has(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_has(child, key) for child in value)
    return False


def _nulls(value: Any, path: str = "") -> list[str]:
    if value is None:
        return [path or "/"]
    if isinstance(value, dict):
        return [hit for key, child in value.items() for hit in _nulls(child, f"{path}/{key}")]
    if isinstance(value, list):
        return [hit for index, child in enumerate(value) for hit in _nulls(child, f"{path}/{index}")]
    return []


def test_businesses_answers_the_exact_projection_with_integer_ids(h: Harness) -> None:
    res = h.get(BUSINESSES)
    assert res.status == 200
    assert res.json() == [
        {
            "name": SEED_BUSINESS_NAME,
            "id": SEED_BUSINESS_ID,
            "businessLocations": [{"id": SEED_BUSINESS_LOCATION_ID, "name": SEED_BUSINESS_LOCATION_NAME}],
        }
    ]


def test_the_menu_list_filters_by_location(h: Harness) -> None:
    res = h.menus()
    assert res.status == 200
    assert res.json() == [{"menuName": SEED_MENU_NAME, "ikentooMenuId": SEED_MENU_ID}]


@pytest.mark.parametrize(
    "query,status,kind",
    [
        ({}, 400, "missing_field"),
        ({"businessLocationId": "abc"}, 400, "invalid_value"),
        ({"businessLocationId": "1.5"}, 400, "invalid_value"),
        ({"businessLocationId": "999"}, 404, "not_found"),
    ],
)
def test_menu_list_refusals(h: Harness, query: dict[str, str], status: int, kind: str) -> None:
    res = h.get(MENUS, query=query)
    assert res.status == status
    assert res.json()["unit_error"]["kind"] == kind


def test_menu_v2_answers_the_seeded_document_with_every_entry_typed(h: Harness) -> None:
    res = h.get(MENU, query={"businessLocationId": LOCATION})
    assert res.status == 200
    body = res.json()
    assert body["ikentooMenuId"] == SEED_MENU_ID and body["menuName"] == SEED_MENU_NAME
    assert body["richDataMissing"] is False
    entries = _entries(body["menuEntryGroups"])
    assert len(entries) == 3 and all("@type" in entry for entry in entries)


def test_unknown_menu_and_foreign_location_are_404(h: Harness) -> None:
    unknown = h.get(menu_path(1), query={"businessLocationId": LOCATION})
    assert unknown.status == 404 and unknown.json()["unit_error"]["reason"] == "unknown_menu"
    nowhere = h.get(MENU, query={"businessLocationId": "999"})
    assert nowhere.status == 404 and nowhere.json()["unit_error"]["reason"] == "unknown_business_location"


def test_rich_content_is_stripped_by_default_and_kept_on_request(h: Harness) -> None:
    default = h.get(MENU, query={"businessLocationId": LOCATION}).json()
    explicit = h.get(MENU, query={"businessLocationId": LOCATION, "richContent": "false"}).json()
    rich = h.get(MENU, query={"businessLocationId": LOCATION, "richContent": "TRUE"}).json()
    assert not _has(default, "itemRichData") and default == explicit
    assert _has(rich, "itemRichData")
    bad = h.get(MENU, query={"businessLocationId": LOCATION, "richContent": "yes"})
    assert bad.status == 400 and bad.json()["unit_error"]["kind"] == "invalid_value"


def test_an_account_profile_changes_nothing(h: Harness) -> None:
    plain = h.get(MENU, query={"businessLocationId": LOCATION}).json()
    takeaway = h.get(MENU, query={"businessLocationId": LOCATION, "accountProfile": "TAKEAWAY"}).json()
    assert plain == takeaway


def test_a_non_integer_menu_id_is_400(h: Harness) -> None:
    res = h.get(menu_path("conformance-probe"), query={"businessLocationId": LOCATION})
    assert res.status == 400 and res.json()["unit_error"]["kind"] == "invalid_value"


@pytest.mark.parametrize("path", [BUSINESSES, MENUS, MENU])
def test_scope_and_bearer_refusals(h: Harness, path: str) -> None:
    query = {"businessLocationId": LOCATION}
    forbidden = h.get(path, query=query, headers=h.read_auth)
    assert forbidden.status == 403 and forbidden.json()["unit_error"]["kind"] == "forbidden_scope"
    missing = h.get(path, query=query, headers={})
    assert missing.status == 401
    assert set(missing.json()) - {"unit_error"} == {"status", "error", "message"}


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER"])
def test_the_scheme_is_case_insensitive(h: Harness, scheme: str) -> None:
    assert h.get(BUSINESSES, headers={"authorization": f"{scheme} {SEED_ACCESS_TOKEN}"}).status == 200


def test_an_unknown_bearer_is_401(h: Harness) -> None:
    res = h.get(BUSINESSES, headers=bearer("not-a-token"))
    assert res.status == 401 and res.json()["unit_error"]["reason"] == "unknown_token"


def test_the_three_validated_routes_answer_no_null_anywhere(h: Harness) -> None:
    """Under the 3.1 dialect ``nullable`` is not a keyword, so a null would fail validation."""
    bodies = [
        h.get(BUSINESSES).json(),
        h.menus().json(),
        h.get(MENU, query={"businessLocationId": LOCATION}).json(),
        h.get(MENU, query={"businessLocationId": LOCATION, "richContent": "true"}).json(),
    ]
    assert [_nulls(body) for body in bodies] == [[], [], [], []]


def test_an_unavailable_rule_answers_envelope_b_and_the_deviation_absorbs_it(h: Harness) -> None:
    rule = {
        "id": "down-once",
        "scope": "request",
        "fault": "unavailable",
        "match": {"route": f"GET {BUSINESSES}"},
        "when": {"times": 1},
    }
    assert h.api.post("/__unit/chaos/rules", rule).status == 200
    before = LEDGER.row(f"GET {BUSINESSES}").deviated
    res = h.get(BUSINESSES)
    assert res.status == 503
    body = res.json()
    assert (body["status"], body["apiSubExceptions"]) == ("503", [])
    if SURFACE is not None:
        assert LEDGER.row(f"GET {BUSINESSES}").deviated == before + 1
