"""Fixtures shared by the Lightspeed K-Series suite."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.lightspeed_k.harness import Harness, harness
from vendorfake.core.time.clock import Clock

CLOCK_START = "2026-10-29T12:00:00.000Z"
VIRTUAL = {"VENDORFAKE_CLOCK": "virtual", "VENDORFAKE_CLOCK_START": CLOCK_START}


def fake_ctx(
    *,
    profile: str = "test",
    vendor_config: dict[str, Any] | None = None,
    chaos_seed: int = 1,
    vendor_name: str = "lightspeed-k",
    clock: Clock | None = None,
    error_sidecar_mode: str = "both",
) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(
            profile=profile,
            vendor_config=vendor_config or {},
            chaos=SimpleNamespace(seed=chaos_seed),
            errors=SimpleNamespace(sidecar=error_sidecar_mode),
        ),
        vendor=SimpleNamespace(name=vendor_name),
        clock=clock if clock is not None else Clock("virtual", CLOCK_START),
    )


@pytest.fixture
def h() -> Iterator[Harness]:
    yield from harness()


@pytest.fixture
def virtual() -> Iterator[Harness]:
    yield from harness(env=VIRTUAL)


@pytest.fixture
def profile_harness() -> Any:
    def build(profile: str, **kwargs: Any) -> Iterator[Harness]:
        return harness(profile, **kwargs)

    return build


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: Any) -> None:
    from tests.unit.lightspeed_k.harness import FIDELITY_UNAVAILABLE_REASON, LEDGER

    if FIDELITY_UNAVAILABLE_REASON is not None:
        terminalreporter.write_line("lightspeed-k fidelity: SKIPPED -- no extract in the cache; run fidelity fetch")
    else:
        terminalreporter.write_line(f"lightspeed-k {LEDGER.summary()}")
