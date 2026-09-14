"""Two vendors, one process, one port, over a real socket.

Nothing in this module imports ``vendorfake``. The server is started the way an
operator starts it -- ``python -m vendorfake serve --vendor clover,square
--port 0`` -- and every assertion is made with ``httpx`` plus the standard
library, which is what makes this evidence rather than a second reading of the
mount's own helpers: an in-process test drives the mount with a transport that
never touches uvicorn's h11 parser, and the whole claim here is that a
prefixed path survives one.

Three things only this can show:

* one child process answers for both vendors, each under its own prefix, with
  its own control plane;
* the root ``/__unit/info`` -- answered by the same index as ``/__unit/health``, the
  path the image's ``HEALTHCHECK`` probes -- is 200 and lists them, so an orchestrator's liveness check means the same
  thing for a mounted process as for a single-vendor one;
* a real vendor flow (Clover's single-use refresh rotation) works through a
  prefix, body and all.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]

STARTUP_TIMEOUT_S = 60.0
LISTENING = re.compile(r"listening on http://([0-9.]+):(\d+) \(vendors=([^;]+); mounts=([^)]+)\)")

#: Seeded in Clover's default scenario; written out here rather than imported,
#: because this module shares nothing with the code under test but HTTP.
CLOVER_CLIENT_ID = "UNITCLOVERAPP"
CLOVER_REFRESH_TOKEN = "unit-seeded-clover-refresh-token-full-permissions"


class Mounted:
    """The child process, its port, and what its announce line claimed."""

    def __init__(self, process: subprocess.Popen[str], port: int, vendors: str, mounts: str) -> None:
        self.process = process
        self.port = port
        self.vendors = vendors
        self.mounts = mounts
        self.base_url = f"http://127.0.0.1:{port}"


def _wait_for_announcement(process: subprocess.Popen[str]) -> tuple[int, str, str]:
    """The one flushed line the CLI prints before uvicorn takes the socket.

    A deadline rather than a blocking read: if the child dies during startup,
    ``readline`` would block until the pipe closed and the failure would be a
    timeout with no output. This reports the child's own stderr instead.
    """
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    assert process.stdout is not None
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if line:
            found = LISTENING.search(line)
            if found is not None:
                return int(found.group(2)), found.group(3), found.group(4)
        elif process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(f"the server exited before it bound (code {process.returncode}):\n{stderr}")
        else:
            time.sleep(0.01)
    raise AssertionError("the server did not announce a port within the startup timeout")


@pytest.fixture(scope="module")
def server() -> Iterator[Mounted]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "vendorfake",
            "serve",
            "--vendor",
            "clover,square",
            "--profile",
            "oauth-only",
            "--port",
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
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    try:
        port, vendors, mounts = _wait_for_announcement(process)
        yield Mounted(process, port, vendors, mounts)
    finally:
        # SIGINT rather than SIGKILL: uvicorn runs its graceful-shutdown path
        # for it, so this exercises the shutdown a mounted process does too.
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover - only on a hang
            process.kill()
            process.wait(timeout=5)


@pytest.fixture(scope="module")
def client(server: Mounted) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=server.base_url, timeout=30.0) as opened:
        yield opened


def test_the_announce_line_names_both_mounts(server: Mounted) -> None:
    """The line is the only thing a parent process gets before the socket is
    live, so it has to carry both the port and where each vendor is."""
    assert server.port > 0
    assert server.vendors == "clover,square"
    assert server.mounts == "/clover,/square"


def test_the_root_info_is_the_healthcheck_for_every_mount(client: httpx.Client) -> None:
    """``/__unit/info`` is the index ``/__unit/health``, the image's ``HEALTHCHECK``
    probe, also answers. A mounted process answers it 200 with the mount table, so the same probe means the
    same thing whether one vendor is served or four."""
    response = client.get("/__unit/info")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "vendors": ["clover", "square"],
        "mounts": {"clover": "/clover", "square": "/square"},
    }


@pytest.mark.parametrize("vendor", ["clover", "square"])
def test_each_mount_has_its_own_control_plane(client: httpx.Client, vendor: str) -> None:
    response = client.get(f"/{vendor}/__unit/info")
    assert response.status_code == 200
    assert response.json()["vendor"]["name"] == vendor


def test_a_vendor_flow_works_through_its_prefix(client: httpx.Client) -> None:
    """Clover's refresh rotation, form body and all, under ``/clover``.

    A control-plane 200 would only show that a path reached the unit; this
    shows that a request with a body reached a vendor route through the mount
    and came back with what that route mints.
    """
    response = client.post(
        "/clover/oauth/v2/refresh",
        json={"client_id": CLOVER_CLIENT_ID, "refresh_token": CLOVER_REFRESH_TOKEN},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"] != CLOVER_REFRESH_TOKEN


def test_an_unmounted_prefix_is_a_404_that_names_the_mounts(client: httpx.Client) -> None:
    """The header as well as the body, because a client library throws the
    body of a 404 away and "which vendors does this process serve" is the
    question a misrouted call is really asking."""
    response = client.get("/nope/x")
    assert response.status_code == 404
    assert response.headers["vendorfake-mounts"] == "clover,square"
    assert response.json()["mounts"] == {"clover": "/clover", "square": "/square"}
