"""Several units in one process, one per path prefix.

Two real units are mounted -- a Clover one and a Square one, each through the
same ``create_app`` a single-vendor process uses -- and every assertion here is
made over HTTP through ``httpx.ASGITransport``, because what is under test is
what a caller sees, not what the mount computed.

The scope rewriting itself (``root_path``, ``raw_path``, the forwarded prefix)
is asserted separately, against a recording application, since no unit route
reports the ASGI scope it was called with and a fact nothing can observe is not
worth having.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import anyio
import httpx
import pytest

from tests.unit.asgi.test_adapt import call
from vendorfake.asgi import create_app, create_mounted_app
from vendorfake.asgi.mount import MOUNTS_HEADER, MountedApp
from vendorfake.registry import create_unit

#: Per-request or per-response by construction; everything else the unit set
#: has to survive the mount unchanged.
PER_REQUEST_HEADERS = frozenset({"x-unit-request-id"})


@pytest.fixture
def clover_app() -> Iterator[Any]:
    built = create_unit(vendor="clover", profile="oauth-only")
    try:
        yield create_app(built)
    finally:
        built.stop()


@pytest.fixture
def square_app() -> Iterator[Any]:
    built = create_unit(vendor="square", profile="oauth-only")
    try:
        yield create_app(built)
    finally:
        built.stop()


@pytest.fixture
def mounted(clover_app: Any, square_app: Any) -> Any:
    """Clover first, Square second -- the order the names were given in, which
    the index document and the ``vendorfake-mounts`` header both report."""
    return create_mounted_app({"clover": clover_app, "square": square_app})


# ---------------------------------------------------------------------------
# Each mount is the whole unit, under its own prefix.
# ---------------------------------------------------------------------------


def test_each_mount_answers_for_its_own_vendor(mounted: Any) -> None:
    """The point of the whole module: two vendors, one process, one port."""
    assert call(mounted, "GET", "/clover/__unit/info").json()["vendor"]["name"] == "clover"
    assert call(mounted, "GET", "/square/__unit/info").json()["vendor"]["name"] == "square"


def test_each_mount_reports_its_own_profile_when_pinned_independently() -> None:
    """konyklabs/roadmap#134: a stack wanting Clover on ``full`` and Square on
    ``oauth-only`` reaches it with one shared ``--profile``/env and a
    ``VENDORFAKE_PROFILE_SQUARE`` pin, not two different ``profile=``
    arguments -- the mount must carry each unit's own resolved profile through
    untouched, the same as it does for the vendor name."""
    clover = create_unit(vendor="clover", profile="full")
    square = create_unit(vendor="square", env={"VENDORFAKE_PROFILE": "full", "VENDORFAKE_PROFILE_SQUARE": "oauth-only"})
    try:
        two_profiles = create_mounted_app({"clover": create_app(clover), "square": create_app(square)})
        assert call(two_profiles, "GET", "/clover/__unit/info").json()["profile"] == "full"
        assert call(two_profiles, "GET", "/square/__unit/info").json()["profile"] == "oauth-only"
    finally:
        clover.stop()
        square.stop()


def test_a_mount_matches_whole_segments_only(mounted: Any) -> None:
    """``/cloverx`` is not ``/clover`` with a suffix, it is a different vendor
    nobody mounted -- and answering it out of the Clover unit would be the
    quietest possible way to serve the wrong fake."""
    response = call(mounted, "GET", "/cloverx/__unit/info")
    assert response.status_code == 404
    assert response.headers["vendorfake-mounts"] == "clover,square"
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert body["mounts"] == {"clover": "/clover", "square": "/square"}
    assert body["message"] == "GET /cloverx/__unit/info matches no mounted vendor; the mounts are /clover, /square"


@pytest.mark.parametrize("path", ["/", "/__unit/info", "/__unit/health"])
def test_the_root_index_lists_every_mount(mounted: Any, path: str) -> None:
    """``/__unit/info`` is what the image's ``HEALTHCHECK`` probes, so a
    multi-vendor process must answer it 200 on the same path a single-vendor
    one does -- and it is 200 exactly when every unit was constructed, which
    has already happened by the time anything is listening."""
    response = call(mounted, "GET", path)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "status": "ok",
        "vendors": ["clover", "square"],
        "mounts": {"clover": "/clover", "square": "/square"},
    }


def test_head_is_answered_with_the_headers_and_no_body(mounted: Any) -> None:
    """A ``HEAD`` on the index reports the length a ``GET`` would carry.

    Sending the body anyway would be a framing error for the server to clean
    up after, and omitting the length would make the response useless for the
    one thing ``HEAD`` is for.
    """
    response = call(mounted, "HEAD", "/__unit/info")
    assert response.status_code == 200
    assert response.content == b""
    assert int(response.headers["content-length"]) == len(call(mounted, "GET", "/__unit/info").content)


def test_a_mount_without_a_trailing_slash_is_the_units_root(mounted: Any, clover_app: Any) -> None:
    """``/clover`` means ``/`` on the Clover unit, not "no path at all"."""
    through_mount = call(mounted, "GET", "/clover")
    direct = call(clover_app, "GET", "/")
    assert through_mount.status_code == direct.status_code == 404
    assert through_mount.json() == direct.json()


def test_percent_escapes_survive_the_mount(mounted: Any) -> None:
    """``%2F`` inside a segment must still not become a separator.

    The mount strips its prefix from ``raw_path`` as well as from ``path``,
    because :func:`vendorfake.asgi.adapt.request_path` reads the raw one; a
    mount that rewrote only the decoded path would hand the unit
    ``/v3/nope/a/b`` and undo the guarantee the adapter exists to keep.
    """
    response = call(mounted, "GET", "/clover/v3/nope/a%2Fb")
    assert response.status_code == 404
    assert "GET /v3/nope/a%2Fb is not a route" in response.json()["message"]
    assert json.loads(response.headers["vendorfake-error-info"])["path"] == "/v3/nope/a%2Fb"


def test_every_unit_response_header_survives_the_mount(mounted: Any, clover_app: Any) -> None:
    """The mount adds nothing to a delegated response and removes nothing.

    Byte-for-byte agreement between bindings is a conformance contract; a
    wrapper that quietly appended a header would break it for every consumer
    comparing a mounted process against a single-vendor one.
    """
    through_mount = call(mounted, "GET", "/clover/v3/nope")
    direct = call(clover_app, "GET", "/v3/nope")
    assert through_mount.status_code == direct.status_code
    assert through_mount.content == direct.content
    assert _comparable(through_mount) == _comparable(direct)


def test_a_mounted_unit_publishes_a_base_url_that_carries_its_prefix(mounted: Any) -> None:
    """``GET /clover/__unit/manifest`` is read by a setup script that then calls
    the vendor surface with what it found. A base URL a mount short would send
    every one of those calls to the root 404."""
    body = call(mounted, "GET", "/clover/__unit/manifest").json()
    assert body["base_url"] == "http://unit.test/clover"


def test_a_callers_forwarded_prefix_comes_before_the_mounts(mounted: Any) -> None:
    """A proxy in front of this process already said where the client is; the
    mount appends to that prefix rather than replacing it, so the published URL
    is the one a client outside both has to call."""
    body = call(mounted, "GET", "/clover/__unit/manifest", headers={"x-forwarded-prefix": "/edge"}).json()
    assert body["base_url"] == "http://unit.test/edge/clover"


def _comparable(response: httpx.Response) -> dict[str, str]:
    return {name: value for name, value in response.headers.items() if name not in PER_REQUEST_HEADERS}


# ---------------------------------------------------------------------------
# The delegated scope, asserted where it can be seen.
# ---------------------------------------------------------------------------


class Recorder:
    """A mounted application that reports the scope it was handed."""

    def __init__(self) -> None:
        self.scopes: list[dict[str, Any]] = []

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.scopes.append(dict(scope))
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    @property
    def last(self) -> dict[str, Any]:
        return self.scopes[-1]

    def header(self, name: bytes) -> list[bytes]:
        return [value for key, value in self.last["headers"] if key.lower() == name]


def test_the_prefix_moves_from_the_path_to_the_root_path() -> None:
    """What a mounted application is told: the path without the prefix, the
    prefix in ``root_path``, and the escapes still in ``raw_path``."""
    recorder = Recorder()
    assert call(create_mounted_app({"clover": recorder}), "GET", "/clover/v3/nope/a%2Fb?x=1").status_code == 204
    assert recorder.last["path"] == "/v3/nope/a/b"
    assert recorder.last["raw_path"].startswith(b"/v3/nope/a%2Fb")
    assert recorder.last["root_path"] == "/clover"


def test_a_mount_at_its_root_is_told_a_rooted_path() -> None:
    """``/clover`` delegates ``/``, not ``""`` -- a unit's router matches paths."""
    recorder = Recorder()
    assert call(create_mounted_app({"clover": recorder}), "GET", "/clover").status_code == 204
    assert recorder.last["path"] == "/"
    assert recorder.last["raw_path"] == b"/"


