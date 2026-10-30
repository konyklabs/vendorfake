"""The shared reading of ``declaration.json`` and ``extract.json``.

Every other fidelity test builds on ``Surface.classify``; this file pins what
the four kinds mean, and that the loaders refuse the documents they should.
"""

from __future__ import annotations

from typing import Any

import pytest

from vendorfake.core.kernel.reply import json_
from vendorfake.core.kernel.types import ReplyInit, Route
from vendorfake.fidelity.types import (
    Alias,
    Deviation,
    Excuse,
    Extract,
    FidelityDeclaration,
    Operation,
    SpecSource,
    Surface,
    load_declaration,
    load_extract,
    route_key,
    template_shape,
    validate_declaration,
)


def _handler(_: Any) -> ReplyInit:
    return json_({})


def _route(method: str, path: str, *, internal: bool = False) -> Route:
    return Route(method=method, path=path, capability="core", handler=_handler, internal=internal)


def _json(ref: str) -> dict[str, Any]:
    return {"description": "x", "content": {"application/json": {"schema": {"$ref": ref}}}}


EXTRACT = Extract(
    {
        "openapi": "3.0.0",
        "info": {"title": "t", "version": "1"},
        "paths": {
            "/v1/things/{thing_id}": {
                "get": {"operationId": "GetThing", "responses": {"200": _json("#/components/schemas/Thing")}},
                "delete": {"operationId": "DeleteThing", "responses": {"default": _json("#/components/schemas/Err")}},
            },
            "/v1/things": {
                "post": {
                    "operationId": "CreateThing",
                    "requestBody": {
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Thing"}}}
                    },
                    "responses": {"200": _json("#/components/schemas/Thing"), "404": {"description": "no body"}},
                }
            },
        },
        "components": {"schemas": {"Thing": {"type": "object"}, "Err": {"type": "object"}}},
        "x-vendorfake": {"schema": 1, "stubbed": []},
    }
)

DECLARATION = FidelityDeclaration(
    anchor="tests.synthetic",
    sources=(SpecSource(kind="openapi3", url="https://example.invalid/x.json"),),
    aliases=(Alias(method="GET", path="/v1/things/me", spec_path="/v1/things/{thing_id}", reason="documented"),),
    excused=(Excuse(method="GET", path="/v1/legacy", reason="kept"),),
    error_envelope="200",
    error_member="errors",
)
SURFACE = Surface(DECLARATION, EXTRACT)


def test_template_shape_erases_parameter_names_only() -> None:
    assert template_shape("/v1/things/{thing_id}") == template_shape("/v1/things/{id}") == "/v1/things/{}"
    assert template_shape("/v1/things/me") == "/v1/things/me"
    assert route_key("get", "/x") == "GET /x"


@pytest.mark.parametrize(
    ("route", "kind"),
    [
        (_route("GET", "/v1/things/{id}"), "operation"),
        (_route("DELETE", "/v1/things/{id}"), "operation"),
        (_route("GET", "/v1/things/me"), "operation"),
        (_route("GET", "/v1/legacy"), "excused"),
        (_route("GET", "/__unit/info", internal=True), "internal"),
        (_route("GET", "/__vendor/stand-in"), "internal"),
        (_route("PUT", "/v1/things/{id}"), "undeclared"),
        (_route("GET", "/v1/other"), "undeclared"),
    ],
)
def test_every_route_is_exactly_one_kind(route: Route, kind: str) -> None:
    classified = SURFACE.classify(route)
    assert classified.kind == kind
    assert (classified.operation is not None) == (kind == "operation")
    if kind == "excused":
        assert classified.reason == "kept"
    if route.path == "/v1/things/me":
        assert classified.alias is not None
        assert classified.operation is not None
        assert classified.operation.key == "GET /v1/things/{thing_id}"


def test_response_schema_precedence_is_exact_then_default_then_envelope() -> None:
    get = EXTRACT.operation("GET", "/v1/things/{x}")
    delete = EXTRACT.operation("DELETE", "/v1/things/{x}")
    post = EXTRACT.operation("POST", "/v1/things")
    assert isinstance(get, Operation) and isinstance(delete, Operation) and isinstance(post, Operation)
    assert get.response_schema(200) == {"$ref": "#/components/schemas/Thing"}
    assert get.response_schema(400) is None
    assert get.response_schema(400, error_envelope="200") == {"$ref": "#/components/schemas/Thing"}
    assert delete.response_schema(418) == {"$ref": "#/components/schemas/Err"}
    # A declared status with no JSON content falls through to the envelope, not to None.
    assert post.response_schema(404, error_envelope="200") == {"$ref": "#/components/schemas/Thing"}
    assert post.request_schema() == {"$ref": "#/components/schemas/Thing"}
    assert get.request_schema() is None


