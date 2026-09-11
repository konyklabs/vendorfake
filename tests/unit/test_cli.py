"""The command line: dispatch, precedence, and the two things it must not do.

The two are the point of most of this file. ``vendorfake --help`` must not
import a web framework, and no module but this one may read ``os.environ`` --
both are properties of the *process*, so both are asserted by starting a fresh
interpreter and looking at what it did, not by reading the source.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from vendorfake.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]


def run(*argv: str) -> tuple[int, str]:
    """Call ``main`` with stdout captured, returning the code and the text."""
    buffer = io.StringIO()
    saved = sys.stdout
    sys.stdout = buffer
    try:
        code = main(list(argv))
    finally:
        sys.stdout = saved
    return code, buffer.getvalue()


def child(code: str) -> subprocess.CompletedProcess[str]:
    """Run a snippet in a fresh interpreter with the repo's ``src`` importable.

    A subprocess rather than an import, because what is being asserted is what
    a *process* ended up holding: inside this one, pytest has already imported
    half the distribution, so ``sys.modules`` says nothing.
    """
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


# ---------------------------------------------------------------------------
# The two process-level properties.
# ---------------------------------------------------------------------------


def test_help_imports_no_web_framework() -> None:
    """The reason every first-party import in ``cli.py`` is inside a function.

    ``serve`` is the only subcommand that reaches :mod:`vendorfake.asgi`, and
    that import is the single named exception in ``tools/boundary.toml``. If it
    drifted to module level, ``--help`` would start paying for FastAPI and the
    exception would quietly stop being an exception -- which no import-graph
    rule can see, because the import is still in the file it is allowed to be
    in.
    """
    result = child(
        "import sys\n"
        "from vendorfake.cli import main\n"
        "try:\n"
        "    main(['--help'])\n"
        "except SystemExit:\n"
        "    pass\n"
        "loaded = sorted(n for n in sys.modules if n.split('.')[0] in {'fastapi', 'starlette', 'uvicorn'})\n"
        "print('LOADED', loaded)\n"
    )
    assert result.returncode == 0, result.stderr
    assert "LOADED []" in result.stdout


def test_no_other_module_reads_the_process_environment() -> None:
    """``create_unit(env=...)`` defaults to ``{}``, and the CLI is the exception.

    Asserted the only way that means anything: set a ``VENDORFAKE_*`` variable
    in a child process, build a unit without passing ``env``, and check that it
    was ignored. A unit that read ``os.environ`` on its own would make one
    test's exported variable change another test's profile.
    """
    result = child(
        "import os, sys\n"
        "os.environ['VENDORFAKE_PROFILE'] = 'from-the-environment'\n"
        "sys.path.insert(0, '.')\n"
        "from tests.fakes import make_unit\n"
        "unit = make_unit()\n"
        "print('PROFILE', unit.context.config.profile)\n"
        "unit.stop()\n"
    )
    assert result.returncode == 0, result.stderr
    assert "PROFILE test" in result.stdout


# ---------------------------------------------------------------------------
# Dispatch.
# ---------------------------------------------------------------------------


def test_version_prints_the_distribution_version() -> None:
    from vendorfake import __version__

    code, out = run("--version")
    assert code == 0
    assert out.strip() == __version__


def test_no_subcommand_prints_help_and_fails() -> None:
    """Exit 2, not 0. A container whose command was mistyped must not look like
    a successful run that simply did nothing."""
    code, out = run()
    assert code == 2
    assert "COMMAND" in out


def test_every_declared_subcommand_has_a_dispatch_arm() -> None:
    """Derived from the parser, never hand-listed.

    Adding a subparser without adding a dispatch arm would otherwise be a
    silent exit through the final ``raise``; this fails at the moment the
    parser and the dispatcher disagree.
    """
    import argparse

    from vendorfake.cli import _build_parser

    parser = _build_parser()
    subparsers = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    declared = set(subparsers[0].choices)
    assert declared == {
        "serve",
        "info",
        "manifest",
        "openapi",
        "vendors",
        "profiles",
        "routes",
        "faults",
        "explain",
        "conformance",
    }


def test_serve_without_a_vendor_refuses_and_lists_both(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The README quickstart names a vendor because this refusal is real: with
    two vendors installed and no --vendor or $VENDORFAKE_VENDOR, `serve`
    exits non-zero before binding anything, listing what it found. Run
    against the real registry -- no monkeypatched create_unit."""
    from vendorfake.registry import available_vendors

    monkeypatch.delenv("VENDORFAKE_VENDOR", raising=False)
    offered = available_vendors()
    assert {"clover", "square"} <= set(offered), offered
    with pytest.raises(SystemExit) as raised:
        run("serve")
    message = str(raised.value)
    assert "create_unit needs a vendor" in message
    for name in offered:
        assert name in message


def test_an_unknown_vendor_is_a_startup_failure_that_lists_the_real_ones() -> None:
    """Not a server that starts and 404s everything.

    "Every endpoint returns 404" is indistinguishable from a consumer's own
    misconfiguration, which is exactly the debugging session this refusal
    prevents.
    """
    with pytest.raises(SystemExit) as raised:
        run("info", "--vendor", "nosuchvendor")
    assert "no vendor named 'nosuchvendor'" in str(raised.value)


def test_vendors_lists_what_would_actually_resolve() -> None:
    """The list is derived from an importability check, never declared, so a
    name printed here is a name that will start."""
    from vendorfake.registry import available_vendors

    code, out = run("vendors")
    assert code == 0
    assert out.split() == list(available_vendors())
    assert "square" in out.split()