def test_the_scope_the_caller_passed_is_not_mutated() -> None:
    """The scope belongs to the server; a mutated one would leak the rewritten
    path back to it, and to every other mount on the same connection."""
    recorder = Recorder()
    app = create_mounted_app({"clover": recorder})
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/clover/v3/nope",
        "raw_path": b"/clover/v3/nope",
        "root_path": "",
        "headers": [(b"host", b"unit.test")],
        "query_string": b"",
    }
    original = dict(scope)

    async def run() -> None:
        messages: list[Any] = [{"type": "http.request", "body": b"", "more_body": False}]

        async def receive() -> Any:
            return messages.pop(0)

        async def send(message: Any) -> None:
            return None

        await app(scope, receive, send)

    anyio.run(run)
    assert scope == original
    assert recorder.last["path"] == "/v3/nope"


def test_the_mount_prefix_is_forwarded() -> None:
    """``x-forwarded-prefix`` is how the unit learns it is not at the root."""
    recorder = Recorder()
    assert call(create_mounted_app({"clover": recorder}), "GET", "/clover/v3/nope").status_code == 204
    assert recorder.header(b"x-forwarded-prefix") == [b"/clover"]


def test_a_forwarded_prefix_list_is_extended_on_its_first_entry() -> None:
    """The manifest reads the first comma-separated entry, so that is the one
    the mount extends; a trailing slash on it does not double up."""
    recorder = Recorder()
    response = call(
        create_mounted_app({"clover": recorder}),
        "GET",
        "/clover/v3/nope",
        headers={"x-forwarded-prefix": "/edge/, /older"},
    )
    assert response.status_code == 204
    assert recorder.header(b"x-forwarded-prefix") == [b"/edge/clover, /older"]


