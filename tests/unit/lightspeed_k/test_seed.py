"""The shipped scenario: constants agree with the document, the parser refuses what the wire cannot carry."""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tests.unit.lightspeed_k.conftest import VIRTUAL
from tests.unit.lightspeed_k.harness import BUSINESSES, Harness, bearer, harness
from vendorfake.core.kernel.types import UnitError
from vendorfake.lightspeed_k import create_lightspeed_k_vendor
from vendorfake.lightspeed_k.config import LightspeedKConfig
from vendorfake.lightspeed_k.entities import COL
from vendorfake.lightspeed_k.seed import constants as c
from vendorfake.lightspeed_k.seed.document import parse_seed_document
from vendorfake.testing.seeds import LightspeedKSeed, seed_for


def _document() -> dict[str, Any]:
    return dict(json.loads(c.DEFAULT_SEED_PATH.read_text(encoding="utf-8")))


def _entries(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for group in groups:
        found.append(group)
        found.extend(_entries(group.get("menuEntry", [])))
    return found


def test_every_constant_names_something_the_document_contains() -> None:
    doc = _document()
    business = doc["businesses"][0]
    assert business["id"] == c.SEED_BUSINESS_ID and business["name"] == c.SEED_BUSINESS_NAME
    location = business["businessLocations"][0]
    assert location == {"id": c.SEED_BUSINESS_LOCATION_ID, "name": c.SEED_BUSINESS_LOCATION_NAME}
    menu = doc["menus"][0]
    assert (menu["ikentooMenuId"], menu["menuName"]) == (c.SEED_MENU_ID, c.SEED_MENU_NAME)
    assert menu["menuEntryGroups"][0]["id"] == c.SEED_GROUP_ID
    skus = tuple(entry["sku"] for entry in _entries(menu["menuEntryGroups"]) if "sku" in entry)
    assert skus == c.SEED_ITEM_SKUS
    tokens = {row["access_token"] for row in doc["tokens"]}
    assert tokens == {c.SEED_ACCESS_TOKEN, c.SEED_FINANCIAL_ONLY_ACCESS_TOKEN}
    assert doc["refresh_tokens"][0]["refresh_token"] == c.SEED_REFRESH_TOKEN
    expected = "Basic " + base64.b64encode(f"{c.SEED_CLIENT_ID}:{c.SEED_CLIENT_SECRET}".encode()).decode()
    assert expected == c.SEED_BASIC_AUTH


def test_the_unknown_sku_is_on_no_seeded_menu() -> None:
    skus = {entry.get("sku") for menu in _document()["menus"] for entry in _entries(menu["menuEntryGroups"])}
    assert c.SEED_UNKNOWN_SKU not in skus
    assert c.SEED_EXAMPLE_ENDPOINT_ID


def test_every_menu_entry_carries_its_type() -> None:
    entries = _entries(_document()["menus"][0]["menuEntryGroups"])
    assert entries and all(isinstance(entry.get("@type"), str) for entry in entries)


def test_the_testing_seed_agrees_with_the_constants() -> None:
    seed = seed_for("lightspeed-k", {})
    assert isinstance(seed, LightspeedKSeed)
    assert (seed.client_id, seed.client_secret, seed.redirect_uri) == (
        c.SEED_CLIENT_ID,
        c.SEED_CLIENT_SECRET,
        c.SEED_REDIRECT_URI,
    )
    assert (seed.access_token, seed.refresh_token, seed.financial_only_access_token) == (
        c.SEED_ACCESS_TOKEN,
        c.SEED_REFRESH_TOKEN,
        c.SEED_FINANCIAL_ONLY_ACCESS_TOKEN,
    )
    assert (seed.business_id, seed.business_location_id, seed.menu_id) == (
        c.SEED_BUSINESS_ID,
        c.SEED_BUSINESS_LOCATION_ID,
        c.SEED_MENU_ID,
    )
    assert seed.item_skus == c.SEED_ITEM_SKUS
    assert seed.basic_auth_headers == {"Authorization": c.SEED_BASIC_AUTH}
    assert seed.auth == {"Authorization": f"bearer {c.SEED_ACCESS_TOKEN}"}
    assert seed.read_only_auth == {"Authorization": f"bearer {c.SEED_FINANCIAL_ONLY_ACCESS_TOKEN}"}
    assert seed.token.tenant_id == str(c.SEED_BUSINESS_LOCATION_ID)
    assert seed.credentials.grant == "refresh_token"
    assert seed.token_path == "/oauth/token"


def _refused(doc: dict[str, Any], fragment: str) -> None:
    with pytest.raises(UnitError) as caught:
        parse_seed_document(doc)
    assert fragment in (caught.value.detail or "")


def test_the_parser_refuses_an_untyped_entry() -> None:
    doc = _document()
    del doc["menus"][0]["menuEntryGroups"][0]["menuEntry"][1]["@type"]
    _refused(doc, "@type")


def test_the_parser_refuses_an_unknown_type() -> None:
    doc = _document()
    doc["menus"][0]["menuEntryGroups"][0]["menuEntry"][0]["@type"] = "menuThing"
    _refused(doc, "@type")


def test_the_parser_refuses_an_unknown_collection() -> None:
    doc = _document()
    doc["orders"] = []
    _refused(doc, "orders")


def test_the_parser_refuses_an_unresolved_location() -> None:
    doc = _document()
    doc["menus"][0]["businessLocationIds"] = [999]
    _refused(doc, "businessLocationIds")


def test_the_parser_refuses_an_unknown_access_token_id() -> None:
    doc = _document()
    doc["refresh_tokens"][0]["access_token_id"] = "tok_absent"
    _refused(doc, "access_token_id")


def test_hydrate_loads_the_scenario(h: Harness) -> None:
    store = h.unit.context.store
    sizes = {name: store.collection(name).size for name in (COL.businesses, COL.menus, COL.tokens, COL.refresh_tokens)}
    assert sizes == {"businesses": 1, "menus": 1, "tokens": 2, "refresh_tokens": 1}


@pytest.mark.parametrize(
    "block,fragment",
    [({"client_id": "devp-v2-unit-client"}, "v2_client_id"), ({"redirect_uri": "http://consumer.example/cb"}, "https")],
)
def test_the_vendor_block_refuses_v2_clients_and_plain_http(block: dict[str, str], fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        create_lightspeed_k_vendor(vendor_config=block)
    with pytest.raises(ValueError, match=fragment):
        LightspeedKConfig().merged_with(block)


def test_a_seed_overlay_still_validates_entries() -> None:
    doc = copy.deepcopy(_document())
    assert parse_seed_document(doc).menus[0].ikentooMenuId == c.SEED_MENU_ID


def test_a_seed_token_with_expires_in_s_zero_is_expired_at_start(tmp_path: Path) -> None:
    """``docs/concepts/seed.md``, Token lifetimes: ``0`` is expired the instant the unit starts, absent is the TTL."""
    doc = _document()
    doc["tokens"][0]["expires_in_s"] = 0
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    for started in harness(env={**VIRTUAL, "VENDORFAKE_SEED": str(path)}):
        tokens = started.unit.context.store.collection(COL.tokens)
        now = int(started.unit.context.clock.now())
        assert tokens.get("tok_seed_full")["expires_at_ms"] == now
        assert tokens.get("tok_seed_financial")["expires_at_ms"] == now + 3_599_000
        res = started.get(BUSINESSES, headers=bearer(c.SEED_ACCESS_TOKEN))
        assert res.status == 401
        assert res.json()["unit_error"]["kind"] == "token_expired"