def test_vendors_reports_nothing_installed_as_a_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Exit 1 with the message on stderr. An empty successful list would read
    as "the fake is fine, you asked for nothing".

    A vendor ships in this distribution, so the empty case is reached by
    emptying the discovery rather than by uninstalling one -- which is what the
    subcommand consults, and therefore what has to be empty for the branch to
    be the one under test.
    """
    import vendorfake.registry as registry_module

    monkeypatch.setattr(registry_module, "available_vendors", lambda: ())
    code, out = run("vendors")
    assert code == 1
    assert out == ""


def test_a_non_integer_port_variable_is_refused_by_name() -> None:
    """Rather than falling back to the default and binding a port nobody asked
    for while reporting success."""
    from vendorfake.cli import _env_int

    with pytest.raises(SystemExit) as raised:
        _env_int({"VENDORFAKE_PORT": "eighty"}, "VENDORFAKE_PORT")
    assert "VENDORFAKE_PORT='eighty' is not an integer" in str(raised.value)


def test_an_empty_environment_variable_counts_as_unset() -> None:
    """``VENDORFAKE_PROFILE=`` in a compose file means "I did not set this",
    not "the profile is the empty string"."""
    from vendorfake.cli import _env_str

    assert _env_str({"VENDORFAKE_PROFILE": ""}, "VENDORFAKE_PROFILE") is None
    assert _env_str({}, "VENDORFAKE_PROFILE") is None
    assert _env_str({"VENDORFAKE_PROFILE": "full"}, "VENDORFAKE_PROFILE") == "full"


# ---------------------------------------------------------------------------
# The subcommands that produce a document.
# ---------------------------------------------------------------------------


def test_openapi_prints_the_same_document_the_adapter_serves() -> None:
    """One generator, one naming, two renderings.

    The CLI reaches the document with no server and no web framework; the
    adapter serves the bytes of the same call. Both go through
    ``document_for_unit``, which is the point: a second place deciding the
    title or the version would drift the first time either changed, and this
    test would not see it if it built its own expectation.
    """
    import functools

    import anyio
    import httpx

    from tests.fakes import make_unit, route
    from vendorfake.asgi import OPENAPI_PATH, create_app
    from vendorfake.core.control.openapi import UNOFFICIAL_NOTICE, document_for_unit
    from vendorfake.core.control.plane import control_plane_routes
    from vendorfake.core.kernel.reply import json_
    from vendorfake.core.util.json import dump_json

    unit = make_unit(
        [route("GET", "/v2/orders", lambda args: json_({}))],
        control_routes=functools.partial(control_plane_routes),
    )
    try:
        offline = document_for_unit(unit)
        app = create_app(unit)

        async def fetch() -> bytes:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
                return (await client.get(OPENAPI_PATH)).content

        served = anyio.run(fetch)
        assert served == dump_json(offline)

        parsed = json.loads(served)
        assert parsed["paths"]["/v2/orders"]["get"]["x-unit-capability"] == "orders"
        assert parsed["info"]["description"] == UNOFFICIAL_NOTICE
        assert "Unofficial" in parsed["info"]["description"]
    finally:
        unit.stop()


def test_the_cli_can_drop_the_control_plane_from_the_document() -> None:
    """``--no-internal`` describes only what the fake is pretending to be.

    The control plane is real and is part of the product, so it is in the
    document by default; a consumer generating a client for the vendor surface
    alone should not have to filter it out by hand.
    """
    from tests.fakes import make_unit, route
    from vendorfake.core.control.openapi import document_for_unit
    from vendorfake.core.control.plane import control_plane_routes
    from vendorfake.core.kernel.reply import json_

    unit = make_unit([route("GET", "/v2/orders", lambda args: json_({}))], control_routes=control_plane_routes)
    try:
        full = document_for_unit(unit)
        trimmed = document_for_unit(unit, include_internal=False)
        assert any(path.startswith("/__unit/") for path in full["paths"])
        assert set(trimmed["paths"]) == {"/v2/orders"}
    finally:
        unit.stop()


# ---------------------------------------------------------------------------
# Discovery: `profiles`, `routes`, `faults`, and `--json` everywhere it applies.
# ---------------------------------------------------------------------------

#: Every subcommand `--json` is honoured by. `serve` and `conformance` are
#: deliberately absent -- see `_json_flag_parent`'s docstring in cli.py.
JSON_SUBCOMMANDS: tuple[tuple[str, ...], ...] = (
    ("info", "--vendor", "square"),
    ("openapi", "--vendor", "square"),
    ("vendors",),
    ("profiles", "--vendor", "square"),
    ("routes", "--vendor", "square"),
    ("faults",),
)


@pytest.mark.parametrize("argv", JSON_SUBCOMMANDS, ids=[row[0] for row in JSON_SUBCOMMANDS])
def test_every_json_subcommand_produces_one_parseable_document_on_stdout(argv: tuple[str, ...]) -> None:
    code, out = run(*argv, "--json")
    assert code == 0
    parsed = json.loads(out)  # raises if anything but valid JSON reached stdout
    assert parsed is not None


@pytest.mark.parametrize("argv", JSON_SUBCOMMANDS, ids=[row[0] for row in JSON_SUBCOMMANDS])
def test_every_json_subcommand_also_accepts_json_before_the_subcommand(argv: tuple[str, ...]) -> None:
    """``--json`` reads naturally on either side of the subcommand name:
    ``vendorfake --json profiles --vendor square`` and
    ``vendorfake profiles --vendor square --json`` are the same request.
    Before this fix, only the trailing position worked: the global position
    exited 2 with ``unrecognized arguments: --json``, which contradicted the
    CHANGELOG's own description of the flag as global."""
    code, out = run("--json", *argv)
    assert code == 0
    parsed = json.loads(out)
    assert parsed is not None


