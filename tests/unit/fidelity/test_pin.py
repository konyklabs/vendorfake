"""``refresh`` and the pin, with bytes in hand and no network.

Every test drives ``refresh`` through an injected fetcher over the synthetic
document from ``test_extract``; the assertions are on what lands on disk and
on the three fields of ``RefreshResult``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.unit.fidelity.test_extract import MODELED, SOURCE, URL, blob, synthetic
from vendorfake.fidelity.extract import cut_digests, cut_extract, render_json
from vendorfake.fidelity.pin import Pin, PinnedSource, fetch, read_pin, refresh, verify, write_pin
from vendorfake.fidelity.types import EXTRACT_FILE, PIN_FILE, FidelityDeclaration, SpecSource

DECLARATION = FidelityDeclaration(
    anchor="tests.synthetic", sources=(SpecSource(kind="openapi3", url=URL),), stubs_accepted=("Missing",)
)


def fetcher_for(document: dict[str, Any]) -> Any:
    data = blob(document)
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return data

    fetcher.calls = calls  # type: ignore[attr-defined]
    return fetcher


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def pinned(tmp_path: Path) -> Path:
    """A directory that already holds a refreshed extract and pin."""
    result = refresh(tmp_path, DECLARATION, MODELED, fetcher=fetcher_for(synthetic()), fetched="2026-09-02")
    assert result.changed_upstream and result.changed_extract
    return tmp_path


def test_pin_round_trips_through_write_and_read(tmp_path: Path) -> None:
    pin = Pin(
        sources=(PinnedSource(url=URL, sha256="ab" * 32, bytes=12, version="1.0", fetched="2026-09-02"),),
        extract_sha256="cd" * 32,
    )
    write_pin(tmp_path / PIN_FILE, pin)
    assert read_pin(tmp_path / PIN_FILE) == pin
    text = (tmp_path / PIN_FILE).read_text()
    assert text.endswith("\n")
    assert json.loads(text)["schema"] == 1


def test_a_pin_with_the_wrong_schema_is_refused(tmp_path: Path) -> None:
    (tmp_path / PIN_FILE).write_text('{"schema": 2, "sources": [], "extract_sha256": ""}')
    with pytest.raises(ValueError, match='"schema": 1'):
        read_pin(tmp_path / PIN_FILE)


def test_fetch_uses_the_injected_fetcher_and_returns_its_bytes() -> None:
    fetcher = fetcher_for(synthetic())
    assert fetch(SpecSource(kind="openapi3", url=URL), fetcher=fetcher) == blob(synthetic())
    assert fetcher.calls == [URL]


def test_first_refresh_writes_both_files_and_the_pin_digests_the_extract(tmp_path: Path) -> None:
    fetcher = fetcher_for(synthetic())
    result = refresh(tmp_path, DECLARATION, MODELED, fetcher=fetcher, fetched="2026-09-02")
    assert fetcher.calls == [URL]
    assert result.changed_upstream is True
    assert result.changed_extract is True
    assert "new pin" in result.diff_summary
    assert f"{EXTRACT_FILE}: new" in result.diff_summary
    pin = read_pin(tmp_path / PIN_FILE)
    assert pin.extract_sha256 == sha(tmp_path / EXTRACT_FILE)
    assert pin.sources == (
        PinnedSource(
            url=URL,
            sha256=hashlib.sha256(blob(synthetic())).hexdigest(),
            bytes=len(blob(synthetic())),
            version="2.3.4",
            fetched="2026-09-02",
        ),
    )
    extract = json.loads((tmp_path / EXTRACT_FILE).read_text())
    assert extract["x-vendorfake"]["sources"] == [{**pin.sources[0].to_json(), "label": "spec"}]


def test_unchanged_upstream_on_a_later_day_is_byte_identical_and_keeps_the_pinned_date(pinned: Path) -> None:
    before = ((pinned / EXTRACT_FILE).read_bytes(), (pinned / PIN_FILE).read_bytes())
    result = refresh(pinned, DECLARATION, MODELED, fetcher=fetcher_for(synthetic()), fetched="2026-12-25")
    assert result.changed_upstream is False
    assert result.changed_extract is False
    assert result.changed is False
    assert "unchanged" in result.diff_summary
    assert ((pinned / EXTRACT_FILE).read_bytes(), (pinned / PIN_FILE).read_bytes()) == before
    assert read_pin(pinned / PIN_FILE).sources[0].fetched == "2026-09-02"


def prose_edited() -> dict[str, Any]:
    document = synthetic()
    document["info"]["description"] = "prose, edited"  # stripped: the cut does not change
    return document


def test_check_detects_a_changed_upstream_byte_and_writes_nothing(pinned: Path) -> None:
    """A byte-only move is a re-pin chore, not a change (konyklabs/roadmap#178):
    the deliberate contract change -- ``changed_upstream`` used to be true here."""
    before = ((pinned / EXTRACT_FILE).read_bytes(), (pinned / PIN_FILE).read_bytes())
    result = refresh(
        pinned, DECLARATION, MODELED, fetcher=fetcher_for(prose_edited()), fetched="2026-09-03", check=True
    )
    assert result.changed_upstream is False
    assert result.changed_extract is False
    assert result.moved == (URL,)
    assert result.changed is False
    assert "changed sha256" in result.diff_summary
    assert "cut; the source rows moved" in result.diff_summary
    assert "check mode: nothing written" in result.diff_summary
    assert ((pinned / EXTRACT_FILE).read_bytes(), (pinned / PIN_FILE).read_bytes()) == before


def test_a_version_only_bump_is_a_move_not_a_cut_change(pinned: Path) -> None:
    document = synthetic()
    document["info"]["version"] = "2.4.0"
    result = refresh(pinned, DECLARATION, MODELED, fetcher=fetcher_for(document), fetched="2026-09-03", check=True)
    assert result.changed_extract is False
    assert result.moved == (URL,)


def test_writing_a_move_repins_and_is_never_called_a_hand_edit(pinned: Path) -> None:
    document = prose_edited()
    result = refresh(pinned, DECLARATION, MODELED, fetcher=fetcher_for(document), fetched="2026-09-03")
    pin = read_pin(pinned / PIN_FILE)
    assert pin.sources[0].sha256 == hashlib.sha256(blob(document)).hexdigest()
    assert pin.sources[0].fetched == "2026-09-03"
    assert pin.extract_sha256 == sha(pinned / EXTRACT_FILE)
    assert "edited by hand" not in result.diff_summary
    assert "wrote" in result.diff_summary
    again = refresh(pinned, DECLARATION, MODELED, fetcher=fetcher_for(document), fetched="2026-09-04")
    assert not again.changed and again.moved == ()


def test_a_moved_cut_folds_the_move_into_changed_upstream(pinned: Path) -> None:
    document = synthetic()
    document["components"]["schemas"]["Money"]["properties"]["amount"]["type"] = "string"
    result = refresh(pinned, DECLARATION, MODELED, fetcher=fetcher_for(document), fetched="2026-09-03", check=True)
    assert result.changed_upstream and result.changed_extract
    assert result.moved == ()
    assert f"{EXTRACT_FILE}: schema ~ Money" in result.diff_summary


def test_check_detects_a_changed_extract_and_names_the_schema(pinned: Path) -> None:
    document = synthetic()
    document["components"]["schemas"]["Money"]["properties"]["amount"]["type"] = "string"
    result = refresh(pinned, DECLARATION, MODELED, fetcher=fetcher_for(document), fetched="2026-09-03", check=True)
    assert result.changed_upstream is True
    assert result.changed_extract is True
    assert f"{EXTRACT_FILE}: schema ~ Money" in result.diff_summary
    assert "lines)" in result.diff_summary


def test_a_changed_modeled_list_changes_the_extract_without_touching_the_upstream(pinned: Path) -> None:
    fewer = [pair for pair in MODELED if pair[0] != "GET"]
    result = refresh(pinned, DECLARATION, fewer, fetcher=fetcher_for(synthetic()), fetched="2026-09-03")
    assert result.changed_upstream is False
    assert result.changed_extract is True
    assert f"{EXTRACT_FILE}: modeled - GET /v1/widgets/{{widget_id}}" in result.diff_summary
    assert f"{EXTRACT_FILE}: schema - Audit" in result.diff_summary
    # Written, since not a check: the pin now digests the new extract and keeps the pinned date.
    pin = read_pin(pinned / PIN_FILE)
    assert pin.extract_sha256 == sha(pinned / EXTRACT_FILE)
    assert pin.sources[0].fetched == "2026-09-02"


def test_a_hand_edited_extract_is_reported_as_changed(pinned: Path) -> None:
    path = pinned / EXTRACT_FILE
    path.write_text(path.read_text().replace('"minimum": 0', '"minimum": 1'))
    result = refresh(pinned, DECLARATION, MODELED, fetcher=fetcher_for(synthetic()), fetched="2026-09-03", check=True)
    assert result.changed_upstream is False
    assert result.changed_extract is True
    assert "edited by hand" in result.diff_summary


def test_check_on_an_empty_directory_writes_nothing(tmp_path: Path) -> None:
    result = refresh(tmp_path, DECLARATION, MODELED, fetcher=fetcher_for(synthetic()), fetched="2026-09-02", check=True)
    assert result.changed is True
    assert not (tmp_path / EXTRACT_FILE).exists()
    assert not (tmp_path / PIN_FILE).exists()


# -- verify: the offline half ----------------------------------------------


def test_verify_is_clean_after_a_refresh_and_never_fetches(pinned: Path) -> None:
    result = verify(pinned, DECLARATION)
    assert not result.changed
    assert "offline; not re-fetched" in result.diff_summary
    assert "matches pin.json" in result.diff_summary


def test_verify_reports_a_hand_edited_extract(pinned: Path) -> None:
    extract = pinned / EXTRACT_FILE
    extract.write_text(extract.read_text().replace('"openapi": "3.0.0"', '"openapi": "3.0.1"'))
    result = verify(pinned, DECLARATION)
    assert result.changed_extract and not result.changed_upstream
    assert "edited by hand?" in result.diff_summary


def test_verify_reports_a_source_the_declaration_and_pin_disagree_on(pinned: Path) -> None:
    other = replace(DECLARATION, sources=(SpecSource(kind="openapi3", url="https://example.test/other.json"),))
    result = verify(pinned, other)
    assert result.changed_upstream and not result.changed_extract
    assert "declared source not pinned: https://example.test/other.json" in result.diff_summary
    assert f"pinned source no longer declared: {URL}" in result.diff_summary


def test_verify_names_missing_files(tmp_path: Path) -> None:
    result = verify(tmp_path, DECLARATION)
    assert result.changed
    assert "extract.json, pin.json" in result.diff_summary


def test_verify_refuses_a_stub_the_declaration_has_not_accepted(pinned: Path) -> None:
    """A stubbed schema validates everything it types (deep-lens D4,
    konyklabs/roadmap#55): a new one is red offline until it is accepted by name."""
    from vendorfake.fidelity.extract import render_json

    extract = pinned / EXTRACT_FILE
    doc = json.loads(extract.read_text())
    assert doc["x-vendorfake"]["stubbed"] == ["Missing"]
    # An upstream release dangles a second schema; `pin` re-cuts and re-pins.
    doc["x-vendorfake"]["stubbed"] = ["Missing", "Money"]
    text = render_json(doc)
    extract.write_text(text)
    write_pin(pinned / PIN_FILE, Pin.from_extract(doc, text))
    result = verify(pinned, DECLARATION)
    assert result.changed_extract and not result.changed_upstream
    assert "schema 'Money' is stubbed to {}" in result.diff_summary
    assert "Missing" not in result.diff_summary
    assert not verify(pinned, replace(DECLARATION, stubs_accepted=("Missing", "Money"))).changed


# -- verify: the non-vendored form (konyklabs/roadmap#56) ---------------------


NOT_VENDORED = replace(DECLARATION, vendored=False)


def test_verify_of_a_non_vendored_declaration_with_no_cache_passes_with_a_note(tmp_path: Path) -> None:
    """Offline cannot fetch, and the design accepts that: an empty cache is
    not an inconsistency, it is nothing to verify."""
    package = tmp_path / "pkg"
    package.mkdir()
    refresh(
        package, NOT_VENDORED, MODELED, fetcher=fetcher_for(synthetic()), fetched="2026-09-02", cache_dir=tmp_path / "c"
    )
    assert not (package / EXTRACT_FILE).exists()
    result = verify(package, NOT_VENDORED, cache_dir=tmp_path / "empty")
    # Nothing checked is not a pass (adversarial A6, konyklabs/roadmap#56).
    assert result.changed
    assert "no cache" in result.diff_summary and "cannot be verified offline" in result.diff_summary
    assert "fetch" in result.diff_summary


def audited() -> dict[str, Any]:
    """A cut change only ``GET /v1/widgets/{widget_id}`` reaches (through ``Audit``)."""
    document = synthetic()
    document["components"]["schemas"]["Audit"]["properties"]["at"] = {"type": "string"}
    return document


def test_verify_of_a_non_vendored_cache_cut_from_moved_bytes(tmp_path: Path) -> None:
    from vendorfake.fidelity.cache import cache_path

    package = tmp_path / "pkg"
    package.mkdir()
    cache = tmp_path / "c"
    refresh(package, NOT_VENDORED, MODELED, fetcher=fetcher_for(synthetic()), fetched="2026-09-02", cache_dir=cache)
    result = verify(package, NOT_VENDORED, cache_dir=cache)
    assert not result.changed
    cached = cache_path(NOT_VENDORED.anchor, cache) / EXTRACT_FILE
    assert f"matches {PIN_FILE} (cached at {cached})" in result.diff_summary
    # A cache cut at run time from moved bytes whose cut is the pinned one: a chore, not a finding.
    cached.write_text(render_json(cut_extract([(SOURCE, blob(prose_edited()))], MODELED, fetched="2026-12-25")))
    result = verify(package, NOT_VENDORED, cache_dir=cache)
    assert not result.changed
    assert result.moved == (URL,)
    assert f"upstream {URL}: moved (pinned " in result.diff_summary
    assert "-- cut unchanged" in result.diff_summary
    # A moved cut is a finding naming the operation.
    cached.write_text(render_json(cut_extract([(SOURCE, blob(audited()))], MODELED, fetched="2026-12-25")))
    result = verify(package, NOT_VENDORED, cache_dir=cache)
    assert result.changed_extract and result.changed_upstream
    assert result.moved == ()
    assert f"{EXTRACT_FILE}: operation ~ GET /v1/widgets/{{widget_id}}" in result.diff_summary
    # A pin with no cut (pinned before #178) and a cache that does not digest to it.
    write_pin(package / PIN_FILE, replace(read_pin(package / PIN_FILE), cut_sha256="", operations=()))
    cached.write_text(render_json(cut_extract([(SOURCE, blob(prose_edited()))], MODELED, fetched="2026-12-25")))
    result = verify(package, NOT_VENDORED, cache_dir=cache)
    assert result.changed
    assert "records no cut digest" in result.diff_summary


def test_verify_of_a_non_vendored_declaration_needs_the_pin_only(tmp_path: Path) -> None:
    result = verify(tmp_path, NOT_VENDORED, cache_dir=tmp_path / "c")
    assert result.changed
    assert f"missing under {tmp_path}: {PIN_FILE} -- run `pin` once" == result.diff_summary


def test_a_vendored_pin_carries_no_modeled_list_and_a_non_vendored_one_does(pinned: Path, tmp_path: Path) -> None:
    """Square's committed pin must stay byte-identical: ``modeled`` is written only where the cache needs it."""
    from vendorfake.fidelity.cache import cache_path

    vendored = json.loads((pinned / PIN_FILE).read_text())
    assert "modeled" not in vendored
    assert "cut_sha256" not in vendored and "operations" not in vendored
    assert read_pin(pinned / PIN_FILE).modeled == ()
    package = tmp_path / "nv"
    package.mkdir()
    refresh(
        package, NOT_VENDORED, MODELED, fetcher=fetcher_for(synthetic()), fetched="2026-09-02", cache_dir=tmp_path / "c"
    )
    pin = read_pin(package / PIN_FILE)
    assert pin.modeled == tuple(f"{m} {p}" for m, p in MODELED)
    cache_text = (cache_path(NOT_VENDORED.anchor, tmp_path / "c") / EXTRACT_FILE).read_text()
    whole, operations = cut_digests(json.loads(cache_text))
    assert pin.cut_sha256 == whole
    assert dict(pin.operations) == operations
    assert set(operations) == {"GET /v1/widgets/{widget_id}", "POST /v1/widgets"}
    # A second refresh on an unchanged upstream is byte-identical, modeled included.
    before = (package / PIN_FILE).read_bytes()
    result = refresh(
        package, NOT_VENDORED, MODELED, fetcher=fetcher_for(synthetic()), fetched="2026-12-25", cache_dir=tmp_path / "c"
    )
    assert not result.changed and (package / PIN_FILE).read_bytes() == before


def test_pin_round_trips_its_cut_and_reads_a_pin_without_one(tmp_path: Path) -> None:
    pin = Pin(
        sources=(PinnedSource(url=URL, sha256="ab" * 32, bytes=12, version="1.0", fetched="2026-09-02"),),
        extract_sha256="cd" * 32,
        modeled=("GET /a",),
        cut_sha256="ef" * 32,
        operations=(("GET /a", "01" * 32),),
    )
    write_pin(tmp_path / PIN_FILE, pin)
    assert read_pin(tmp_path / PIN_FILE) == pin
    assert json.loads((tmp_path / PIN_FILE).read_text())["operations"] == {"GET /a": "01" * 32}
    (tmp_path / PIN_FILE).write_text('{"schema": 1, "sources": [], "extract_sha256": "cd"}')
    bare = read_pin(tmp_path / PIN_FILE)
    assert bare.cut_sha256 == "" and bare.operations == ()


def test_a_cold_cache_check_judges_the_cut_from_the_pin(tmp_path: Path) -> None:
    """The weekly drift job's case: no cache on the runner, so the pin alone says what the cut was."""
    package = tmp_path / "pkg"
    package.mkdir()
    refresh(
        package, NOT_VENDORED, MODELED, fetcher=fetcher_for(synthetic()), fetched="2026-09-02", cache_dir=tmp_path / "c"
    )
    cold = tmp_path / "empty"
    result = refresh(
        package,
        NOT_VENDORED,
        MODELED,
        fetcher=fetcher_for(prose_edited()),
        fetched="2026-09-03",
        check=True,
        cache_dir=cold,
    )
    assert result.moved == (URL,)
    assert result.changed_extract is False
    assert f"{EXTRACT_FILE}: new" not in result.diff_summary
    result = refresh(
        package, NOT_VENDORED, MODELED, fetcher=fetcher_for(audited()), fetched="2026-09-03", check=True, cache_dir=cold
    )
    assert result.changed_extract is True
    assert f"{EXTRACT_FILE}: operation ~ GET /v1/widgets/{{widget_id}}" in result.diff_summary
    assert "operation ~ POST /v1/widgets" not in result.diff_summary


def test_a_pre_178_non_vendored_pin_is_changed_once_and_migrated_by_a_write(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    cache = tmp_path / "c"
    refresh(package, NOT_VENDORED, MODELED, fetcher=fetcher_for(synthetic()), fetched="2026-09-02", cache_dir=cache)
    write_pin(package / PIN_FILE, replace(read_pin(package / PIN_FILE), cut_sha256="", operations=()))
    result = refresh(
        package,
        NOT_VENDORED,
        MODELED,
        fetcher=fetcher_for(synthetic()),
        fetched="2026-09-03",
        check=True,
        cache_dir=cache,
    )
    assert result.changed_extract is True
    assert "records no cut digest" in result.diff_summary
    assert "edited by hand" not in result.diff_summary
    refresh(package, NOT_VENDORED, MODELED, fetcher=fetcher_for(synthetic()), fetched="2026-09-03", cache_dir=cache)
    assert read_pin(package / PIN_FILE).cut_sha256 != ""
    clean = refresh(
        package,
        NOT_VENDORED,
        MODELED,
        fetcher=fetcher_for(synthetic()),
        fetched="2026-09-04",
        check=True,
        cache_dir=cache,
    )
    assert not clean.changed and clean.moved == ()


def test_refresh_hands_the_declarations_extension_map_and_error_schema_to_the_cut(tmp_path: Path) -> None:
    """``Unreachable`` is referenced by no modeled operation; it lands in the
    extract only because the declaration names it as the error schema. The
    mapped extension shows the map went through as well."""
    document = synthetic()
    document["components"]["schemas"]["Money"]["properties"]["currency"]["x-nullable"] = True
    declaration = replace(DECLARATION, error_schema="Unreachable", extension_map={"x-nullable": "nullable"})
    refresh(tmp_path, declaration, MODELED, fetcher=fetcher_for(document), fetched="2026-09-02")
    extract = json.loads((tmp_path / EXTRACT_FILE).read_text())
    assert "Unreachable" in extract["components"]["schemas"]
    assert extract["components"]["schemas"]["Money"]["properties"]["currency"] == {"type": "string", "nullable": True}
    assert extract["x-vendorfake"]["rewritten"]["extensions"] == {"x-nullable": 1}


def test_refresh_refuses_a_declared_error_schema_the_upstream_lacks(tmp_path: Path) -> None:
    declaration = replace(DECLARATION, error_schema="NoSuchSchema")
    with pytest.raises(ValueError, match="NoSuchSchema"):
        refresh(tmp_path, declaration, MODELED, fetcher=fetcher_for(synthetic()), fetched="2026-09-02")
    assert not (tmp_path / EXTRACT_FILE).exists()


# -- a source that cannot be fetched: a verdict, never a traceback -----------


OTHER = "https://example.test/moved.yaml"
GONE_AT = "https://example.test/404"


def failing_fetcher(document: dict[str, Any], failing: dict[str, Exception]) -> Any:
    """Serves ``document`` for every URL except those in ``failing``, which raise."""
    data = blob(document)
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        if url in failing:
            raise failing[url]
        return data

    fetcher.calls = calls  # type: ignore[attr-defined]
    return fetcher


def not_found(url: str, *, final: str) -> httpx.HTTPStatusError:
    """What ``raise_for_status`` raises after a redirect from ``url`` landed on a 404 at ``final``."""
    response = httpx.Response(404, request=httpx.Request("GET", final))
    return httpx.HTTPStatusError("404 Not Found", request=response.request, response=response)


def snapshot(directory: Path) -> tuple[bytes, bytes]:
    return (directory / EXTRACT_FILE).read_bytes(), (directory / PIN_FILE).read_bytes()


TWO_SOURCES = replace(
    DECLARATION, sources=(SpecSource(kind="openapi3", url=OTHER), SpecSource(kind="openapi3", url=URL))
)


@pytest.mark.parametrize("check", [True, False], ids=["check", "write"])
def test_a_404_on_one_source_is_gone_the_others_are_still_reported_and_nothing_is_written(
    pinned: Path, check: bool
) -> None:
    before = snapshot(pinned)
    fetcher = failing_fetcher(synthetic(), {OTHER: not_found(OTHER, final=GONE_AT)})
    result = refresh(pinned, TWO_SOURCES, MODELED, fetcher=fetcher, fetched="2026-10-27", check=check)
    # The failing source came first, and the one after it was still fetched.
    assert fetcher.calls == [OTHER, URL]
    assert [failure.url for failure in result.gone] == [OTHER] and result.unreachable == ()
    assert f"upstream {OTHER}: GONE (HTTP 404 at {GONE_AT}; never pinned)" in result.diff_summary
    assert f"upstream {URL}: unchanged (sha256 " in result.diff_summary
    assert "not cut -- 1 source(s) could not be fetched" in result.diff_summary
    assert result.changed_extract is False
    assert snapshot(pinned) == before


def test_a_gone_pinned_source_names_the_last_pin_it_had(pinned: Path) -> None:
    before = snapshot(pinned)
    pin = read_pin(pinned / PIN_FILE).sources[0]
    response = httpx.Response(410, request=httpx.Request("GET", URL))
    gone = httpx.HTTPStatusError("410 Gone", request=response.request, response=response)
    result = refresh(pinned, DECLARATION, MODELED, fetcher=failing_fetcher(synthetic(), {URL: gone}), fetched="x")
    assert [failure.url for failure in result.gone] == [URL]
    # Same URL after redirects: no "at <final>" clause.
    assert (
        f"upstream {URL}: GONE (HTTP 410; pinned sha256 {pin.sha256[:12]}, fetched {pin.fetched})"
        in result.diff_summary
    )
    assert "not written:" in result.diff_summary
    assert snapshot(pinned) == before


def test_a_connection_error_is_unreachable_and_writes_nothing(pinned: Path) -> None:
    before = snapshot(pinned)
    fetcher = failing_fetcher(synthetic(), {OTHER: httpx.ConnectError("[Errno 61] Connection refused")})
    result = refresh(pinned, TWO_SOURCES, MODELED, fetcher=fetcher, fetched="2026-10-27")
    assert fetcher.calls == [OTHER, URL]
    assert [failure.url for failure in result.unreachable] == [OTHER] and result.gone == ()
    assert f"upstream {OTHER}: UNREACHABLE (ConnectError: [Errno 61] Connection refused; never pinned)" in (
        result.diff_summary
    )
    assert f"upstream {URL}: unchanged" in result.diff_summary
    assert snapshot(pinned) == before


@pytest.mark.parametrize("status", [500, 503, 403, 429])
def test_a_5xx_or_a_non_404_4xx_is_unreachable_not_gone(pinned: Path, status: int) -> None:
    response = httpx.Response(status, request=httpx.Request("GET", URL))
    error = httpx.HTTPStatusError(str(status), request=response.request, response=response)
    result = refresh(
        pinned, DECLARATION, MODELED, fetcher=failing_fetcher(synthetic(), {URL: error}), fetched="x", check=True
    )
    assert [failure.state for failure in result.failures] == ["UNREACHABLE"]
    assert f"upstream {URL}: UNREACHABLE (HTTP {status};" in result.diff_summary


def test_a_timeout_and_an_os_error_are_unreachable(pinned: Path) -> None:
    failing = {OTHER: httpx.ReadTimeout("timed out"), URL: ConnectionResetError("reset")}
    result = refresh(
        pinned, TWO_SOURCES, MODELED, fetcher=failing_fetcher(synthetic(), failing), fetched="x", check=True
    )
    assert [failure.url for failure in result.unreachable] == [OTHER, URL]
    assert f"upstream {OTHER}: UNREACHABLE (ReadTimeout: timed out;" in result.diff_summary
    assert f"upstream {URL}: UNREACHABLE (ConnectionResetError: reset;" in result.diff_summary


def test_a_changed_source_beside_a_gone_one_is_still_reported_as_changed(pinned: Path) -> None:
    document = synthetic()
    document["info"]["description"] = "prose, edited"
    fetcher = failing_fetcher(document, {OTHER: not_found(OTHER, final=GONE_AT)})
    result = refresh(pinned, TWO_SOURCES, MODELED, fetcher=fetcher, fetched="2026-10-27", check=True)
    assert result.changed_upstream is True and len(result.gone) == 1
    assert f"upstream {URL}: changed sha256 " in result.diff_summary


# ---------------------------------------------------------------------------
# Webhooks entries (konyklabs/roadmap#185).
# ---------------------------------------------------------------------------


def _hooked(*names: str) -> FidelityDeclaration:
    from vendorfake.fidelity.types import Webhook

    return replace(NOT_VENDORED, webhooks=tuple(Webhook(name=name, reason="r") for name in names))


def test_a_pin_records_its_webhooks_names_only_when_the_declaration_names_some(tmp_path: Path) -> None:
    from tests.unit.fidelity.test_extract import webhooked_document

    plain, hooked = tmp_path / "plain", tmp_path / "hooked"
    plain.mkdir()
    hooked.mkdir()
    fetcher = fetcher_for(webhooked_document())
    refresh(plain, NOT_VENDORED, MODELED, fetcher=fetcher, fetched="2026-09-02", cache_dir=tmp_path / "c1")
    assert "webhooks" not in json.loads((plain / PIN_FILE).read_text())
    declaration = _hooked("widget changed", "nope")
    refresh(hooked, declaration, MODELED, fetcher=fetcher, fetched="2026-09-02", cache_dir=tmp_path / "c2")
    pin = read_pin(hooked / PIN_FILE)
    # Found or not, every declared name scoped the cut, and only the found one has a digest.
    assert pin.webhooks == ("nope", "widget changed")
    assert "WEBHOOK widget changed" in dict(pin.operations)
    assert "WEBHOOK nope" not in dict(pin.operations)
    assert not {key for key, _ in pin.operations if key.startswith("WEBHOOK")} & set(pin.modeled)
    assert verify(hooked, declaration, cache_dir=tmp_path / "c2").changed is False


def test_a_moved_webhooks_entry_is_named_by_the_check(tmp_path: Path) -> None:
    from tests.unit.fidelity.test_extract import webhooked_document

    declaration = _hooked("widget changed")
    package = tmp_path / "pkg"
    package.mkdir()
    refresh(
        package,
        declaration,
        MODELED,
        fetcher=fetcher_for(webhooked_document()),
        fetched="2026-09-02",
        cache_dir=tmp_path / "c",
    )
    moved = webhooked_document()
    moved["components"]["schemas"]["Notice"]["properties"]["reference"]["type"] = "integer"
    result = refresh(
        package,
        declaration,
        MODELED,
        fetcher=fetcher_for(moved),
        fetched="2026-09-03",
        check=True,
        cache_dir=tmp_path / "c",
    )
    assert result.changed_extract is True
    assert result.diff_summary.splitlines()[-2:] == [
        f"{EXTRACT_FILE}: operation ~ WEBHOOK widget changed",
        "check mode: nothing written",
    ]


def test_the_structural_diff_names_a_webhooks_entry_gained_or_lost() -> None:
    from tests.unit.fidelity.test_extract import webhooked_document
    from vendorfake.fidelity.pin import _extract_diff

    old = cut_extract([(SOURCE, blob(webhooked_document()))], MODELED, fetched="2026-09-02")
    new = cut_extract(
        [(SOURCE, blob(webhooked_document()))], MODELED, fetched="2026-09-02", webhooks=["widget changed", "x"]
    )
    lines = _extract_diff(old, new, render_json(old), render_json(new))
    assert f"{EXTRACT_FILE}: webhooks_modeled + widget changed" in lines
    assert f"{EXTRACT_FILE}: webhooks_missing + x" in lines
    assert f"{EXTRACT_FILE}: schema + Notice" in lines


def test_verify_refuses_a_declared_webhooks_entry_the_cut_was_not_scoped_to(tmp_path: Path) -> None:
    from tests.unit.fidelity.test_extract import webhooked_document

    package = tmp_path / "pkg"
    package.mkdir()
    refresh(
        package,
        NOT_VENDORED,
        MODELED,
        fetcher=fetcher_for(webhooked_document()),
        fetched="2026-09-02",
        cache_dir=tmp_path / "c",
    )
    result = verify(package, _hooked("widget changed"), cache_dir=tmp_path / "c")
    assert result.changed_extract is True
    assert (
        f"{EXTRACT_FILE}: webhooks entry 'widget changed' is declared but not in the cut -- run `vendorfake-fidelity pin`"
        in result.diff_summary
    )
