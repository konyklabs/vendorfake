"""Tying the extract to the upstream bytes it was cut from.

FOR: making vendor drift a diff. ``pin.json`` records, per upstream document,
the sha256 of the exact bytes fetched, their length, the document's own
version string and the date they were fetched -- plus the sha256 of the
committed ``extract.json``. ``refresh`` fetches again, cuts again, and reports
whether the upstream changed, whether the extract changed, or both; a pinned
source whose bytes moved while the cut stayed is a re-pin chore, never a change
(konyklabs/roadmap#178); in check mode it writes nothing, so CI can fail on
drift without ever touching the tree.

INVARIANT: **the fetcher is a parameter.** Everything below the default
``fetch`` is testable with bytes in hand; no unit test reaches the network, and
the one real fetch per vendor is a deliberate act with a date attached.

SECOND INVARIANT: **an unchanged upstream refreshes to byte-identical files.**
The ``fetched`` date a caller passes applies only to sources whose bytes
differ from the pinned ones; a source with the same sha256 keeps the date it
was first pinned on, because that is still the date *these bytes* were
obtained. Without this, every check run on a new day would read as drift.

THIRD INVARIANT: **a source that cannot be fetched is a verdict, never a
traceback, and never a pin.** Every declared source is fetched, whatever the
one before it did, and each gets its ``upstream <url>:`` line. One that
answered 404 or 410 (after redirects) is ``GONE`` -- the document the fake was
checked against is no longer published, and the pinned extract is the last
known copy of it. One that could not be reached at all (connection refused,
DNS, TLS, a timeout, a 5xx -- and, by JUDGMENT, any other 4xx such as 401, 403
or 429, which says nothing about whether the document still exists) is
``UNREACHABLE``. Either one means nothing is cut and nothing is written, in
check mode or not: a pin must never record an error page's bytes.
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from vendorfake.fidelity.extract import cut_digests, cut_extract, render_json, sha256_hex
from vendorfake.fidelity.types import EXTRACT_FILE, PIN_FILE, FidelityDeclaration, SpecSource, route_key

__all__ = [
    "GONE",
    "PIN_SCHEMA",
    "UNREACHABLE",
    "Fetcher",
    "Pin",
    "PinnedSource",
    "RefreshResult",
    "SourceFailure",
    "fetch",
    "read_pin",
    "refresh",
    "verify",
    "write_pin",
]

PIN_SCHEMA = 1

Fetcher = Callable[[str], bytes]
"""``url -> bytes``. The default is :func:`fetch`; tests pass a closure over a literal."""

_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class PinnedSource:
    """One row of ``x-vendorfake.sources`` / ``pin.json.sources``."""

    url: str
    sha256: str
    bytes: int
    version: str
    fetched: str

    @classmethod
    def of(cls, row: Mapping[str, Any]) -> PinnedSource:
        return cls(
            url=str(row["url"]),
            sha256=str(row["sha256"]),
            bytes=int(row["bytes"]),
            version=str(row.get("version", "")),
            fetched=str(row.get("fetched", "")),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "version": self.version,
            "fetched": self.fetched,
        }


@dataclass(frozen=True, slots=True)
class Pin:
    """``pin.json``: the upstream rows and the extract's own digest."""

    sources: tuple[PinnedSource, ...]
    extract_sha256: str
    #: The ``METHOD /path`` keys the extract was scoped to -- the *input* of
    #: :func:`cut_extract`, kept so a non-vendored vendor's cut can be
    #: reproduced at run time from the pin alone (konyklabs/roadmap#56). A
    #: vendored pin leaves it empty: the committed extract already says.
    modeled: tuple[str, ...] = ()
    #: The cut's digest and one per kept operation (konyklabs/roadmap#178); empty on a vendored pin, like ``modeled``.
    cut_sha256: str = ""
    operations: tuple[tuple[str, str], ...] = ()
    #: The ``webhooks`` entry names the cut was scoped to, found or not, read off its ledgers; empty unless declared.
    webhooks: tuple[str, ...] = ()

    @classmethod
    def of(cls, doc: Mapping[str, Any]) -> Pin:
        if int(doc.get("schema", 0)) != PIN_SCHEMA:
            raise ValueError(f'{PIN_FILE}: expected "schema": {PIN_SCHEMA}, got {doc.get("schema")!r}')
        return cls(
            sources=tuple(PinnedSource.of(row) for row in doc.get("sources", ())),
            extract_sha256=str(doc["extract_sha256"]),
            modeled=tuple(str(key) for key in doc.get("modeled", ())),
            cut_sha256=str(doc.get("cut_sha256", "")),
            operations=tuple(sorted((str(key), str(value)) for key, value in doc.get("operations", {}).items())),
            webhooks=tuple(str(name) for name in doc.get("webhooks", ())),
        )

    @classmethod
    def from_extract(
        cls, document: Mapping[str, Any], extract_text: str, *, modeled: Sequence[tuple[str, str]] = ()
    ) -> Pin:
        """The pin for an extract as :func:`~vendorfake.fidelity.extract.render_json` rendered it."""
        meta = document.get("x-vendorfake", {})
        rows = meta.get("sources", ()) if isinstance(meta, Mapping) else ()
        cut_sha256, operations = cut_digests(document) if modeled else ("", {})
        hooks = {str(name) for field in ("webhooks_modeled", "webhooks_missing") for name in meta.get(field, ())}
        return cls(
            sources=tuple(PinnedSource.of(row) for row in rows),
            extract_sha256=sha256_hex(extract_text.encode("utf-8")),
            modeled=tuple(route_key(method, spec_path) for method, spec_path in modeled),
            cut_sha256=cut_sha256,
            operations=tuple(sorted(operations.items())),
            webhooks=tuple(sorted(hooks)) if modeled else (),
        )

    def to_json(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "schema": PIN_SCHEMA,
            "sources": [row.to_json() for row in self.sources],
            "extract_sha256": self.extract_sha256,
        }
        if self.modeled:
            doc["modeled"] = list(self.modeled)
        if self.cut_sha256:
            doc["cut_sha256"] = self.cut_sha256
            doc["operations"] = dict(self.operations)
        if self.webhooks:
            doc["webhooks"] = list(self.webhooks)
        return doc

    def source(self, url: str) -> PinnedSource | None:
        for row in self.sources:
            if row.url == url:
                return row
        return None