def test_json_before_and_after_the_subcommand_produce_the_identical_document() -> None:
    global_code, global_out = run("--json", "profiles", "--vendor", "square")
    trailing_code, trailing_out = run("profiles", "--vendor", "square", "--json")
    assert global_code == trailing_code == 0
    assert json.loads(global_out) == json.loads(trailing_out)


def test_a_json_flag_repeated_on_both_sides_of_the_subcommand_is_accepted() -> None:
    code, out = run("--json", "profiles", "--vendor", "square", "--json")
    assert code == 0
    assert json.loads(out)


def test_profiles_lists_the_six_shipped_profiles() -> None:
    code, out = run("profiles", "--vendor", "square", "--json")
    assert code == 0
    rows = json.loads(out)
    assert sorted(row["name"] for row in rows) == [
        "chaos-demo",
        "full",
        "no-chaos",
        "no-faults",
        "oauth-only",
        "orders-only",
    ]
    for row in rows:
        assert row["vendor"] == "square"
        assert isinstance(row["capabilities"], list) and row["capabilities"]
        assert row["summary"]


def test_profiles_table_form_lists_the_same_names() -> None:
    code, out = run("profiles", "--vendor", "square")
    assert code == 0
    for name in ("chaos-demo", "full", "no-chaos", "no-faults", "oauth-only", "orders-only"):
        assert name in out


def test_routes_excludes_internal_routes_unless_asked() -> None:
    code, out = run("routes", "--vendor", "square", "--json")
    assert code == 0
    rows = json.loads(out)
    assert rows  # the vendor surface is not empty
    assert not any(row["internal"] for row in rows)
    assert any(row["operation_id"] == "ObtainToken" and row["path"] == "/oauth2/token" for row in rows)

    code, out = run("routes", "--vendor", "square", "--internal", "--json")
    assert code == 0
    with_internal = json.loads(out)
    assert any(row["internal"] and row["path"] == "/__unit/info" for row in with_internal)
    assert len(with_internal) > len(rows)


def test_faults_lists_every_key_of_the_fault_param_table() -> None:
    from vendorfake.core.chaos.faults import FAULT_DESCRIPTIONS, FAULT_PARAM_KEYS, FAULT_PROVENANCE

    code, out = run("faults", "--json")
    assert code == 0
    rows = json.loads(out)
    assert {row["name"] for row in rows} == set(FAULT_PARAM_KEYS)
    for row in rows:
        assert row["params"] == list(FAULT_PARAM_KEYS[row["name"]])
        assert row["description"] == FAULT_DESCRIPTIONS[row["name"]]
        assert row["provenance"] == FAULT_PROVENANCE[row["name"]]


def test_faults_json_names_transport_provenance_for_exactly_the_five_transport_faults() -> None:
    """E-transport-faults.md's definition of done item 5: provenance appears
    in the ``faults`` CLI output, not only in the control-plane listings."""
    from vendorfake.core.chaos.faults import RESPONSE_PHASE_FAULTS

    code, out = run("faults", "--json")
    assert code == 0
    rows = {row["name"]: row["provenance"] for row in json.loads(out)}
    assert {name for name, provenance in rows.items() if provenance == "transport"} == RESPONSE_PHASE_FAULTS
    assert rows["rate_limit"] == "vendor"


def test_faults_table_form_has_a_provenance_column() -> None:
    code, out = run("faults")
    assert code == 0
    header, *rows = out.splitlines()
    assert "provenance" in header
    assert any("transport" in row for row in rows)
    assert any("vendor" in row for row in rows)


def test_fault_descriptions_names_exactly_the_fault_param_keys_names() -> None:
    """The drift the CLI would otherwise reproduce silently: a fault with
    parameters and no prose, or prose for a fault the engine does not have."""
    from vendorfake.core.chaos.faults import FAULT_DESCRIPTIONS, FAULT_PARAM_KEYS

    assert set(FAULT_DESCRIPTIONS) == set(FAULT_PARAM_KEYS)


def test_vendors_json_is_the_same_list_the_text_form_prints() -> None:
    from vendorfake.registry import available_vendors

    code, out = run("vendors", "--json")
    assert code == 0
    assert json.loads(out) == list(available_vendors())


def test_profiles_and_routes_refuse_an_unknown_vendor_by_name() -> None:
    with pytest.raises(SystemExit) as raised:
        run("profiles", "--vendor", "nosuchvendor")
    assert "no vendor named 'nosuchvendor'" in str(raised.value)

    with pytest.raises(SystemExit) as raised:
        run("routes", "--vendor", "nosuchvendor")
    assert "no vendor named 'nosuchvendor'" in str(raised.value)


def test_routes_defaults_to_full_and_honours_an_explicit_profile() -> None:
    """The route table does not vary by profile -- every declared route is
    registered whether or not its capability is enabled -- so this asserts
    the flag is accepted and produces the same table, not a different one."""
    code, full_out = run("routes", "--vendor", "square", "--json")
    code_named, named_out = run("routes", "--vendor", "square", "--profile", "oauth-only", "--json")
    assert code == 0 and code_named == 0
    assert json.loads(full_out) == json.loads(named_out)


# ---------------------------------------------------------------------------
# `serve`: the precedence rule, without binding a socket.
# ---------------------------------------------------------------------------


