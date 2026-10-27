"""Every ``@vX.Y.Z`` install pin in the docs names the version that ships.

FOR: catching the drift a release leaves behind if a doc is missed.
README.md, docs/index.md and docs/start/install.md each tell a consumer to
install a tagged commit (``pip install ... @vX.Y.Z``) and each carries a
release-please ``x-release-please-version`` marker (see
``docs/start/install.md`` and ``release-please-config.json``'s
``extra-files``) so a release bumps the pin automatically. That is exactly
the kind of mechanism that fails silently: a marker release-please's regex
stops matching, a pin added by hand after the fact, or a new doc that copies
an old pin without the marker, would all ship instructions that install the
wrong tag, and nothing else in this suite would notice. This test reads
every Markdown file under the docs surface, finds every ``@vX.Y.Z`` it
contains, and asserts each one equals the version of the ``vendorfake``
package actually imported -- printing the file and line of any mismatch so
the fix is one edit, not a grep. The same holds for the health JSON those
three files paste after ``curl .../__unit/health``: its ``"version"`` is on an
annotated line, so release-please rewrites it, and the second test asserts it.
"""

from __future__ import annotations

import re
from pathlib import Path

import vendorfake

ROOT = Path(__file__).resolve().parents[2]

PIN_RE = re.compile(r"konyklabs/vendorfake@v(\d+\.\d+\.\d+)")

# The health JSON pasted under each start page's `curl .../__unit/health`
# carries a version too. Only a line release-please rewrites (one annotated
# with ``x-release-please-version``) is a pin; the three files named in
# ``release-please-config.json``'s ``extra-files`` are where it lives.
MARKER = "x-release-please-version"
HEALTH_VERSION_RE = re.compile(r'"version"\s*:\s*"(\d+\.\d+\.\d+)"')
EXTRA_FILES = ("README.md", "docs/index.md", "docs/start/install.md")


def _pins_in(path: Path) -> list[tuple[Path, int, str]]:
    """Every ``(path, line number, pinned version)`` triple found in *path*."""
    found: list[tuple[Path, int, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        found.extend((path, lineno, match.group(1)) for match in PIN_RE.finditer(line))
    return found


def test_every_docs_install_pin_matches_the_installed_version() -> None:
    files = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    pins = [pin for f in files if f.is_file() for pin in _pins_in(f)]

    assert pins, f"found 0 @vX.Y.Z pins across {len(files)} files: {[str(f.relative_to(ROOT)) for f in files]}"

    mismatches = [
        f"{path.relative_to(ROOT)}:{lineno}: pinned v{found}, vendorfake.__version__ is {vendorfake.__version__!r}"
        for path, lineno, found in pins
        if found != vendorfake.__version__
    ]
    assert not mismatches, "\n" + "\n".join(mismatches)


def _health_versions_in(path: Path) -> list[tuple[Path, int, str]]:
    """Every ``"version":"X.Y.Z"`` on a line carrying the release-please marker."""
    found: list[tuple[Path, int, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if MARKER in line:
            found.extend((path, lineno, match.group(1)) for match in HEALTH_VERSION_RE.finditer(line))
    return found


def test_every_pasted_health_version_matches_the_installed_version() -> None:
    files = [ROOT / name for name in EXTRA_FILES]
    versions = [v for f in files for v in _health_versions_in(f)]

    assert len({path for path, _, _ in versions}) == len(files), (
        f'found {len(versions)} annotated "version" values; expected one in each of {list(EXTRA_FILES)}: '
        f"{[f'{p.relative_to(ROOT)}:{n}' for p, n, _ in versions]}"
    )

    mismatches = [
        f'{path.relative_to(ROOT)}:{lineno}: pasted "version":"{found}", vendorfake.__version__ is {vendorfake.__version__!r}'
        for path, lineno, found in versions
        if found != vendorfake.__version__
    ]
    assert not mismatches, "\n" + "\n".join(mismatches)