def write_pin(path: Path, pin: Pin) -> None:
    path.write_text(render_json(pin.to_json()), encoding="utf-8")


def read_pin(path: Path) -> Pin:
    return Pin.of(json.loads(path.read_text(encoding="utf-8")))


def fetch(source: SpecSource, *, fetcher: Fetcher | None = None) -> bytes:
    """The upstream bytes, exactly as served. ``fetcher`` replaces the network."""
    if fetcher is not None:
        return fetcher(source.url)
    response = httpx.get(source.url, follow_redirects=True, timeout=_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.content


GONE = "GONE"
UNREACHABLE = "UNREACHABLE"


@dataclass(frozen=True, slots=True)
class SourceFailure:
    """One declared source that could not be fetched, and why (the third invariant)."""

    url: str
    #: :data:`GONE` (404/410) or :data:`UNREACHABLE` (everything else).
    state: str
    #: For a terminal: the status and final URL, or the transport error.
    detail: str


def _failure(url: str, exc: Exception) -> SourceFailure:
    """Classify a fetch error. Only ``httpx`` and ``OSError`` failures reach here."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        final = str(exc.response.url)
        where = f" at {final}" if final and final != url else ""
        state = GONE if status in (404, 410) else UNREACHABLE
        return SourceFailure(url, state, f"HTTP {status}{where}")
    return SourceFailure(url, UNREACHABLE, f"{type(exc).__name__}: {exc}")


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """What one refresh found. ``diff_summary`` is for a terminal; the booleans are for an exit code."""

    changed_upstream: bool
    changed_extract: bool
    diff_summary: str
    #: Declared sources that could not be fetched; when non-empty nothing was cut or written.
    failures: tuple[SourceFailure, ...] = ()
    #: Pinned sources whose bytes moved with the cut unchanged: a re-pin chore, not a change (konyklabs/roadmap#178).
    moved: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.changed_upstream or self.changed_extract

    @property
    def gone(self) -> tuple[SourceFailure, ...]:
        return tuple(failure for failure in self.failures if failure.state == GONE)

    @property
    def unreachable(self) -> tuple[SourceFailure, ...]:
        return tuple(failure for failure in self.failures if failure.state == UNREACHABLE)


def refresh(
    anchor_dir: Path,
    declaration: FidelityDeclaration,
    modeled: Sequence[tuple[str, str]],
    *,
    fetcher: Fetcher | None = None,
    check: bool = False,
    fetched: str,
    cache_dir: Path | str | None = None,
) -> RefreshResult:
    """Fetch every declared source, cut the extract, compare with what is
    committed under ``anchor_dir`` and -- unless ``check`` -- write the new
    ``extract.json`` and ``pin.json`` there.

    ``anchor_dir`` is the directory holding ``declaration.json`` (for a built-in
    vendor, ``importlib.resources.files(anchor)``). ``modeled`` is the
    ``(METHOD, spec_path)`` list with aliases applied, as :func:`cut_extract`
    takes it. ``fetched`` is today's ISO date, applied per the second invariant.

    A non-vendored declaration (``vendored: false``) writes ``pin.json`` beside
    the declaration as always, but the extract goes to the cache directory
    (``cache_dir``, else the resolution in :mod:`vendorfake.fidelity.cache`)
    and never under the package; the pin then also carries ``modeled`` so the
    cut can be reproduced from the pin alone.

    A source that cannot be fetched (the third invariant) is reported in
    ``failures`` with a line of its own; the cut is skipped and nothing is
    written, ``check`` or not.
    """
    from vendorfake.fidelity.cache import cache_path

    extract_dir = anchor_dir if declaration.vendored else cache_path(declaration.anchor, cache_dir)
    extract_path = extract_dir / EXTRACT_FILE
    pin_path = anchor_dir / PIN_FILE
    old_pin = read_pin(pin_path) if pin_path.exists() else None
    old_text = extract_path.read_text(encoding="utf-8") if extract_path.exists() else None

    blobs: list[tuple[SpecSource, bytes]] = []
    failures: list[SourceFailure] = []
    for source in declaration.sources:
        # Every source is fetched whatever the one before it did (the third
        # invariant); _failure tells a status error from a transport one.
        try:
            blobs.append((source, fetch(source, fetcher=fetcher)))
        except (httpx.HTTPError, OSError) as exc:
            failures.append(_failure(source.url, exc))
    if failures:
        return _unfetched(declaration, blobs, failures, old_pin, check=check)

    document = cut_extract(
        blobs,
        modeled,
        fetched=fetched,
        extension_map=declaration.extension_map,
        error_schema=declaration.error_schema,
        annotations=declaration.annotations,
        webhooks=[hook.name for hook in declaration.webhooks],
    )

    lines: list[str] = []
    changed_upstream = False
    moved: list[str] = []
    for row in document["x-vendorfake"]["sources"]:
        pinned = old_pin.source(row["url"]) if old_pin is not None else None
        if pinned is not None and pinned.sha256 == row["sha256"]:
            row["fetched"] = pinned.fetched
            lines.append(f"upstream {row['url']}: unchanged (sha256 {row['sha256'][:12]}, fetched {pinned.fetched})")
            continue
        if pinned is None:
            changed_upstream = True
            lines.append(
                f"upstream {row['url']}: new pin (sha256 {row['sha256'][:12]}, {row['bytes']} bytes, "
                f"version {row['version']!r}, fetched {row['fetched']})"
            )
        else:
            moved.append(row["url"])
            lines.append(
                f"upstream {row['url']}: changed sha256 {pinned.sha256[:12]} -> {row['sha256'][:12]}, "
                f"{pinned.bytes} -> {row['bytes']} bytes, version {pinned.version!r} -> {row['version']!r}"
            )
    if old_pin is not None:
        for pinned in old_pin.sources:
            if not any(row["url"] == pinned.url for row in document["x-vendorfake"]["sources"]):
                changed_upstream = True
                lines.append(f"upstream {pinned.url}: no longer declared")

    new_text = render_json(document)
    new_pin = Pin.from_extract(document, new_text, modeled=() if declaration.vendored else modeled)
    cut_sha256, operations = cut_digests(document)

    # "The extract changed" means the cut changed -- what the validator sees --
    # never that a source row or ``info`` moved with the upstream (konyklabs/roadmap#178).
    changed_extract = _pinned_cut(old_pin, old_text, vendored=declaration.vendored) != cut_sha256
    if changed_extract and moved:
        changed_upstream, moved = True, []
    if not changed_extract:
        lines.append(f"{EXTRACT_FILE}: unchanged" + (" (cut; the source rows moved)" if moved else ""))
    elif old_pin is not None and not declaration.vendored and not old_pin.cut_sha256:
        lines.append(f"{PIN_FILE}: records no cut digest (pinned before konyklabs/roadmap#178) -- `pin` writes one")
    elif old_pin is not None and old_pin.operations:
        lines.extend(_operation_diff(dict(old_pin.operations), operations))
    elif old_text is not None:
        lines.extend(_extract_diff(json.loads(old_text), document, old_text, new_text))
    else:
        lines.append(f"{EXTRACT_FILE}: new ({len(new_text.encode('utf-8'))} bytes)")
    if (
        declaration.vendored
        and old_pin is not None
        and old_text is not None
        and sha256_hex(old_text.encode("utf-8")) != old_pin.extract_sha256
    ):
        changed_extract = True
        lines.append(f"{PIN_FILE}: extract_sha256 does not match the committed {EXTRACT_FILE} (edited by hand?)")
    elif (
        old_pin is not None
        and not changed_upstream
        and not changed_extract
        and not moved
        and (old_pin.sources, old_pin.extract_sha256, old_pin.modeled, old_pin.webhooks)
        != (new_pin.sources, new_pin.extract_sha256, new_pin.modeled, new_pin.webhooks)
    ):
        # Same bytes and same cut can only disagree with the pin if the pin was edited by hand.
        changed_upstream = True
        lines.append(f"{PIN_FILE}: rows differ from what the extract says (edited by hand?)")

    if not check and (changed_upstream or changed_extract or moved):
        extract_dir.mkdir(parents=True, exist_ok=True)
        extract_path.write_text(new_text, encoding="utf-8")
        write_pin(pin_path, new_pin)
        if declaration.vendored:
            lines.append(f"wrote {extract_path.name} and {pin_path.name}")
        else:
            lines.append(f"wrote {pin_path.name} beside the declaration and {extract_path.name} to {extract_dir}")
    elif check:
        lines.append("check mode: nothing written")

    return RefreshResult(
        changed_upstream=changed_upstream,
        changed_extract=changed_extract,
        diff_summary="\n".join(lines),
        moved=tuple(moved),
    )


def _unfetched(
    declaration: FidelityDeclaration,
    blobs: Sequence[tuple[SpecSource, bytes]],
    failures: Sequence[SourceFailure],
    old_pin: Pin | None,
    *,
    check: bool,
) -> RefreshResult:
    """The report when at least one source failed: a line per source, no cut, nothing written.

    A source that did fetch is compared by its bytes alone -- its version
    string lives inside the document and needs the cut, which is skipped,
    because a cut missing one of a vendor's documents would report every
    operation that document carried as removed.
    """
    fetched = {source.url: data for source, data in blobs}
    failed = {failure.url: failure for failure in failures}
    lines: list[str] = []
    changed_upstream = False
    for source in declaration.sources:
        pinned = old_pin.source(source.url) if old_pin is not None else None
        failure = failed.get(source.url)
        if failure is not None:
            last = f"pinned sha256 {pinned.sha256[:12]}, fetched {pinned.fetched}" if pinned else "never pinned"
            lines.append(f"upstream {source.url}: {failure.state} ({failure.detail}; {last})")
            continue
        data = fetched[source.url]
        digest = sha256_hex(data)
        if pinned is not None and pinned.sha256 == digest:
            lines.append(f"upstream {source.url}: unchanged (sha256 {digest[:12]}, fetched {pinned.fetched})")
            continue
        changed_upstream = True
        if pinned is None:
            lines.append(f"upstream {source.url}: new pin (sha256 {digest[:12]}, {len(data)} bytes)")
        else:
            lines.append(
                f"upstream {source.url}: changed sha256 {pinned.sha256[:12]} -> {digest[:12]}, "
                f"{pinned.bytes} -> {len(data)} bytes"
            )
    if old_pin is not None:
        declared = {source.url for source in declaration.sources}
        for row in old_pin.sources:
            if row.url not in declared:
                changed_upstream = True
                lines.append(f"upstream {row.url}: no longer declared")
    lines.append(f"{EXTRACT_FILE}: not cut -- {len(failures)} source(s) could not be fetched")
    if check:
        lines.append("check mode: nothing written")
    else:
        lines.append(f"not written: {PIN_FILE} and {EXTRACT_FILE} keep the last documents that were fetched")
    return RefreshResult(
        changed_upstream=changed_upstream,
        changed_extract=False,
        diff_summary="\n".join(lines),
        failures=tuple(failures),
    )


def _pinned_cut(old_pin: Pin | None, old_text: str | None, *, vendored: bool) -> str | None:
    """The digest of the cut the pin describes: recorded in a non-vendored pin, cut from a committed extract that digests to a vendored one; ``None`` when neither can say."""
    if old_pin is None:
        return None
    if not vendored:
        return old_pin.cut_sha256 or None
    if old_text is None or sha256_hex(old_text.encode("utf-8")) != old_pin.extract_sha256:
        return None
    return cut_digests(json.loads(old_text))[0]


def _operation_diff(before: Mapping[str, str], after: Mapping[str, str]) -> list[str]:
    """The operations whose digest moved between two cuts; one line when the cut moved outside every one of them."""
    out = [f"{EXTRACT_FILE}: operation + {key}" for key in sorted(after.keys() - before.keys())]
    out += [f"{EXTRACT_FILE}: operation - {key}" for key in sorted(before.keys() - after.keys())]
    out += [
        f"{EXTRACT_FILE}: operation ~ {key}"
        for key in sorted(before.keys() & after.keys())
        if before[key] != after[key]
    ]
    return out or [
        f"{EXTRACT_FILE}: cut changed outside every modeled operation (openapi, the error schema or a ledger)"
    ]


def _extract_diff(old: Mapping[str, Any], new: Mapping[str, Any], old_text: str, new_text: str) -> list[str]:
    """A structural summary of an extract change, then the unified-diff line counts."""
    out: list[str] = []
    old_meta = old.get("x-vendorfake", {}) if isinstance(old.get("x-vendorfake"), Mapping) else {}
    new_meta = new.get("x-vendorfake", {})
    for field in ("modeled", "missing", "stubbed", "webhooks_modeled", "webhooks_missing"):
        before = set(old_meta.get(field, ()))
        after = set(new_meta.get(field, ()))
        for key in sorted(after - before):
            out.append(f"{EXTRACT_FILE}: {field} + {key}")
        for key in sorted(before - after):
            out.append(f"{EXTRACT_FILE}: {field} - {key}")
    old_components = old.get("components", {})
    old_schemas = old_components.get("schemas", {}) if isinstance(old_components, Mapping) else {}
    new_schemas = new.get("components", {}).get("schemas", {})
    for name in sorted(set(new_schemas) | set(old_schemas)):
        if name not in old_schemas:
            out.append(f"{EXTRACT_FILE}: schema + {name}")
        elif name not in new_schemas:
            out.append(f"{EXTRACT_FILE}: schema - {name}")
        elif old_schemas[name] != new_schemas[name]:
            out.append(f"{EXTRACT_FILE}: schema ~ {name}")
    old_paths = old.get("paths", {}) if isinstance(old.get("paths"), Mapping) else {}
    for path in sorted(set(new["paths"]) | set(old_paths)):
        if path in old_paths and path in new["paths"] and old_paths[path] != new["paths"][path]:
            out.append(f"{EXTRACT_FILE}: operation ~ {path}")
    added = removed = 0
    for line in difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    out.append(f"{EXTRACT_FILE}: changed (+{added} -{removed} lines)")
    return out


def verify(anchor_dir: Path, declaration: FidelityDeclaration, *, cache_dir: Path | str | None = None) -> RefreshResult:
    """The offline half of ``refresh``: is what is committed self-consistent?

    No network: whether upstream moved is a scheduled question (D-006). A vendored
    extract must digest to the pin. A non-vendored cache is judged by its cut
    (konyklabs/roadmap#178): source rows that moved with the pin's cut are a re-pin
    chore (``moved``); a moved cut is a finding naming the operations.
    """
    from vendorfake.fidelity.cache import cache_path

    lines: list[str] = []
    changed_extract = False
    changed_upstream = False
    pin_path = anchor_dir / PIN_FILE
    if declaration.vendored:
        extract_path = anchor_dir / EXTRACT_FILE
    else:
        extract_dir = cache_path(declaration.anchor, cache_dir)
        extract_path = extract_dir / EXTRACT_FILE
        if not pin_path.is_file():
            return RefreshResult(True, True, f"missing under {anchor_dir}: {PIN_FILE} -- run `pin` once")
        if not extract_path.is_file():
            return RefreshResult(
                # Nothing checked is not a pass: the pin's own claims (the
                # extract digest, the source rows) are only verifiable
                # against a cut, and CI populates one before this runs.
                True,
                False,
                f"no cache at {extract_path}: the pin cannot be verified offline -- run `vendorfake-fidelity fetch` first",
            )
    if not extract_path.is_file() or not pin_path.is_file():
        missing = [name for name, path in ((EXTRACT_FILE, extract_path), (PIN_FILE, pin_path)) if not path.is_file()]
        return RefreshResult(True, True, f"missing under {anchor_dir}: {', '.join(missing)} -- run `pin` once")
    pin = read_pin(pin_path)
    text = extract_path.read_text(encoding="utf-8")
    actual = sha256_hex(text.encode("utf-8"))
    document = json.loads(text)
    moved: tuple[str, ...] = ()
    if actual != pin.extract_sha256 and not declaration.vendored and pin.cut_sha256:
        cut_sha256, operations = cut_digests(document)
        rows = {row["url"]: row["sha256"] for row in document["x-vendorfake"]["sources"]}
        pinned_rows = {row.url: row.sha256 for row in pin.sources}
        moved = tuple(url for url, sha in rows.items() if url in pinned_rows and pinned_rows[url] != sha)
        same = cut_sha256 == pin.cut_sha256
        for url in moved:
            lines.append(
                f"upstream {url}: moved (pinned {pinned_rows[url][:12]}, cached cut from {rows[url][:12]})"
                + (" -- cut unchanged" if same else "")
            )
        if same and not moved:
            lines.append(
                f"{EXTRACT_FILE}: cut matches {PIN_FILE}; bytes differ outside the cut -- run `vendorfake-fidelity pin`"
            )
        elif not same:
            changed_extract, changed_upstream, moved = True, bool(moved), ()
            lines.extend(_operation_diff(dict(pin.operations), operations))
    else:
        if actual != pin.extract_sha256:
            changed_extract = True
            lines.append(
                f"{EXTRACT_FILE}: sha256 {actual[:12]} does not match {PIN_FILE}'s {pin.extract_sha256[:12]} "
                f"(edited by hand?)"
            )
            if not declaration.vendored:
                lines.append(
                    f"{PIN_FILE}: records no cut digest (pinned before konyklabs/roadmap#178) -- "
                    f"run `vendorfake-fidelity pin`"
                )
        embedded = Pin.from_extract(document, text)
        if embedded.sources != pin.sources:
            changed_extract = True
            lines.append(f"{EXTRACT_FILE}: its x-vendorfake.sources rows disagree with {PIN_FILE}")
    meta = document.get("x-vendorfake", {})
    stubbed = tuple(meta.get("stubbed", ())) if isinstance(meta, Mapping) else ()
    for name in sorted(set(stubbed) - set(declaration.stubs_accepted)):
        changed_extract = True
        lines.append(
            f"{EXTRACT_FILE}: schema {name!r} is stubbed to {{}} (upstream dangles) and not in stubs_accepted -- "
            f"everything it types is unvalidated until the declaration accepts it"
        )
    if isinstance(meta, Mapping):
        cut_names = {str(name) for field in ("webhooks_modeled", "webhooks_missing") for name in meta.get(field, ())}
        declared_names = {hook.name for hook in declaration.webhooks}
        for name in sorted(declared_names ^ cut_names):
            changed_extract = True
            side = "declared but not in the cut" if name in declared_names else "in the cut but no longer declared"
            lines.append(f"{EXTRACT_FILE}: webhooks entry {name!r} is {side} -- run `vendorfake-fidelity pin`")
    declared = {source.url for source in declaration.sources}
    pinned = {row.url for row in pin.sources}
    for url in sorted(declared - pinned):
        changed_upstream = True
        lines.append(f"declared source not pinned: {url}")
    for url in sorted(pinned - declared):
        changed_upstream = True
        lines.append(f"pinned source no longer declared: {url}")
    if not lines:
        for row in pin.sources:
            lines.append(
                f"upstream {row.url}: pinned sha256 {row.sha256[:12]}, fetched {row.fetched} (offline; not re-fetched)"
            )
        where = "" if declaration.vendored else f" (cached at {extract_path})"
        lines.append(f"{EXTRACT_FILE}: matches {PIN_FILE}{where}")
    return RefreshResult(changed_upstream, changed_extract, "\n".join(lines), moved=moved)