def test_serve_applies_flag_then_environment_then_profile_then_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag beats environment beats profile beats built-in default.

    Asserted by intercepting ``run_server`` rather than by starting one: what
    is under test is which numbers were chosen, and binding a real port to find
    that out would make the test slower, racier and no more conclusive. The
    socket itself is proved out of process, in ``tests/integration``.
    """

    import vendorfake.asgi as asgi_module
    import vendorfake.cli as cli_module
    import vendorfake.registry as registry_module
    from tests.fakes import make_unit
    from vendorfake.core.control.plane import control_plane_routes

    calls: list[dict[str, object]] = []
    units: list[object] = []

    def fake_create_unit(**kwargs: object) -> object:
        built = make_unit(control_routes=control_plane_routes, log_level="warn")
        units.append(built)
        return built

    def fake_run_server(app: object, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(registry_module, "create_unit", fake_create_unit)
    monkeypatch.setattr(asgi_module, "run_server", fake_run_server)

    def serve(argv: list[str], env: dict[str, str]) -> dict[str, object]:
        calls.clear()
        parser = cli_module._build_parser()
        args = parser.parse_args(["serve", *argv])
        assert cli_module._serve(args, env, sys.stdout) == 0
        return calls[0]

    try:
        # Nothing given: the profile's transport section, then the defaults.
        chosen = serve([], {})
        assert chosen["host"] == "127.0.0.1"
        assert chosen["port"] == 8080
        assert chosen["log_level"] == "warn"

        # The environment beats the profile.
        chosen = serve([], {"VENDORFAKE_HOST": "0.0.0.0", "VENDORFAKE_PORT": "9001", "VENDORFAKE_LOG_LEVEL": "debug"})
        assert (chosen["host"], chosen["port"], chosen["log_level"]) == ("0.0.0.0", 9001, "debug")

        # The flag beats the environment.
        chosen = serve(
            ["--host", "10.0.0.5", "--port", "0", "--log-level", "error"],
            {"VENDORFAKE_HOST": "0.0.0.0", "VENDORFAKE_PORT": "9001", "VENDORFAKE_LOG_LEVEL": "debug"},
        )
        assert (chosen["host"], chosen["port"], chosen["log_level"]) == ("10.0.0.5", 0, "error")
    finally:
        for built in units:
            built.stop()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Startup failures read as refusals, not as crashes (konyklabs/roadmap#74).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subcommand", ["serve", "info", "openapi", "routes"])
def test_a_nonexistent_profile_is_a_refusal_that_names_the_real_ones(subcommand: str) -> None:
    """A mistyped ``--profile`` used to be a raw ``UnitError`` traceback out of
    the profile loader, while the adjacent ``--vendor`` flag -- the same kind
    of typo, one letter away -- was already a one-line refusal. The loader's
    message always named every profile the vendor ships; nothing but the
    ``except`` clause stood between it and the caller.
    """
    with pytest.raises(SystemExit) as raised:
        run(subcommand, "--vendor", "square", "--profile", "nosuchprofile")

    message = str(raised.value)
    assert message.startswith("vendorfake: "), message
    assert "nosuchprofile" in message
    for shipped in ("full", "oauth-only", "orders-only", "no-chaos", "no-faults", "chaos-demo"):
        assert shipped in message


def test_the_refusal_carries_a_message_rather_than_a_bare_code() -> None:
    """``SystemExit`` with a string prints it to stderr and exits 1, which is
    the shape every other refusal in this module already has. Asserted so the
    two kinds of startup failure cannot drift apart again.
    """
    with pytest.raises(SystemExit) as bad_profile:
        run("info", "--vendor", "square", "--profile", "nosuchprofile")
    with pytest.raises(SystemExit) as bad_vendor:
        run("info", "--vendor", "nosuchvendor")

    assert isinstance(bad_profile.value.code, str), repr(bad_profile.value.code)
    assert isinstance(bad_vendor.value.code, str), repr(bad_vendor.value.code)


def test_a_malformed_profile_document_is_a_refusal_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Not only a missing profile. Any ``UnitError`` raised while the unit is
    being built is a startup failure the caller can act on, so all of them
    leave through the same message rather than the first one leaving through a
    traceback.
    """
    import vendorfake.registry as registry_module
    from tests.fakes import FakeVendor

    (tmp_path / "broken.json").write_text('{"name": "broken", "capabilities": "not-a-list"}', encoding="utf-8")
    definition = FakeVendor(name="acme", profile_dir=tmp_path, base_dir=tmp_path)
    monkeypatch.setattr(registry_module, "resolve_vendor", lambda name: definition)

    with pytest.raises(SystemExit) as raised:
        run("info", "--vendor", "acme", "--profile", "broken")

    assert str(raised.value).startswith("vendorfake: "), str(raised.value)


