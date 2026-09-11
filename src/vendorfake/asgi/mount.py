"""Several units in one process, one per path prefix: ``serve --vendor clover,square``. All ``JUDGMENT`` --
no vendor documents how a fake of it should share a port with a fake of another one. The single-vendor path
is untouched: ``create_app(unit)`` still goes straight onto the socket, and this is reached only when more
than one vendor was named.

Invariant: a plain ASGI callable, not a router. A ``Mount`` would be a second place where a request could be
matched, rejected or rewritten by something other than the unit, which is what ``app``'s catch-all exists to
prevent. This picks the first path segment, and if it names a mount hands the sub-application a *copy* of the
scope with that segment moved from ``path`` to ``root_path`` -- ``raw_path`` stripped alongside ``path``,
since ``adapt.request_path`` reads the raw one, and ``x-forwarded-prefix`` appended so the unit can report a
base URL a caller can reach.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, MutableMapping
from typing import Any

from vendorfake.core.kernel.reply import JSON_CONTENT_TYPE
from vendorfake.core.util.json import dump_json

__all__ = ["FORWARDED_PREFIX_HEADER", "MOUNTS_HEADER", "ASGIApp", "MountedApp", "create_mounted_app"]

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]
"""Spelled out, not imported: ``FastAPI`` satisfies it structurally and this module needs nothing else."""

FORWARDED_PREFIX_HEADER = b"x-forwarded-prefix"
"""Told to the mounted unit, so it can report a URL the caller can reach."""

MOUNTS_HEADER = b"vendorfake-mounts"
"""On the root 404: the mount names, comma-joined -- a header too, because a client throws a 404 body away."""

#: Served alongside ``/``: the image's ``HEALTHCHECK`` probes ``/__unit/health``, and a mounted process must be
#: healthy on the same path a single-vendor one is.
_INDEX_PATHS = frozenset({"/", "/__unit/info", "/__unit/health"})


class MountedApp:
    """One application per mount name, on the first path segment. Public only so a test can name it."""

    def __init__(self, apps: Mapping[str, ASGIApp], *, index: bool = True) -> None:
        self._apps: dict[str, ASGIApp] = dict(apps)
        self._serves_index = index
        self._names: tuple[str, ...] = tuple(self._apps)
        self._mounts: dict[str, str] = {name: f"/{name}" for name in self._names}
        self._index = dump_json({"status": "ok", "vendors": list(self._names), "mounts": self._mounts})
        self._mounts_header = ",".join(self._names).encode("latin-1")
        self._mount_list = ", ".join(self._mounts[name] for name in self._names)

    @property
    def names(self) -> tuple[str, ...]:
        """The mount names, in mount order."""
        return self._names

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope.get("type")
        if kind == "lifespan":
            await self._lifespan(receive, send)
            return
        segment = _first_segment(str(scope.get("path", "/")))
        app = self._apps.get(segment)
        if app is not None:
            await app(self._delegated(scope, segment), receive, send)
            return
        if kind == "websocket":
            # A websocket scope cannot carry the 404 below; closing before accepting is ASGI for "nothing here".
            await send({"type": "websocket.close", "code": 1000})
            return
        await self._unmatched(scope, send)

    async def _unmatched(self, scope: Scope, send: Send) -> None:
        """The index, or a 404 naming every mount, for a request that asked for a vendor nobody mounted."""
        method = str(scope.get("method", "GET")).upper()
        path = str(scope.get("path", "/"))
        if self._serves_index and method in {"GET", "HEAD"} and path in _INDEX_PATHS:
            await _send_json(send, 200, self._index, method=method)
            return
        body = dump_json(
            {
                "message": f"{method} {path} matches no mounted vendor; the mounts are {self._mount_list}",
                "mounts": self._mounts,
            }
        )
        await _send_json(send, 404, body, method=method, extra=[(MOUNTS_HEADER, self._mounts_header)])

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        """Completed here, not delegated: every unit starts before the process listens."""
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    def _delegated(self, scope: Scope, name: str) -> Scope:
        """A copy of ``scope`` as the mounted application should see it."""
        prefix = self._mounts[name]
        delegated: Scope = dict(scope)
        delegated["path"] = _without_prefix(str(scope.get("path", "/")), prefix)
        raw = scope.get("raw_path")
        if isinstance(raw, bytes):
            encoded = prefix.encode("latin-1")
            if raw.startswith(encoded):
                delegated["raw_path"] = _without_prefix_bytes(raw, encoded)
            else:  # pragma: no cover - only a percent-encoded mount name gets here
                delegated.pop("raw_path", None)
        delegated["root_path"] = f"{scope.get('root_path', '')}{prefix}"
        delegated["headers"] = _forwarded(scope.get("headers", ()), prefix)
        return delegated


def create_mounted_app(apps: Mapping[str, ASGIApp], *, index: bool = True) -> ASGIApp:
    """Mount each application under ``/<name>/``, in order; ``index=False`` for a vendor listener, which leaves the
    index to the control listener."""
    return MountedApp(apps, index=index)


def _first_segment(path: str) -> str:
    """``/clover/x`` -> ``clover``. Split, not ``startswith``: ``clover`` must not swallow ``/cloverx/...``."""
    rooted = path[1:] if path.startswith("/") else path
    return rooted.split("/", 1)[0]


def _without_prefix(path: str, prefix: str) -> str:
    """``/clover`` -> ``/``, ``/clover/x`` -> ``/x``. Always rooted."""
    remainder = path[len(prefix) :]
    return remainder if remainder.startswith("/") else f"/{remainder}"


def _without_prefix_bytes(raw: bytes, prefix: bytes) -> bytes:
    """The same on ``raw_path``, query and all: ``/clover?a=1`` becomes ``/?a=1``, never ``?a=1``."""
    remainder = raw[len(prefix) :]
    return remainder if remainder.startswith(b"/") else b"/" + remainder


def _forwarded(headers: Iterable[Any], prefix: str) -> list[tuple[bytes, bytes]]:
    """The caller's headers, with this prefix recorded. An existing ``x-forwarded-prefix`` is extended, not
    replaced: ``/edge`` plus ``clover`` is ``/edge/clover``, what a client outside both calls."""
    encoded = prefix.encode("latin-1")
    out: list[tuple[bytes, bytes]] = []
    found = False
    for name, value in headers:
        if not found and bytes(name).lower() == FORWARDED_PREFIX_HEADER:
            # Extend the FIRST comma-separated entry, the one the manifest reads.
            first, sep, rest = bytes(value).partition(b",")
            out.append((bytes(name), first.rstrip(b"/") + encoded + sep + rest))
            found = True
        else:
            out.append((bytes(name), bytes(value)))
    if not found:
        out.append((FORWARDED_PREFIX_HEADER, encoded))
    return out


async def _send_json(
    send: Send,
    status: int,
    body: bytes,
    *,
    method: str,
    extra: list[tuple[bytes, bytes]] | None = None,
) -> None:
    """One JSON response; ``HEAD`` gets a ``GET``'s headers and length with no body to discard."""
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", JSON_CONTENT_TYPE.encode("latin-1")),
        (b"content-length", str(len(body)).encode("latin-1")),
    ]
    headers.extend(extra or [])
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": b"" if method == "HEAD" else body})