def test_the_envelope_is_never_the_schema_for_a_status_below_400() -> None:
    """konyklabs/roadmap#170 F1: the envelope describes error bodies. A 201, a 204 or a 302 the operation does not
    declare has no schema, so the validator's "no schema for status" path decides it instead of the 200's schema
    quietly accepting a success the vendor never documents."""
    get = EXTRACT.operation("GET", "/v1/things/{x}")
    assert isinstance(get, Operation)
    for status in (201, 204, 302, 399):
        assert get.response_schema(status, error_envelope="200") is None
    assert get.response_schema(400, error_envelope="200") == {"$ref": "#/components/schemas/Thing"}


def test_an_extract_must_be_openapi_3() -> None:
    with pytest.raises(ValueError, match="OpenAPI 3"):
        Extract({"swagger": "2.0", "paths": {}})


def test_a_declaration_needs_a_schema_and_a_source() -> None:
    with pytest.raises(ValueError, match='"schema": 1'):
        FidelityDeclaration.of("x", {"sources": [{"kind": "openapi3", "url": "u"}]})
    with pytest.raises(ValueError, match="at least one spec source"):
        FidelityDeclaration.of("x", {"schema": 1, "sources": []})
    with pytest.raises(ValueError, match="unknown spec source kind"):
        FidelityDeclaration.of("x", {"schema": 1, "sources": [{"kind": "wsdl", "url": "u"}]})


def test_loaders_name_the_missing_package() -> None:
    with pytest.raises(FileNotFoundError, match=r"declaration\.json"):
        load_declaration("vendorfake.fidelity")
    # The extract needs the declaration first (it decides whether the extract
    # is beside it or cut at run time), so the missing file named is that one.
    with pytest.raises(FileNotFoundError, match=r"declaration\.json"):
        load_extract("vendorfake.fidelity")


# -- deviations and the declaration schema ---------------------------------


def test_a_deviation_needs_a_value_and_a_real_pointer_segment() -> None:
    row = {"pointer": "/errors/*/code", "keyword": "enum", "value": "X", "reason": "r", "url": "https://d/"}
    assert Deviation.of(row).value == "X"
    with pytest.raises(ValueError, match="exactly one"):
        Deviation.of({k: v for k, v in row.items() if k != "value"})
    # null is a value a vendor's examples answer where its schema says string.
    assert (
        Deviation.of({**row, "value": None}).matches(keyword="type", pointer="/errors/0/code", instance=None) is False
    )
    assert Deviation.of({**row, "keyword": "type", "value": None}).matches(
        keyword="type", pointer="/errors/0/code", instance=None
    )
    with pytest.raises(ValueError, match="at least one real segment"):
        Deviation.of({**row, "pointer": "/*/*"})
    with pytest.raises(ValueError, match="absolute"):
        Deviation.of({**row, "pointer": "errors/0/code"})


def test_a_deviation_matches_one_keyword_one_value_one_shape_and_its_routes() -> None:
    dev = Deviation.of(
        {
            "pointer": "/errors/*/code",
            "keyword": "enum",
            "value": "X",
            "reason": "r",
            "url": "https://d/",
            "routes": ["PUT /a"],
        }
    )
    assert dev.matches(keyword="enum", pointer="/errors/3/code", instance="X", route_key="PUT /a")
    assert not dev.matches(keyword="enum", pointer="/errors/3/code", instance="X", route_key="GET /b")
    assert not dev.matches(keyword="enum", pointer="/errors/3/code", instance="Y", route_key="PUT /a")
    assert not dev.matches(keyword="type", pointer="/errors/3/code", instance="X", route_key="PUT /a")
    assert not dev.matches(keyword="enum", pointer="/errors/code", instance="X", route_key="PUT /a")


def test_the_declaration_schema_refuses_the_widenings_by_typo() -> None:
    good = {"schema": 1, "sources": [{"kind": "openapi3", "url": "https://x/spec.json"}]}
    validate_declaration(good, where="t")
    with pytest.raises(ValueError, match="error_member"):
        validate_declaration({**good, "error_envelope": "200"}, where="t")
    with pytest.raises(ValueError, match="not valid under any"):
        validate_declaration(
            {**good, "deviations": [{"pointer": "/a", "keyword": "enum", "reason": "r", "url": "https://d/"}]},
            where="t",
        )
    with pytest.raises(ValueError, match="Additional properties"):
        validate_declaration({**good, "excuses": []}, where="t")
    with pytest.raises(ValueError, match="error_member"):
        FidelityDeclaration.of("t", {**good, "error_envelope": "200"})


