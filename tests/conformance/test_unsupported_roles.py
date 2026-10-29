"""konyklabs/roadmap#139: a vendor with two unsupported roles passes C34/C35 with
the excusals visible at GET /__unit/info."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.fakes import TOKEN_ONLY_PROFILES, UNSUPPORTED_ROLE_REASON, FakeVendor, unsupported_roles_vendor
from vendorfake.conformance import (
    ConformanceClient,
    ConformanceTarget,
    InProcessConformanceClient,
    Outcome,
    run_conformance,
)
from vendorfake.core.transport.inprocess import in_process
from vendorfake.registry import create_unit


def _target(vendor: FakeVendor, profiles: tuple[str, ...] = tuple(TOKEN_ONLY_PROFILES)) -> ConformanceTarget:
    @contextmanager
    def open_client(profile: str, transport: str) -> Iterator[ConformanceClient]:
        unit = create_unit(vendor=vendor, profile=profile)
        try:
            yield InProcessConformanceClient(in_process(unit))
        finally:
            unit.stop()

    return ConformanceTarget(name="acme", open_client=open_client, profiles=profiles)


def _run(vendor: FakeVendor, profiles: tuple[str, ...] = tuple(TOKEN_ONLY_PROFILES)) -> list:
    return list(run_conformance(_target(vendor, profiles), check_ids=("C34", "C35"), transports=("inprocess",)).results)


def _one(results: list, check_id: str):  # type: ignore[no-untyped-def]
    [result] = [r for r in results if r.check_id == check_id]
    return result


@pytest.mark.conformance
def test_two_unsupported_roles_pass_c34_and_c35_on_every_shipped_profile(tmp_path: Path) -> None:
    results = _run(unsupported_roles_vendor(tmp_path))
    assert len(results) == 10
    assert all(r.outcome is Outcome.PASS for r in results), [(r.case_id, r.detail) for r in results]
    for result in (r for r in results if r.check_id == "C35"):
        assert "excused by declaration" in result.detail, result.detail
        assert "orders-only" in result.detail, result.detail


@pytest.mark.conformance
def test_info_publishes_the_excusals_beside_roles(tmp_path: Path) -> None:
    unit = create_unit(vendor=unsupported_roles_vendor(tmp_path), profile="full")
    try:
        body = in_process(unit).get("/__unit/info").json()
        assert body["vendor"]["roles"] == {"auth": "token", "chaos": "chaos", "orders": None, "webhooks": None}
        assert body["vendor"]["not_supported_roles"] == {
            "orders": UNSUPPORTED_ROLE_REASON,
            "webhooks": UNSUPPORTED_ROLE_REASON,
        }
        assert "webhooks" in body["not_supported"]
    finally:
        unit.stop()


@pytest.mark.conformance
def test_a_null_role_with_no_reason_fails_c34_by_name_and_never_as_None(tmp_path: Path) -> None:
    vendor = unsupported_roles_vendor(tmp_path)
    vendor.not_supported_roles = {"webhooks": UNSUPPORTED_ROLE_REASON}
    results = _run(vendor, ("full",))
    c34 = _one(results, "C34")
    assert c34.outcome is Outcome.FAIL, c34.detail
    assert "not_supported_roles" in c34.detail
    assert "orders" in c34.detail
    assert "'None'" not in c34.detail
    # Removing the reason un-excuses the name, so orders-only is missing again.
    c35 = _one(results, "C35")
    assert c35.outcome is Outcome.FAIL, c35.detail
    assert "orders-only" in c35.detail


@pytest.mark.conformance
def test_a_stale_excuse_fails_c34(tmp_path: Path) -> None:
    vendor = unsupported_roles_vendor(tmp_path)
    vendor.not_supported_roles = {**vendor.not_supported_roles, "payments": "x"}
    c34 = _one(_run(vendor, ("full",)), "C34")
    assert c34.outcome is Outcome.FAIL, c34.detail
    assert "payments" in c34.detail


@pytest.mark.conformance
def test_shipping_an_excused_profile_name_fails_c35(tmp_path: Path) -> None:
    vendor = unsupported_roles_vendor(tmp_path)
    (vendor.profile_dir / "orders-only.json").write_text(json.dumps({"capabilities": ["token"]}), encoding="utf-8")
    results = _run(vendor, ("orders-only",))
    c35 = _one(results, "C35")
    assert c35.outcome is Outcome.FAIL, c35.detail
    assert "orders-only" in c35.detail
    assert "'orders'" in c35.detail
    c34 = _one(results, "C34")
    assert c34.outcome is Outcome.PASS, c34.detail