def test_a_callers_forwarded_prefix_keeps_its_place() -> None:
    """A proxy in front of this process already said where the client is; the
    mount extends that prefix rather than replacing it, so ``/edge`` plus a
    mount named ``clover`` is the ``/edge/clover`` a client outside both has
    to call."""
    recorder = Recorder()
    response = call(
        create_mounted_app({"clover": recorder}),
        "GET",
        "/clover/v3/nope",
        headers={"x-forwarded-prefix": "/edge"},
    )
    assert response.status_code == 204
    assert recorder.header(b"x-forwarded-prefix") == [b"/edge/clover"]


# ---------------------------------------------------------------------------
# The rest of the protocol.
# ---------------------------------------------------------------------------


def test_a_lifespan_scope_completes_without_delegating() -> None:
    """Nothing below the mount is built by a lifespan event -- every unit was
    started before the process listened -- so the protocol is completed here
    rather than fanned out to N applications with N answers to reconcile."""
    recorder = Recorder()
    app = create_mounted_app({"clover": recorder})
    sent: list[dict[str, Any]] = []

    async def run() -> None:
        incoming: list[dict[str, Any]] = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]

        async def receive() -> Any:
            return incoming.pop(0)

        async def send(message: Any) -> None:
            sent.append(dict(message))

        await app({"type": "lifespan"}, receive, send)

    anyio.run(run)
    assert [message["type"] for message in sent] == ["lifespan.startup.complete", "lifespan.shutdown.complete"]
    assert recorder.scopes == []


def test_create_mounted_app_keeps_the_order_it_was_given(clover_app: Any, square_app: Any) -> None:
    """Mount order is the order the vendors were named, which is what the
    index document and the ``vendorfake-mounts`` header report."""
    app = create_mounted_app({"square": square_app, "clover": clover_app})
    assert isinstance(app, MountedApp)
    assert app.names == ("square", "clover")
    assert call(app, "GET", "/__unit/info").json()["vendors"] == ["square", "clover"]
    assert call(app, "GET", "/nope").headers[MOUNTS_HEADER.decode()] == "square,clover"
