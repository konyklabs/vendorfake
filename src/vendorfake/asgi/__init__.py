"""The transport adapter: the only package here that imports a web framework.

``adapt`` converts to and from the core's request and response types, ``app``
registers one catch-all route over a unit, ``mount`` puts one such application
per vendor under ``/<vendor>/`` when several were asked for, ``serve`` puts the
result on a socket. The build fails if ``fastapi``, ``starlette`` or
``uvicorn`` is reached elsewhere."""

from vendorfake.asgi.adapt import TRANSPORT, to_response, to_unit_request
from vendorfake.asgi.app import (
    HTTP_METHODS,
    OPENAPI_PATH,
    TransportFaultAbort,
    create_app,
    registered_methods,
)
from vendorfake.asgi.mount import ASGIApp, MountedApp, create_mounted_app
from vendorfake.asgi.serve import DEFAULT_HOST, DEFAULT_PORT, bind, bound_port, run_server, serve_in_thread

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "HTTP_METHODS",
    "OPENAPI_PATH",
    "TRANSPORT",
    "ASGIApp",
    "MountedApp",
    "TransportFaultAbort",
    "bind",
    "bound_port",
    "create_app",
    "create_mounted_app",
    "registered_methods",
    "run_server",
    "serve_in_thread",
    "to_response",
    "to_unit_request",
]
