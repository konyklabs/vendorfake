"""The control plane on a listener of its own, with a token, over real sockets (konyklabs/roadmap#134).

Started the way an operator starts it -- ``python -m vendorfake serve ... --port 0 --control-port 0`` with
``VENDORFAKE_CONTROL_TOKEN`` exported -- and asserted with ``httpx`` alone, once for one vendor and once for two
mounted, because what only this shows is two uvicorn servers in one process answering on two ports and stopping
together on one signal.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_S = 60.0
LISTENING = re.compile(r"listening on http://([0-9.]+):(\d+) \([^)]*\) control on http://([0-9.]+):(\d+)")

TOKEN = "integration-control-token-under-test"
TOKEN_HEADER = "vendorfake-control-token"
#: Seeded in Clover's default scenario; written out because this module shares nothing with the code but HTTP.
CLOVER_CLIENT_ID = "UNITCLOVERAPP"
CLOVER_REFRESH_TOKEN = "unit-seeded-clover-refresh-token-full-permissions"


@dataclass(frozen=True)
class Split:
    """The child, both base URLs, and the prefix Clover is reached under."""

    process: subprocess.Popen[str]
    vendor_url: str
    control_url: str
    vendor_port: int
    prefix: str


def _wait_for_announcement(process: subprocess.Popen[str]) -> tuple[int, int]:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    assert process.stdout is not None
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if line:
            found = LISTENING.search(line)
            if found is not None:
                return int(found.group(2)), int(found.group(4))
        elif process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(f"the server exited before it bound (code {process.returncode}):\n{stderr}")
        else:
            time.sleep(0.01)
    raise AssertionError("the server did not announce both ports within the startup timeout")


@pytest.fixture(scope="module", params=["clover", "clover,square"], ids=["one-vendor", "mounted"])
def server(request: pytest.FixtureRequest) -> Iterator[Split]:
    vendors = str(request.param)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "vendorfake",
            "serve",
            "--vendor",
            vendors,
            "--profile",
            "oauth-only",
            "--port",
            "0",
            "--control-port",
            "0",
            "--host",
            "127.0.0.1",
            "--log-level",
            "error",
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1", "VENDORFAKE_CONTROL_TOKEN": TOKEN},
    )
    try:
        vendor_port, control_port = _wait_for_announcement(process)
        yield Split(
            process=process,
            vendor_url=f"http://127.0.0.1:{vendor_port}",
            control_url=f"http://127.0.0.1:{control_port}",
            vendor_port=vendor_port,
            prefix="/clover" if "," in vendors else "",
        )
    finally:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover - only on a hang
            process.kill()
            process.wait(timeout=5)
            pytest.fail("the two-listener process did not stop on SIGINT")


def test_the_vendor_port_serves_the_vendor_surface(server: Split) -> None:
    response = httpx.post(
        f"{server.vendor_url}{server.prefix}/oauth/v2/refresh",
        json={"client_id": CLOVER_CLIENT_ID, "refresh_token": CLOVER_REFRESH_TOKEN},
        timeout=30.0,
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


def test_the_vendor_port_answers_the_control_plane_with_the_vendor_s_404(server: Split) -> None:
    for path in ("/__unit/info", "/__unit/health", "/__unit/openapi.json"):
        response = httpx.get(f"{server.vendor_url}{server.prefix}{path}", headers={TOKEN_HEADER: TOKEN}, timeout=30.0)
        assert response.status_code == 404, path
        assert response.headers["x-unit-error"] == "not_found", path


def test_the_control_port_requires_the_token_except_for_health(server: Split) -> None:
    info = f"{server.control_url}{server.prefix}/__unit/info"
    refused = httpx.get(info, timeout=30.0)
    assert refused.status_code == 401
    assert refused.headers["x-unit-error"] == "unauthorized"
    assert TOKEN not in refused.text
    assert httpx.get(info, headers={TOKEN_HEADER: "not-it"}, timeout=30.0).status_code == 401
    allowed = httpx.get(info, headers={TOKEN_HEADER: TOKEN}, timeout=30.0)
    assert allowed.status_code == 200
    assert allowed.json()["control"] == {"token_required": True}
    assert httpx.get(f"{server.control_url}{server.prefix}/__unit/health", timeout=30.0).status_code == 200
    assert httpx.get(f"{server.control_url}/__unit/health", timeout=30.0).status_code == 200


def test_the_control_port_names_the_vendor_port_for_a_vendor_path(server: Split) -> None:
    response = httpx.post(f"{server.control_url}{server.prefix}/oauth/v2/refresh", json={}, timeout=30.0)
    assert response.status_code == 404
    assert response.json() == {
        "message": f"POST {server.prefix}/oauth/v2/refresh is the vendor surface; it is served on port {server.vendor_port}"
    }
