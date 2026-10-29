"""``target_for`` resolves a vendor name through the registry, never by spelling a module from the name.

konyklabs/roadmap#179: a hyphenated identifier is the first whose name differs from its module, so a
``vendorfake.<name>.fidelity`` guess silently drops the fidelity leg and makes ``serve --validate`` refuse.
"""

from __future__ import annotations

import pytest

from vendorfake import registry
from vendorfake.testing.fidelity import target_for


def test_a_hyphenated_name_finds_the_leg_of_the_module_the_registry_names(monkeypatch: pytest.MonkeyPatch) -> None:
    targets = registry._targets()
    monkeypatch.setattr(registry, "_targets", lambda: {**targets, "hyphen-name": "vendorfake.square:VENDOR"})
    target = target_for("hyphen-name")
    assert target is not None
    assert target.name == "hyphen-name"
    assert target.anchor == "vendorfake.square.fidelity"


def test_a_name_the_registry_does_not_map_has_no_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    targets = {name: value for name, value in registry._targets().items() if name != "square"}
    monkeypatch.setattr(registry, "_targets", lambda: targets)
    assert target_for("square") is None
    assert target_for("no-such-vendor") is None


def test_a_mapped_module_without_a_declaration_has_no_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    targets = registry._targets()
    monkeypatch.setattr(registry, "_targets", lambda: {**targets, "hyphen-name": "vendorfake.clover:VENDOR"})
    assert target_for("hyphen-name") is None


def test_a_mapped_module_that_is_not_installed_has_no_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    targets = registry._targets()
    monkeypatch.setattr(registry, "_targets", lambda: {**targets, "hyphen-name": "not_installed_vendor:VENDOR"})
    assert target_for("hyphen-name") is None


def test_every_shipped_leg_still_resolves() -> None:
    for name in ("square", "toast", "lightspeed"):
        target = target_for(name)
        assert target is not None
        assert target.anchor == f"vendorfake.{name}.fidelity"