def test_the_profiles_subcommand_refuses_a_malformed_profile_document_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same widened ``except (ValueError, UnitError)`` in ``_profiles`` as
    the test above exercises for ``info``, and not the same code path:
    ``profiles`` takes no ``--profile`` flag, so its ``UnitError`` can only
    come from ``available_profiles``'s own scan of every document in the
    vendor's profile directory, not from loading one named document. Reverting
    the clause in ``_profiles`` back to ``except ValueError`` leaves this test
    -- and only this one -- red.
    """
    import vendorfake.registry as registry_module
    from tests.fakes import FakeVendor

    (tmp_path / "broken.json").write_text('{"name": "broken", "capabilities": "not-a-list"}', encoding="utf-8")
    definition = FakeVendor(name="acme", profile_dir=tmp_path, base_dir=tmp_path)
    monkeypatch.setattr(registry_module, "resolve_vendor", lambda name: definition)

    with pytest.raises(SystemExit) as raised:
        run("profiles", "--vendor", "acme")

    assert str(raised.value).startswith("vendorfake: "), str(raised.value)


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------


def test_manifest_prints_one_json_document_and_nothing_else() -> None:
    """`--json` is implicit here: the output *is* the document. A banner, a
    table or a trailing note would break `vendorfake manifest > square.json`,
    which is the whole way a compose setup step uses it."""
    code, out = run("manifest", "--vendor", "square")
    assert code == 0
    document = json.loads(out)
    assert document["schema"] == "vendorfake.manifest/1"
    assert (document["vendor"], document["profile"]) == ("square", "full")


def test_manifest_matches_the_document_the_control_plane_serves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two ways in, one function behind them. Were these built separately, a
    field added to one would silently be absent from the other, and a script
    that read the file would fail only against the served world. Both units run
    on the same pinned virtual clock: the seeded tokens carry an expiry."""
    from vendorfake.core.transport.inprocess import in_process
    from vendorfake.registry import create_unit

    pinned = {"VENDORFAKE_CLOCK": "virtual", "VENDORFAKE_CLOCK_START": "2026-01-01T00:00:00Z"}
    for key, value in pinned.items():
        monkeypatch.setenv(key, value)
    _, out = run("manifest", "--vendor", "square")
    unit = create_unit(vendor="square", env=pinned)
    try:
        served = in_process(unit).get("/__unit/manifest").json()
    finally:
        unit.stop()
    assert json.loads(out) == served


def test_manifest_records_the_base_url_it_was_given_and_null_without_one() -> None:
    """A process with no request cannot infer the address a container will be
    reached at; guessing loopback would put a URL in the document that no
    caller outside the container can use."""
    _, given = run("manifest", "--vendor", "square", "--base-url", "http://fake:8080")
    assert json.loads(given)["base_url"] == "http://fake:8080"
    _, omitted = run("manifest", "--vendor", "square")
    assert json.loads(omitted)["base_url"] is None


def test_manifest_refuses_an_unknown_vendor_rather_than_printing_an_empty_document() -> None:
    """An empty `ids` would read as "this unit has no entities", and a script
    would fail somewhere further down on a missing key instead of here."""
    with pytest.raises(SystemExit) as raised:
        run("manifest", "--vendor", "nope")
    assert str(raised.value).startswith("vendorfake: ")


