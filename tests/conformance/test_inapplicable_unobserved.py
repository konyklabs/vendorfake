"""konyklabs/roadmap#179: a run-bound contract the target declares inapplicable is not "never observed"
under --strict -- the skip is a reason about the vendor, not a run that never looked."""

from __future__ import annotations

import pytest

from tests.conformance.harness import lightspeed_k_target
from vendorfake.conformance import ConformanceTarget, run_conformance


def _without_c21(target: ConformanceTarget) -> ConformanceTarget:
    inapplicable = {key: value for key, value in target.inapplicable.items() if key != "C21"}
    return ConformanceTarget(
        name=target.name,
        open_client=target.open_client,
        open_with_seed_overlay=target.open_with_seed_overlay,
        profiles=target.profiles,
        transports=target.transports,
        out_of_process=target.out_of_process,
        expected_skips={**dict(target.expected_skips or {}), "C21": tuple(target.profiles)},
        inapplicable=inapplicable,
    )


@pytest.mark.conformance
def test_an_inapplicable_run_bound_contract_is_not_unobserved() -> None:
    target = lightspeed_k_target(profiles=("full",), transports=("inprocess",))
    assert "C21" in target.inapplicable
    report = run_conformance(target, check_ids=("C21",), strict=True)
    assert report.unobserved == {}


@pytest.mark.conformance
def test_the_same_skips_without_the_declaration_are_still_unobserved() -> None:
    target = _without_c21(lightspeed_k_target(profiles=("full",), transports=("inprocess",)))
    report = run_conformance(target, check_ids=("C21",), strict=True)
    assert set(report.unobserved) == {"C21"}
