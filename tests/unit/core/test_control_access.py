"""``VENDORFAKE_CONTROL_TOKEN`` in the kernel: refused before routing, health exempt, the vendor surface untouched, and
the token in no answer and no log line (konyklabs/roadmap#134)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from tests.fakes import make_unit, route
from vendorfake.core.config.models import ProfileDocument, parse_profile_document
from vendorfake.core.config.profile import resolve_config
from vendorfake.core.control.access import CONTROL_TOKEN_HEADER, control_access_error, names_control_plane
from vendorfake.core.control.plane import control_plane_routes
from vendorfake.core.kernel.reply import json_
from vendorfake.core.kernel.types import UnitError, UnitErrorKind
from vendorfake.core.kernel.unit import make_request
from vendorfake.core.logging import JsonLogger

TOKEN = "kernel-control-token-under-test"
REFUSAL = {
    "code": "unauthorized",
    "detail": "The control plane requires the vendorfake-control-token header.",
    "field": "vendorfake-control-token",
    "info": None,
}


def _orders(args: Any) -> Any:
    return json_({"orders": []})


def _build(token: str | None, **kwargs: Any) -> Any:
    return make_unit(
        [route("GET", "/v2/orders", _orders)], control_routes=control_plane_routes, control_token=token, **kwargs
    )


@pytest.fixture
def guarded() -> Iterator[Any]:
    built = _build(TOKEN)
    try:
        yield built
    finally:
        built.stop()


@pytest.fixture
def unguarded() -> Iterator[Any]:
    built = _build(None)
    try:
        yield built
    finally:
        built.stop()


def ask(unit: Any, method: str, path: str, token: str | None = None) -> Any:
    headers = {} if token is None else {CONTROL_TOKEN_HEADER: token}
    return unit.handle(make_request(method=method, path=path, headers=headers))


def error_of(response: Any) -> Any:
    return json.loads(response.body)["error"]


def test_a_control_route_without_the_header_is_refused_on_that_header(guarded: Any) -> None:
    response = ask(guarded, "GET", "/__unit/info")
    assert response.status == 401
    assert response.headers["x-unit-error"] == "unauthorized"
    assert error_of(response) == REFUSAL


def test_a_wrong_header_is_refused_and_the_right_one_answers(guarded: Any) -> None:
    assert ask(guarded, "GET", "/__unit/info", "not-it").status == 401
    assert ask(guarded, "GET", "/__unit/info", TOKEN[:-1]).status == 401
    assert ask(guarded, "GET", "/__unit/info", TOKEN.upper()).status == 401
    assert ask(guarded, "GET", "/__unit/info", TOKEN).status == 200
    assert ask(guarded, "GET", "/__unit/routes", TOKEN).status == 200


def test_health_answers_without_the_header_and_only_for_a_read(guarded: Any) -> None:
    assert ask(guarded, "GET", "/__unit/health").status == 200
    assert ask(guarded, "POST", "/__unit/health").status == 401


def test_an_unknown_control_path_draws_the_same_refusal_as_a_real_one(guarded: Any) -> None:
    """Before routing: a 404 or 405 without the token would enumerate the routes."""
    real = ask(guarded, "GET", "/__unit/info")
    for method, path in (("GET", "/__unit/nope"), ("DELETE", "/__unit/info"), ("GET", "/__unit")):
        refused = ask(guarded, method, path)
        assert refused.status == real.status == 401, (method, path)
        assert error_of(refused) == error_of(real)
        assert "vendorfake-near-miss" not in refused.headers


@pytest.mark.parametrize("path", ["//__unit/info", "/__unit//info", "/__unit/info/"])
def test_a_path_the_router_reads_as_the_control_plane_cannot_slip_past(guarded: Any, unguarded: Any, path: str) -> None:
    """The router drops empty segments, so the check does too: each of these reaches ``/__unit/info`` unguarded."""
    assert ask(unguarded, "GET", path).status == 200
    assert ask(guarded, "GET", path).status == 401


def test_a_vendor_route_is_unaffected(guarded: Any, unguarded: Any) -> None:
    for built in (guarded, unguarded):
        assert ask(built, "GET", "/v2/orders").status == 200
        assert ask(built, "GET", "/v2/orders", "not-it").status == 200
        assert ask(built, "GET", "/v2/nope").status == 404


def test_without_a_token_nothing_changes(unguarded: Any) -> None:
    info = ask(unguarded, "GET", "/__unit/info")
    assert info.status == 200
    assert json.loads(info.body)["control"] == {"token_required": False}
    assert ask(unguarded, "GET", "/__unit/nope").status == 404
    assert ask(unguarded, "GET", "/__unit/info", "anything").status == 200


def test_the_token_appears_in_no_answer_and_no_log_line(capfd: pytest.CaptureFixture[str]) -> None:
    built = _build(TOKEN, logger=JsonLogger("debug"))
    try:
        answers = [
            ask(built, "GET", "/__unit/info"),
            ask(built, "GET", "/__unit/nope", "not-it"),
            ask(built, "GET", "/__unit/health"),
            ask(built, "GET", "/__unit/routes", TOKEN),
            ask(built, "GET", "/v2/orders", TOKEN),
        ]
        info = ask(built, "GET", "/__unit/info", TOKEN)
        answers.append(info)
        assert json.loads(info.body)["control"] == {"token_required": True}
        for response in answers:
            assert TOKEN.encode() not in response.body
            assert all(TOKEN not in value for value in response.headers.values())
        assert TOKEN not in repr(built.context.config)
    finally:
        built.stop()
    captured = capfd.readouterr()
    assert '"status"' in captured.out + captured.err
    assert TOKEN not in captured.out + captured.err


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/__unit/info", True),
        ("/__unit", True),
        ("//__unit/info", True),
        ("/__unitx/info", False),
        ("/v2/__unit/info", False),
        ("/%5F%5Funit/info", False),
        ("/", False),
    ],
)
def test_names_control_plane_reads_a_path_as_the_router_does(path: str, expected: bool) -> None:
    assert names_control_plane(path) is expected


def test_control_access_error_is_the_one_refusal() -> None:
    refused = control_access_error("GET", "/__unit/info", {}, TOKEN)
    assert isinstance(refused, UnitError)
    assert refused.kind is UnitErrorKind.UNAUTHORIZED
    assert refused.field == CONTROL_TOKEN_HEADER
    assert control_access_error("GET", "/__unit/info", {CONTROL_TOKEN_HEADER: TOKEN}, TOKEN) is None
    assert control_access_error("HEAD", "/__unit/health", {}, TOKEN) is None
    assert control_access_error("GET", "/__unit/info", {}, None) is None
    assert control_access_error("GET", "/__unit/info", {}, "") is None


def test_the_token_is_resolved_from_the_environment_and_a_profile_document_has_no_key_for_it() -> None:
    document = ProfileDocument()
    assert resolve_config(document, name="p", env={"VENDORFAKE_CONTROL_TOKEN": TOKEN}).control.token == TOKEN
    assert resolve_config(document, name="p", env={"VENDORFAKE_CONTROL_TOKEN": ""}).control.token is None
    assert resolve_config(document, name="p").control.token is None
    with pytest.raises(UnitError) as raised:
        parse_profile_document({"control": {"token": TOKEN}}, source="inline")
    assert raised.value.field == "control"