def test_a_deviation_value_keeps_its_json_type() -> None:
    row = {"pointer": "/errors/*/code", "keyword": "enum", "value": 402, "reason": "r", "url": "https://d/"}
    dev = Deviation.of(row)
    assert dev.matches(keyword="enum", pointer="/errors/0/code", instance=402)
    assert not dev.matches(keyword="enum", pointer="/errors/0/code", instance="402")
    assert not dev.matches(keyword="enum", pointer="/errors/0/code", instance=402.0)
    assert dev.label == "enum /errors/*/code = 402"
    with pytest.raises(ValueError, match="scalar"):
        Deviation.of({**row, "value": [402]})


def test_a_range_status_key_is_consulted_before_default_and_envelope() -> None:
    ranged = Extract(
        {
            "openapi": "3.0.0",
            "info": {"title": "t", "version": "1"},
            "paths": {
                "/v1/x": {
                    "get": {
                        "responses": {
                            "200": _json("#/components/schemas/Ok"),
                            "4XX": _json("#/components/schemas/ClientErr"),
                            "default": _json("#/components/schemas/Err"),
                        }
                    }
                }
            },
            "components": {"schemas": {"Ok": {}, "ClientErr": {}, "Err": {}}},
        }
    )
    op = ranged.operation("GET", "/v1/x")
    assert op is not None
    assert op.response_schema(404, error_envelope="200") == {"$ref": "#/components/schemas/ClientErr"}
    assert op.response_schema(503, error_envelope="200") == {"$ref": "#/components/schemas/Err"}
    assert op.response_schema(200) == {"$ref": "#/components/schemas/Ok"}


def test_an_override_is_one_route_one_status_one_component() -> None:
    row = {"route": "GET /v1/things", "status": 200, "schema": "Thing", "reason": "r", "url": "https://d/"}
    declaration = FidelityDeclaration.of(
        "t", {"schema": 1, "sources": [{"kind": "openapi3", "url": "https://x/s.json"}], "overrides": [row]}
    )
    assert declaration.override_for("GET /v1/things", 200) is not None
    assert declaration.override_for("GET /v1/things", 404) is None
    assert declaration.override_for("POST /v1/things", 200) is None
    with pytest.raises(ValueError, match="overrides"):
        validate_declaration(
            {
                "schema": 1,
                "sources": [{"kind": "openapi3", "url": "https://x/s.json"}],
                "overrides": [{**row, "status": "200"}],
            },
            where="t",
        )


def test_a_deviation_may_name_a_pattern_instead_of_a_value_and_glob_a_segment() -> None:
    row = {
        "pointer": "/**/*Date",
        "keyword": "format",
        "pattern": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+0000",
        "reason": "the vendor's documented timestamp format",
        "url": "https://d/",
    }
    dev = Deviation.of(row)
    assert dev.matches(keyword="format", pointer="/checks/0/openedDate", instance="2026-09-02T13:45:17.000+0000")
    assert dev.matches(keyword="format", pointer="/modifiedDate", instance="2026-09-02T13:45:17.001+0000")
    assert not dev.matches(keyword="format", pointer="/checks/0/openedDate", instance="2026-09-02T13:45:17Z")
    assert not dev.matches(keyword="format", pointer="/checks/0/dateOpened", instance="2026-09-02T13:45:17.000+0000")
    assert not dev.matches(keyword="type", pointer="/openedDate", instance="2026-09-02T13:45:17.000+0000")
    assert dev.label.startswith("format /**/*Date ~ /")
    with pytest.raises(ValueError, match="exactly one"):
        Deviation.of({**row, "value": "x"})
    with pytest.raises(ValueError, match="exactly one"):
        Deviation.of({k: v for k, v in row.items() if k != "pattern"})
    with pytest.raises(ValueError, match="regular expression"):
        Deviation.of({**row, "pattern": "("})


def _media(*pairs: tuple[str, str]) -> dict[str, Any]:
    return {"description": "x", "content": {media: {"schema": {"$ref": ref}} for media, ref in pairs}}


