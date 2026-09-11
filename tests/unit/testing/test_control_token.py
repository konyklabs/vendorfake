"""``VENDORFAKE_CONTROL_TOKEN`` through ``vendorfake.testing``: every driver sends it on control-plane paths and
nowhere else, and a client without it is refused (konyklabs/roadmap#134)."""

from __future__ import annotations

import anyio
import httpx
import pytest

from vendorfake.testing import UnitTransport, async_unit, serve_in_thread, served, unit

TOKEN = "testing-control-token-under-test"
HEADER = "vendorfake-control-token"
ENV = {"VENDORFAKE_CONTROL_TOKEN": TOKEN}


def test_unit_drives_the_control_plane_through_its_driver_with_a_token() -> None:
    with unit("clover", env=ENV) as started:
        assert started.info()["control"] == {"token_required": True}
        assert started.reset()
        assert started.clear_requests() == 0
        assert started.requests() == []


def test_a_raw_client_without_the_header_is_refused_and_never_sees_the_token() -> None:
    with (
        unit("clover", env=ENV) as started,
        httpx.Client(transport=UnitTransport(started.unit), base_url=started.base_url) as raw,
    ):
        for method, path in (("GET", "/__unit/requests"), ("POST", "/__unit/state/reset"), ("GET", "/__unit/nope")):
            refused = raw.request(method, path)
            assert refused.status_code == 401, (method, path)
            assert refused.headers["x-unit-error"] == "unauthorized"
            assert TOKEN not in refused.text
            assert all(TOKEN not in value for value in refused.headers.values())
        assert raw.get("/__unit/health").status_code == 200
        assert raw.get("/__unit/info", headers={HEADER: TOKEN}).status_code == 200


def test_the_driver_sends_the_token_on_control_paths_only_and_an_explicit_header_wins() -> None:
    with unit("clover", env=ENV) as started:
        control = started.client.build_request("GET", "/__unit/info")
        vendor = started.client.build_request("GET", "/v3/merchants/abc")
        for hook in started.client.event_hooks["request"]:
            hook(control)
            hook(vendor)
        assert control.headers[HEADER] == TOKEN
        assert HEADER not in vendor.headers
        assert started.client.get("/__unit/info", headers={HEADER: "not-it"}).status_code == 401


def test_without_a_token_nothing_is_sent_and_nothing_is_required() -> None:
    with unit("clover") as started:
        assert started.info()["control"] == {"token_required": False}
        assert started.client.event_hooks["request"] == []
        with httpx.Client(transport=UnitTransport(started.unit), base_url=started.base_url) as raw:
            assert raw.get("/__unit/info").status_code == 200


def test_async_unit_sends_the_token_from_its_async_client() -> None:
    async def run() -> tuple[int, int]:
        async with async_unit("clover", env=ENV) as started:
            sent = await started.async_client.get("/__unit/info")
            refused = await started.async_client.get("/__unit/info", headers={HEADER: "not-it"})
            return sent.status_code, refused.status_code

    assert anyio.run(run) == (200, 401)


def test_serve_in_thread_sends_the_token_its_unit_resolved() -> None:
    with unit("clover", env=ENV) as started, serve_in_thread(started) as driver:
        assert driver.reset()
        assert driver.info()["control"] == {"token_required": True}
        assert httpx.get(f"{driver.base_url}/__unit/info", timeout=10.0).status_code == 401


def test_served_ignores_an_exported_control_listener_and_refuses_one_in_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``served()`` drives one listener: an exported split would leave its driver on the vendor port."""
    monkeypatch.setenv("VENDORFAKE_CONTROL_PORT", "0")
    monkeypatch.setenv("VENDORFAKE_CONTROL_HOST", "127.0.0.1")
    with served("clover") as child:
        assert child.info()["vendor"]["name"] == "clover"
        assert child.reset()
    for name in ("VENDORFAKE_CONTROL_PORT", "VENDORFAKE_CONTROL_HOST"):
        with pytest.raises(ValueError, match="vendorfake serve --control-port"), served("clover", env={name: "0"}):
            pytest.fail(f"served() started with {name} in env=")