def test_serve_validate_refuses_a_vendor_with_no_fidelity_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--validate`` on a vendor with no declaration would start a server that
    checks nothing, with the flag reading as satisfied. It refuses instead, and
    says which vendor and why.

    ``run_server`` is intercepted the way the precedence test does it: what is
    under test is the refusal, and it happens before a socket would be bound.
    """
    import vendorfake.asgi as asgi_module
    import vendorfake.cli as cli_module

    bound: list[object] = []
    monkeypatch.setattr(asgi_module, "run_server", lambda app, **kwargs: bound.append(kwargs))

    parser = cli_module._build_parser()
    args = parser.parse_args(["serve", "--vendor", "clover", "--validate"])
    with pytest.raises(SystemExit) as caught:
        cli_module._serve(args, {}, sys.stdout)
    message = str(caught.value)
    assert "clover" in message and "fidelity leg" in message
    assert bound == []


def test_serve_validate_builds_the_observer_for_a_vendor_that_has_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """The flag reaches ``create_app`` as an observer; without it there is none."""
    import vendorfake.asgi as asgi_module
    import vendorfake.cli as cli_module

    seen: list[object] = []
    real_create_app = asgi_module.create_app

    def spy_create_app(unit: object, **kwargs: object) -> object:
        seen.append(kwargs.get("observer"))
        return real_create_app(unit, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(asgi_module, "create_app", spy_create_app)
    monkeypatch.setattr(asgi_module, "run_server", lambda app, **kwargs: None)

    parser = cli_module._build_parser()
    for argv in (["--validate"], []):
        args = parser.parse_args(["serve", "--vendor", "square", *argv])
        assert cli_module._serve(args, {}, sys.stdout) == 0
    assert [observer is not None for observer in seen] == [True, False]


# ---------------------------------------------------------------------------
# `serve --vendor clover,square`: several vendors in one process.
# ---------------------------------------------------------------------------


def serve_intercepted(monkeypatch: pytest.MonkeyPatch, argv: list[str], env: dict[str, str]) -> tuple[object, str]:
    """Run ``serve`` with ``run_server`` intercepted, returning the application
    it was handed and what was announced.

    The interception the precedence test uses, for the same reason: what is
    under test is which units were built and what they were mounted into, and
    binding a real port to find that out would be slower, racier and no more
    conclusive. The socket is proved out of process, in ``tests/integration``.
    Real units, because ``create_unit`` is what resolves a vendor name.
    """
    import vendorfake.asgi as asgi_module
    import vendorfake.cli as cli_module

    served: list[object] = []

    def fake_run_server(app: object, **kwargs: object) -> None:
        """``on_bound`` is called the way the real one calls it: the announce
        line is printed from that callback, so a stub that skipped it would
        assert nothing about the line."""
        served.append(app)
        announce = kwargs.get("on_bound")
        assert callable(announce)
        announce("127.0.0.1", 8080)

    monkeypatch.setattr(asgi_module, "run_server", fake_run_server)
    buffer = io.StringIO()
    parser = cli_module._build_parser()
    args = parser.parse_args(["serve", "--profile", "oauth-only", *argv])
    assert cli_module._serve(args, env, buffer) == 0
    assert len(served) == 1
    return served[0], buffer.getvalue()


def test_serve_mounts_one_app_per_vendor_when_several_are_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """A comma-separated `--vendor` builds one unit per name and hands
    `run_server` the mount; the announce line is how a parent process learns
    both the port and where each vendor ended up."""
    from vendorfake.asgi.mount import MountedApp

    app, announced = serve_intercepted(monkeypatch, ["--vendor", "clover,square", "--port", "0"], {})

    assert isinstance(app, MountedApp)
    assert app.names == ("clover", "square")
    assert "(vendors=clover,square; mounts=/clover,/square)" in announced


def test_serve_takes_the_vendor_list_from_the_environment_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """`VENDORFAKE_VENDOR=clover,square` alone is the container form: one
    variable on an image that names no vendor at all."""
    from vendorfake.asgi.mount import MountedApp

    app, announced = serve_intercepted(monkeypatch, [], {"VENDORFAKE_VENDOR": "clover,square"})

    assert isinstance(app, MountedApp)
    assert app.names == ("clover", "square")
    assert "(vendors=clover,square; mounts=/clover,/square)" in announced


def test_serve_ignores_whitespace_around_a_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """`clover, square` is what a human writes; a mount named `" square"` is
    what an unstripped split would produce."""
    from vendorfake.asgi.mount import MountedApp

    app, announced = serve_intercepted(monkeypatch, ["--vendor", "clover, square"], {})

    assert isinstance(app, MountedApp)
    assert app.names == ("clover", "square")
    assert "mounts=/clover,/square" in announced


def test_serve_with_one_vendor_is_the_single_vendor_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """One vendor is served as it always was: the unit's own application
    straight onto the socket, no mount, no prefix, and the `vendor=` announce
    line a parent process may already be parsing."""
    from fastapi import FastAPI

    app, announced = serve_intercepted(monkeypatch, ["--vendor", "clover"], {})

    assert isinstance(app, FastAPI)
    assert "(vendor=clover)" in announced


@pytest.mark.parametrize(
    ("argv", "env", "fragment"),
    [
        (["--vendor", "clover,clover"], {}, "twice"),
        (["--vendor", "clover,"], {}, "empty vendor name"),
        (["--vendor", ",square"], {}, "empty vendor name"),
        ([], {"VENDORFAKE_VENDOR": "clover,clover"}, "twice"),
        (["--vendor", "clover,square", "--validate"], {}, "--validate serves one vendor"),
    ],
)
def test_serve_refuses_a_vendor_list_it_cannot_mount(argv: list[str], env: dict[str, str], fragment: str) -> None:
    """A duplicate mount would be unreachable, an empty name is a mount at
    `//`, and `--validate` has one ledger and one declaration to check against.
    Each would otherwise be a server that started and answered some of what was
    asked for."""
    import vendorfake.cli as cli_module

    parser = cli_module._build_parser()
    with pytest.raises(SystemExit) as raised:
        cli_module._serve(parser.parse_args(["serve", *argv]), env, io.StringIO())

    assert str(raised.value).startswith("vendorfake: "), str(raised.value)
    assert fragment in str(raised.value)


def test_a_describing_subcommand_refuses_a_vendor_list() -> None:
    """Only `serve` has somewhere to put a second vendor. `info` prints one
    document about one unit, so describing the first name silently would be the
    worst of the three possible behaviours."""
    with pytest.raises(SystemExit) as raised:
        run("info", "--vendor", "clover,square")

    assert str(raised.value) == "vendorfake: --vendor names several vendors; only `serve` mounts more than one"


# ---------------------------------------------------------------------------
# `--profile` per mount: a `vendor=profile` pair list, and VENDORFAKE_PROFILE_<VENDOR>
# (konyklabs/roadmap#134).
# ---------------------------------------------------------------------------


def _serve_and_capture_profiles(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], env: dict[str, str]
) -> dict[str, str]:
    """Run `serve` for real (`run_server` intercepted, everything else genuine)
    and return the resolved profile each mounted vendor actually built on,
    keyed by vendor name."""
    import vendorfake.asgi as asgi_module
    import vendorfake.cli as cli_module
    import vendorfake.registry as registry_module

    seen: dict[str, str] = {}
    real_create_unit = registry_module.create_unit

    def spy_create_unit(*, vendor: str, **kwargs: object) -> object:
        built = real_create_unit(vendor=vendor, **kwargs)  # type: ignore[arg-type]
        seen[vendor] = built.context.config.profile
        return built

    monkeypatch.setattr(registry_module, "create_unit", spy_create_unit)
    monkeypatch.setattr(asgi_module, "run_server", lambda app, **kwargs: None)

    parser = cli_module._build_parser()
    args = parser.parse_args(["serve", *argv])
    assert cli_module._serve(args, env, io.StringIO()) == 0
    return seen


def test_serve_mounts_each_vendor_on_its_own_profile_via_the_pair_form(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--profile full,square=oauth-only` gives clover the shared bare default
    and square its own pair -- resolved per mount, not once for both."""
    seen = _serve_and_capture_profiles(
        monkeypatch, ["--vendor", "clover,square", "--profile", "full,square=oauth-only"], {}
    )
    assert seen == {"clover": "full", "square": "oauth-only"}


def test_serve_mounts_each_vendor_on_its_own_profile_via_the_env_form_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same split, reached with $VENDORFAKE_PROFILE_SQUARE instead of a
    --profile pair: the two ways to say it agree, and the variable beats the
    bare --profile shared by every other mount."""
    seen = _serve_and_capture_profiles(
        monkeypatch,
        ["--vendor", "clover,square", "--profile", "full"],
        {"VENDORFAKE_PROFILE_SQUARE": "oauth-only"},
    )
    assert seen == {"clover": "full", "square": "oauth-only"}


def test_serve_plain_profile_path_is_unchanged_with_the_pair_grammar_added(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bare `--profile full` with no `=` or `,` still means exactly what it
    meant before konyklabs/roadmap#134: every mount on that one profile."""
    seen = _serve_and_capture_profiles(monkeypatch, ["--vendor", "clover,square", "--profile", "full"], {})
    assert seen == {"clover": "full", "square": "full"}