STAR = Extract(
    {
        "openapi": "3.1.0",
        "info": {"title": "t", "version": "1"},
        "paths": {
            "/v1/star": {
                "post": {
                    "requestBody": {"content": {"*/*": {"schema": {"$ref": "#/components/schemas/In"}}}},
                    "responses": {
                        "200": _media(("*/*", "#/components/schemas/Ok")),
                        "503": _media(("*/*", "#/components/schemas/Busy")),
                    },
                }
            },
            "/v1/both": {
                "post": {
                    "requestBody": {
                        "content": {
                            "*/*": {"schema": {"$ref": "#/components/schemas/Busy"}},
                            "application/json": {"schema": {"$ref": "#/components/schemas/In"}},
                        }
                    },
                    "responses": {
                        "200": _media(
                            ("*/*", "#/components/schemas/Busy"), ("application/json", "#/components/schemas/Ok")
                        )
                    },
                }
            },
            "/v1/text": {"get": {"responses": {"200": _media(("text/plain", "#/components/schemas/Ok"))}}},
        },
        "components": {"schemas": {"In": {}, "Ok": {}, "Busy": {}}},
    }
)


def test_a_body_declared_only_under_any_media_type_is_looked_up_as_json() -> None:
    """konyklabs/roadmap#179: a document that declares a body under ``*/*`` alone still describes the JSON the
    route answers; before this the lookup found no schema and the validator called the status undeclared."""
    star = STAR.operation("POST", "/v1/star")
    assert star is not None
    assert star.response_schema(503) == {"$ref": "#/components/schemas/Busy"}
    assert star.response_schema(200) == {"$ref": "#/components/schemas/Ok"}
    assert star.request_schema() == {"$ref": "#/components/schemas/In"}


def test_application_json_wins_over_any_media_type_whatever_the_order() -> None:
    both = STAR.operation("POST", "/v1/both")
    assert both is not None
    assert both.response_schema(200) == {"$ref": "#/components/schemas/Ok"}
    assert both.request_schema() == {"$ref": "#/components/schemas/In"}


def test_a_non_json_media_type_is_still_no_schema() -> None:
    text_op = STAR.operation("GET", "/v1/text")
    assert text_op is not None
    assert text_op.response_schema(200) is None


# ---------------------------------------------------------------------------
# Webhooks rows (konyklabs/roadmap#185).
# ---------------------------------------------------------------------------

_GOOD = {"schema": 1, "sources": [{"kind": "openapi3", "url": "https://x/spec.json"}]}


@pytest.mark.parametrize(
    ("rows", "needle"),
    [
        ([{"name": "order notice"}], "'reason' is a required property"),
        ([{"name": "", "reason": "r"}], "should be non-empty"),
        ([{"name": "order notice", "reason": "r", "topic": "x"}], "Additional properties"),
        ([{"name": "a", "reason": "r"}, {"name": "a", "reason": "r"}], "non-unique elements"),
        ([{"name": "a", "reason": "r", "event_types": []}], "should be non-empty"),
    ],
)
def test_the_declaration_schema_refuses_a_malformed_webhooks_row(rows: list[dict[str, Any]], needle: str) -> None:
    with pytest.raises(ValueError, match=needle):
        validate_declaration({**_GOOD, "webhooks": rows}, where="t")


def test_several_webhooks_rows_each_need_event_types_or_the_declaration_is_refused() -> None:
    rows = [{"name": "a", "reason": "r", "event_types": ["order.*"]}, {"name": "b", "reason": "r"}]
    validate_declaration({**_GOOD, "webhooks": rows}, where="t")  # the schema allows it; the loader does not
    with pytest.raises(ValueError, match="every row needs event_types"):
        FidelityDeclaration.of("t", {**_GOOD, "webhooks": rows})


def test_a_delivery_maps_to_the_one_entry_or_to_the_first_whose_globs_cover_it() -> None:
    one = FidelityDeclaration.of("t", {**_GOOD, "webhooks": [{"name": "a", "reason": "r"}]})
    assert one.webhook_for("anything:at:all") == one.webhooks[0]
    rows = [
        {"name": "orders", "reason": "r", "event_types": ["order:*"]},
        {"name": "refunds", "reason": "r", "event_types": ["refund.created", "refund.updated"]},
    ]
    several = FidelityDeclaration.of("t", {**_GOOD, "webhooks": rows})
    assert [hook.name for hook in several.webhooks] == ["orders", "refunds"]
    assert several.webhook_for("order:SUCCESS:E1") is not None
    assert several.webhook_for("order:SUCCESS:E1").name == "orders"  # type: ignore[union-attr]
    assert several.webhook_for("refund.updated").name == "refunds"  # type: ignore[union-attr]
    assert several.webhook_for("payment.created") is None
    assert FidelityDeclaration.of("t", _GOOD).webhooks == ()
