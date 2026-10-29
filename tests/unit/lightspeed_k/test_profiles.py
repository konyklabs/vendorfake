"""The six shipped profiles, and what each name promises (the vendor-side half of C35)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from tests.unit.lightspeed_k.harness import BUSINESSES, Harness
from vendorfake.lightspeed_k.capabilities import LIGHTSPEED_K_CAPABILITIES
from vendorfake.lightspeed_k.vendor import LightspeedKVendor
from vendorfake.registry import available_profiles

REQUIRED = ("full", "oauth-only", "orders-only", "no-chaos", "no-faults", "chaos-demo")


def _profile(name: str) -> dict[str, Any]:
    path = LightspeedKVendor().profile_dir / f"{name}.json"
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _capabilities(name: str) -> set[str]:
    return {str(item) for item in _profile(name)["capabilities"]}


def test_all_six_shared_names_ship() -> None:
    assert set(REQUIRED) <= {row.name for row in available_profiles("lightspeed-k")}


@pytest.mark.parametrize("name", REQUIRED)
def test_every_profile_names_only_declared_capabilities(name: str) -> None:
    assert _capabilities(name) <= {row.name for row in LIGHTSPEED_K_CAPABILITIES}


@pytest.mark.parametrize("name", REQUIRED)
def test_every_profile_document_agrees_with_its_filename_and_seed(name: str) -> None:
    document = _profile(name)
    assert document["name"] == name
    assert document["seed"] == "seed/default.seed.json"


def test_oauth_only_is_auth_and_chaos() -> None:
    assert _capabilities("oauth-only") == {"auth", "chaos"}


def test_orders_only_has_no_token_endpoint_and_the_seeded_bearer_reads(
    profile_harness: Callable[..., Iterator[Harness]],
) -> None:
    assert _capabilities("orders-only") == {"order_and_pay", "chaos"}
    for h in profile_harness("orders-only"):
        assert h.get(BUSINESSES).status == 200


def test_no_chaos_equals_full_and_no_faults_drops_chaos() -> None:
    assert _capabilities("no-chaos") == _capabilities("full") == {"auth", "order_and_pay", "chaos"}
    assert _capabilities("no-faults") == {"auth", "order_and_pay"}


def test_chaos_demo_runs_on_a_virtual_clock_with_two_rules() -> None:
    document = _profile("chaos-demo")
    assert document["clock"]["mode"] == "virtual"
    assert [rule["fault"] for rule in document["chaos"]["rules"]] == ["token_expiry", "unavailable"]