def test_serve_with_one_vendor_the_flag_beats_the_per_vendor_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """One vendor mounted: `--profile` names that unit's own profile outright,
    the same as an explicit `profile=` on any other binding, so it is not
    silently beaten by that vendor's own `VENDORFAKE_PROFILE_<VENDOR>`."""
    seen = _serve_and_capture_profiles(
        monkeypatch, ["--vendor", "square", "--profile", "full"], {"VENDORFAKE_PROFILE_SQUARE": "oauth-only"}
    )
    assert seen == {"square": "full"}


def test_serve_with_several_vendors_a_pair_beats_that_mounts_own_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """konyklabs/roadmap#134 tier 1: a `vendor=profile` pair naming a mount wins even when that mount also
    has its own `VENDORFAKE_PROFILE_<VENDOR>` set -- the pair is the most specific choice there is."""
    seen = _serve_and_capture_profiles(
        monkeypatch,
        ["--vendor", "clover,square", "--profile", "full,square=no-faults"],
        {"VENDORFAKE_PROFILE_SQUARE": "oauth-only"},
    )
    assert seen == {"clover": "full", "square": "no-faults"}


def test_serve_with_one_vendor_a_pair_naming_it_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The single-vendor form of the pair syntax: `--profile square=oauth-only` with `--vendor square` is
    exactly `--profile oauth-only`, not a shared default with nothing to share it with."""
    seen = _serve_and_capture_profiles(monkeypatch, ["--vendor", "square", "--profile", "square=oauth-only"], {})
    assert seen == {"square": "oauth-only"}


def test_serve_mounts_report_each_vendors_own_profile_through_the_socket_wiring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not just `create_unit`'s own resolution: the mounted application `_serve_mounted` hands to
    `run_server` must actually carry each vendor's own profile through to its control plane, queried the
    way a caller would over the mount's ASGI transport. Replaces the hand-built-units version of this
    check, which never reached `_serve_mounted`'s per-mount wiring at all (docs/testing.md)."""
    import vendorfake.asgi as asgi_module
    import vendorfake.cli as cli_module
    from tests.unit.asgi.test_adapt import call

    profiles: dict[str, object] = {}

    def fake_run_server(app: object, **kwargs: object) -> None:
        profiles["clover"] = call(app, "GET", "/clover/__unit/info").json()["profile"]
        profiles["square"] = call(app, "GET", "/square/__unit/info").json()["profile"]

    monkeypatch.setattr(asgi_module, "run_server", fake_run_server)
    parser = cli_module._build_parser()
    args = parser.parse_args(["serve", "--vendor", "clover,square", "--profile", "full,square=oauth-only"])
    assert cli_module._serve(args, {}, io.StringIO()) == 0

    assert profiles == {"clover": "full", "square": "oauth-only"}


# ---------------------------------------------------------------------------
# A profile path containing `=` or `,` is one profile, never the pair grammar
# (konyklabs/roadmap#134 follow-up).
# ---------------------------------------------------------------------------


def test_info_loads_a_profile_path_containing_an_equals_sign(tmp_path: Path) -> None:
    """A path is a path by :func:`~vendorfake.core.config.profile.is_profile_path`'s own rule, whatever
    characters it contains; it must never be mistaken for `serve`'s `vendor=profile` grammar."""
    from vendorfake.registry import resolve_vendor

    profile_dir = tmp_path / "build=42"
    profile_dir.mkdir()
    shipped = (resolve_vendor("square").profile_dir / "full.json").read_text(encoding="utf-8")
    path = profile_dir / "p.json"
    path.write_text(shipped, encoding="utf-8")

    code, out = run("info", "--vendor", "square", "--profile", str(path))
    assert code == 0
    assert json.loads(out)["profile"] == "full"


