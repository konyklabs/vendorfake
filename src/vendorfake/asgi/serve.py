"""Running the ASGI application on a real socket. Bound here and handed to
uvicorn, so a caller using ``port=0`` learns the number synchronously; this
module builds no unit, because the boundary policy forbids the registry import.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

try:
    import uvicorn
    from fastapi import FastAPI
except ImportError as exc:
    raise ImportError("vendorfake serve needs the 'serve' extra: pip install 'vendorfake[serve]'") from exc

from vendorfake.asgi.mount import ASGIApp

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "bind", "run_server", "run_split_server", "serve_in_thread"]

_THREAD_STARTUP_TIMEOUT_S = 30.0
_THREAD_SHUTDOWN_TIMEOUT_S = 10.0

DEFAULT_HOST = "127.0.0.1"
"""Loopback: a fake holds seeded credentials, so widening it is explicit."""

DEFAULT_PORT = 8080
"""Matches the profile loader's ``transport.port`` default."""

_BACKLOG = 128


def bind(host: str, port: int) -> socket.socket:
    """Bind and listen; ``SO_REUSEADDR`` so ``TIME_WAIT`` cannot block a restart."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(_BACKLOG)
    return sock


def bound_port(sock: socket.socket) -> int:
    """The port a socket actually got, the only way to learn it for ``port=0``."""
    return int(sock.getsockname()[1])


def run_server(
    app: FastAPI | ASGIApp,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    log_level: str = "info",
    on_bound: Callable[[str, int], None] | None = None,
) -> None:
    """Serve ``app`` until interrupted. Blocking. ``on_bound`` is called once with
    the host and real port before uvicorn takes over, so ``--port 0`` is readable
    by a parent process. ``app`` is any ASGI application: with several vendors
    named the CLI hands over ``mount``'s instead of a ``FastAPI`` one."""
    sock = bind(host, port)
    if on_bound is not None:
        on_bound(host, bound_port(sock))
    config = uvicorn.Config(app, log_level=log_level, access_log=False)
    server = uvicorn.Server(config)
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()


def run_split_server(
    build: Callable[[int], tuple[FastAPI | ASGIApp, FastAPI | ASGIApp]],
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    control_host: str = DEFAULT_HOST,
    control_port: int = 0,
    log_level: str = "info",
    on_bound: Callable[[str, int, str, int], None] | None = None,
) -> None:
    """Serve the vendor and control surfaces on two sockets in one event loop until interrupted. Blocking. ``build``
    gets the vendor socket's real port and returns ``(vendor app, control app)``, so ``port=0`` is nameable."""
    vendor_sock = bind(host, port)
    try:
        control_sock = bind(control_host, control_port)
    except BaseException:
        vendor_sock.close()
        raise
    try:
        vendor_number, control_number = bound_port(vendor_sock), bound_port(control_sock)
        vendor_app, control_app = build(vendor_number)
        if on_bound is not None:
            on_bound(host, vendor_number, control_host, control_number)
        vendor_server = uvicorn.Server(uvicorn.Config(vendor_app, log_level=log_level, access_log=False))
        control_server = uvicorn.Server(uvicorn.Config(control_app, log_level=log_level, access_log=False))

        async def serve_both() -> None:
            # Each server re-raises a caught signal to the handler it replaced, so one SIGTERM stops both.
            await asyncio.gather(
                vendor_server.serve(sockets=[vendor_sock]), control_server.serve(sockets=[control_sock])
            )

        factory = vendor_server.config.get_loop_factory()
        if factory is None:
            asyncio.run(serve_both())
        else:
            with asyncio.Runner(loop_factory=factory) as runner:
                runner.run(serve_both())
    finally:
        vendor_sock.close()
        control_sock.close()


@contextmanager
def serve_in_thread(
    app: FastAPI,
    *,
    host: str = DEFAULT_HOST,
    port: int = 0,
    log_level: str = "error",
) -> Iterator[str]:
    """Serve ``app`` on a background thread, yielding its base URL. A thread, not
    a process; separate runs need ``vendorfake.testing.served``."""
    sock = bind(host, port)
    number = bound_port(sock)
    server = uvicorn.Server(uvicorn.Config(app, log_level=log_level, access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + _THREAD_STARTUP_TIMEOUT_S
        while not server.started:
            if not thread.is_alive():
                raise RuntimeError("uvicorn exited before it started serving")
            if time.monotonic() > deadline:
                raise RuntimeError(f"uvicorn did not start within {_THREAD_STARTUP_TIMEOUT_S}s")
            time.sleep(0.01)
        yield f"http://{host}:{number}"
    finally:
        server.should_exit = True
        thread.join(_THREAD_SHUTDOWN_TIMEOUT_S)
        sock.close()