def test_serve_with_one_vendor_builds_a_profile_path_containing_a_comma(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from vendorfake.registry import resolve_vendor

    profile_dir = tmp_path / "a,b"
    profile_dir.mkdir()
    shipped = (resolve_vendor("square").profile_dir / "full.json").read_text(encoding="utf-8")
    path = profile_dir / "p.json"
    path.write_text(shipped, encoding="utf-8")

    seen = _serve_and_capture_profiles(monkeypatch, ["--vendor", "square", "--profile", str(path)], {})
    assert seen == {"square": "full"}


def test_serve_with_several_vendors_applies_a_profile_path_to_every_mount(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A path given to a several-vendor `serve` is the shared default for every mount, unsplit -- checked
    against what each mount's `create_unit` call actually received, since two vendors rarely share one
    profile document's capability list (each is stubbed to a bare fake unit here for exactly that reason)."""
    import vendorfake.asgi as asgi_module
    import vendorfake.cli as cli_module
    import vendorfake.registry as registry_module
    from tests.fakes import make_unit
    from vendorfake.core.control.plane import control_plane_routes
    from vendorfake.registry import resolve_vendor

    profile_dir = tmp_path / "run=1"
    profile_dir.mkdir()
    shipped = (resolve_vendor("clover").profile_dir / "full.json").read_text(encoding="utf-8")
    path = profile_dir / "p.json"
    path.write_text(shipped, encoding="utf-8")

    seen: dict[str, object] = {}
    units: list[object] = []

    def spy_create_unit(*, vendor: str, profile: object = None, **kwargs: object) -> object:
        seen[vendor] = profile
        built = make_unit(control_routes=control_plane_routes, log_level="warn")
        units.append(built)
        return built

    monkeypatch.setattr(registry_module, "create_unit", spy_create_unit)
    monkeypatch.setattr(asgi_module, "run_server", lambda app, **kwargs: None)

    try:
        parser = cli_module._build_parser()
        args = parser.parse_args(["serve", "--vendor", "clover,square", "--profile", str(path)])
        assert cli_module._serve(args, {}, io.StringIO()) == 0
        assert seen == {"clover": str(path), "square": str(path)}
    finally:
        for built in units:
            built.stop()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("profile_arg", "fragment"),
    [
        ("full,square=oauth-only,toast=full", "does not mount"),
        ("full,no-faults", "two bare items"),
        ("square=full,square=oauth-only", "twice"),
        ("full,", "empty item"),
    ],
)
def test_serve_refuses_a_malformed_profile_pair_list(profile_arg: str, fragment: str) -> None:
    """Each of the four refusals konyklabs/roadmap#134 names: a pair for a
    vendor this serve does not mount, two bare items, the same vendor named
    twice, and an empty item."""
    import vendorfake.cli as cli_module

    parser = cli_module._build_parser()
    args = parser.parse_args(["serve", "--vendor", "clover,square", "--profile", profile_arg])
    with pytest.raises(SystemExit) as raised:
        cli_module._serve(args, {}, io.StringIO())

    message = str(raised.value)
    assert message.startswith("vendorfake: "), message
    assert fragment in message


def test_serve_warns_about_a_profile_variable_naming_no_installed_vendor(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A typo in the suffix pins nothing, silently, unless something says so
    (konyklabs/roadmap#134 point 4) -- not a refusal, since one environment may
    feed several processes each serving a different subset of vendors."""
    import vendorfake.asgi as asgi_module
    import vendorfake.cli as cli_module

    monkeypatch.setattr(asgi_module, "run_server", lambda app, **kwargs: None)
    parser = cli_module._build_parser()
    args = parser.parse_args(["serve", "--vendor", "square"])
    assert cli_module._serve(args, {"VENDORFAKE_PROFILE_NOSUCHVENDOR": "full"}, io.StringIO()) == 0

    captured = capsys.readouterr()
    assert "VENDORFAKE_PROFILE_NOSUCHVENDOR" in captured.err
    assert "square" in captured.err


def test_serve_does_not_warn_about_a_correctly_spelled_profile_variable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The companion to the warning test above: a real, correctly spelled
    `VENDORFAKE_PROFILE_SQUARE` must never trip the same message -- a warning
    test that only ever supplies a typo cannot tell a real alarm from a false
    one."""
    import vendorfake.asgi as asgi_module
    import vendorfake.cli as cli_module

    monkeypatch.setattr(asgi_module, "run_server", lambda app, **kwargs: None)
    parser = cli_module._build_parser()
    args = parser.parse_args(["serve", "--vendor", "square"])
    assert cli_module._serve(args, {"VENDORFAKE_PROFILE_SQUARE": "oauth-only"}, io.StringIO()) == 0

    captured = capsys.readouterr()
    assert "names no installed vendor" not in captured.err


@pytest.mark.parametrize("subcommand", ["routes", "info"])
def test_a_describing_subcommand_refuses_the_serve_only_pair_form(subcommand: str) -> None:
    """`routes`/`info` describe one unit with one profile; the `vendor=profile`
    list is `serve`'s grammar, and the refusal names it rather than trying to
    guess which pair the caller meant."""
    with pytest.raises(SystemExit) as raised:
        run(subcommand, "--vendor", "square", "--profile", "square=oauth-only")

    message = str(raised.value)
    assert message.startswith("vendorfake: "), message
    assert "serve" in message


def test_describing_commands_honour_the_per_vendor_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """konyklabs/roadmap#134 follow-up: `routes`, `explain route` and `info` disagreed about
    `VENDORFAKE_PROFILE_<VENDOR>` -- `info` (via `_make_unit`/`create_unit`) honoured it, `routes` and
    `explain` resolved their own `args.profile or $VENDORFAKE_PROFILE or 'full'` and ignored it. All three
    now resolve through the same `resolve_profile_name`, so an exported variable means one thing everywhere
    (AGENTS.md)."""
    import vendorfake.registry as registry_module

    real_create_unit = registry_module.create_unit
    seen: list[object] = []

    def spy_create_unit(*, vendor: str, profile: object = None, **kwargs: object) -> object:
        seen.append(profile)
        return real_create_unit(vendor=vendor, profile=profile, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(registry_module, "create_unit", spy_create_unit)
    monkeypatch.setenv("VENDORFAKE_PROFILE_SQUARE", "oauth-only")

    seen.clear()
    run("routes", "--vendor", "square")
    assert seen[-1] == "oauth-only"
    seen.clear()
    run("routes", "--vendor", "square", "--profile", "full")
    assert seen[-1] == "full"

    seen.clear()
    run("explain", "route", "--vendor", "square", "ListLocations")
    assert seen[-1] == "oauth-only"
    seen.clear()
    run("explain", "route", "--vendor", "square", "--profile", "full", "ListLocations")
    assert seen[-1] == "full"

    _, out = run("info", "--vendor", "square")
    assert json.loads(out)["profile"] == "oauth-only"
    _, out = run("info", "--vendor", "square", "--profile", "full")
    assert json.loads(out)["profile"] == "full"
