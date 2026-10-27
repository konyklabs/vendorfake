# Using this repository in another GitHub organisation

For an engineer who copied this repository — a fork or an import — into
another GitHub organisation and wants green CI and true docs on the first day.
Most of it travels unchanged. Four workflow files reach back into the
upstream organisation; this page names them and the exact edit for each.
Line numbers are as of 0.7.0.

## 1. What works unchanged

- **The package and its tests.** Nothing in `src/` or `tests/` depends on
  where the repository lives.
- **The one command.**

    ```sh
    uv sync --all-groups && tools/self-test.sh
    ```

    `tools/self-test.sh --quick` is the pull-request subset.
- **The docs site.** `uv run --group docs mkdocs build --strict`.
- **The container.** The `Dockerfile` and `tools/verify_image_build.sh`.
- **Three workflows** that use only public actions and `GITHUB_TOKEN`:

| Workflow | When it runs | What it needs in a copy |
|---|---|---|
| `.github/workflows/self-test.yml` | Pull request: the `check` job on Python 3.13 — `--quick`, then the four vendor unit suites and the parity suite. Push to `main` and dispatch: the full matrix (`test`, Python 3.11 and 3.13). | Nothing. |
| `.github/workflows/fidelity-drift.yml` | Weekly cron (`17 6 * * 1`, Monday) and dispatch. | `issues: write` (declared in the file) and outbound HTTPS to the vendors' documentation hosts. It files its issue in the copy's own repository. In a fork, GitHub disables every workflow until someone enables them from the Actions tab; GitHub also stops a schedule after a stretch with no repository activity. |
| `.github/workflows/publish-image.yml` | Dispatch only, with the input `confirm` set to `publish`. | `packages: write` for Actions in the repository settings. It pushes to `ghcr.io/${{ github.repository }}` (line 38), so it follows the copy. The comment at line 1 names the upstream registry path; it is a comment, not configuration. |

`release-please-config.json` and `.release-please-manifest.json` travel too.
The copy continues from 0.7.0 unless it resets on purpose — and a reset changes
`pyproject.toml`'s `version`, the manifest and `CHANGELOG.md` together, in one
commit.

## 2. What to delete or replace

Four files call reusable workflows in the upstream organisation's `.github`
repository. That repository is public, so the calls resolve from any
organisation and run — they do not fail. That is the problem: each one runs
code from another organisation, three of them pinned to its mutable `main`, and
two with `secrets: inherit`, which hands that code every secret the copy can
see. Each one also enforces the upstream organisation's rules, not yours.

| File | What it calls | What happens in a copy | Do this |
|---|---|---|---|
| `.github/workflows/title-lint.yml` (lines 8-9) | `uses: konyklabs/.github/.github/workflows/title-lint.yml@main` | It runs and checks every pull request title against the upstream rules: a conventional-commit prefix and a task reference (`#N` or `org/repo#N`), or the check `lint / check` goes red. Whatever upstream's `main` says next is what your titles are checked against. | Delete it, replace it with your own title check, or repoint `uses:` at your organisation's `.github` repository. |
| `.github/workflows/proprietary-scan.yml` (lines 9-10) | The same pattern, plus `secrets: inherit` for the organisation secret `PROPRIETARY_BLOCKLIST` | The secret does not travel, so the reusable prints "No blocklist available in this context — scan skipped" and exits 0. The check `scan / scan` is green and has checked nothing. `secrets: inherit` still passes the copy's own secrets to upstream code. | Delete it — it enforces a rule specific to the upstream organisation — or replace it with your own scan. |
| `.github/workflows/claude-review.yml` (lines 15-23) | An opt-in review gate behind the `gate` label; the upstream reusable at `@main` with `secrets: inherit` and `id-token: write` | Adding the label runs upstream's review pipeline with the copy's secrets. It needs `CLAUDE_CODE_OAUTH_TOKEN`, which does not travel, so its model steps have no credential. | Delete it. Nothing depends on it. |
| `.github/workflows/release.yml`, the `release-please` job only (lines 16-24) | `uses: konyklabs/.github/.github/workflows/release-please.yml@a70221d…` (pinned to a commit) | It runs `googleapis/release-please-action@v4` in manifest mode on every push to `main`, and opens release pull requests in the copy from the committed config and manifest. It works; it is still code from another organisation. | Keep the behaviour without the dependency: replace the job with `googleapis/release-please-action` called directly, reading the committed config and manifest (manifest mode: no `release-type` input). Or delete the job and tag by hand. |

The `build` and `publish` jobs below the `release-please` job in `release.yml`
are self-contained, but `publish` does nothing useful until a PyPI trusted
publisher is registered — see [section 5](#5-network-vendors-and-publishing).

**Rulesets do not travel with a copy.** The upstream repository's
`protect-main` ruleset requires the status checks `lint / check` and
`scan / scan`, and only the two callers above produce them. A copy that
recreates that ruleset and deletes the callers blocks every pull request,
forever. Require the copy's own check instead: the `check` job of
`self-test.yml` (context name `check`). Add `test (3.11)` and `test (3.13)`
only if you also change `self-test.yml` to run the full matrix on pull
requests; as shipped, that job runs only on push and dispatch.

## 3. Names to retarget (optional) — and the one trap

Everything that spells `konyklabs/vendorfake` keeps working from a copy: it
points at the upstream project, which still exists. Retargeting is optional.
If you do it, do it in one commit, then run `tools/self-test.sh --quick`.

| File | Line | What it is |
|---|---|---|
| `pyproject.toml` | 9 | `authors` (a name, not a URL — edit by hand if you want your own) |
| `pyproject.toml` | 59-60 | `Homepage`, `Issues` |
| `mkdocs.yml` | 5-7 | `site_author` (a name, edit by hand), `repo_url`, `repo_name` |
| `Dockerfile` | 34 | `org.opencontainers.image.source` — GHCR uses it to link the package to a repository |
| `llms.txt` | every link | ten links into the repository |
| `README.md` | 39-40 | the install lines |
| `docs/index.md` | 46 | the install line |
| `docs/start/install.md` | 6, 8 | the install lines |
| `docs/start/bindings.md` | 215, 254, 325 | docker compose `build:` URLs |
| `docs/start/bindings.md` | 402 | `actions/checkout`'s `repository:` |
| `docs/start/bindings.md` | 289, 546 | links to the example project |
| `examples/pytest-consumer/README.md` | 17 | the dependency line |
| `examples/pytest-consumer/pyproject.toml` | 9 | the dependency line, commented |
| `AGENTS.md` | 7, 9 | links into the docs |
| `src/vendorfake/fidelity/corpus.schema.json`, `declaration.schema.json` | 3 | `$id` — an identifier, never fetched, spelled `konyklabs.github.io/vendorfake` |

**The trap.** `tests/unit/test_docs_pins.py:28` finds the install lines with
the literal pattern `konyklabs/vendorfake@v…`. Retarget the install lines
without that pattern and the self-test goes red with "found 0 pins". Change
both in the same commit. The one-shot command below does, because it rewrites
the test's pattern along with the docs (POSIX shell, `perl` on macOS and
Linux):

```sh
git grep -l 'konyklabs/vendorfake' -- ':!CHANGELOG.md' ':!uv.lock' ':!NOTICE' ':!docs/start/another-organisation.md' | xargs perl -pi -e 's{konyklabs/vendorfake(?!#)}{NEWORG/vendorfake}g'
```

The `(?!#)` leaves `konyklabs/vendorfake#N` alone: those are upstream issue
numbers kept as provenance (`docs/api-contract.md:337`,
`src/vendorfake/conformance/checks/control_plane.py:5`,
`tests/conformance/test_mutants.py:284`, `tests/unit/test_route_scopes.py:5`),
the same kind of reference as [section 4](#4-what-the-comments-mean) describes.
The command does not touch the two schema `$id` lines, which use the
`konyklabs.github.io` spelling; edit those by hand if you want them changed.
`CHANGELOG.md` is release history with upstream links, `NOTICE` is the
attribution to the upstream project ([section 6](#6-licence-and-attribution)),
and this page describes the upstream project; all three are left alone on
purpose.

Keep each `x-release-please-version` marker on the line it is on.
Release-please bumps exactly those lines, in exactly the files
`release-please-config.json` lists as `extra-files` (lines 6-10:
`README.md`, `docs/index.md`, `docs/start/install.md`).

## 4. What the comments mean

- **`konyklabs/roadmap#N`** in docstrings, comments and tests is the upstream
  project's issue number for the task that motivated a line, kept as
  provenance. At 0.7.0, `git grep -l 'konyklabs/roadmap#' -- ':!CHANGELOG.md'`
  lists 135 files (243 lines).
- **`D-NNN`** (D-001, D-002 and D-006 appear here) are the upstream project's
  architecture decision records:
  <https://github.com/konyklabs/roadmap/tree/main/decisions>.
- **`DOCUMENTED`, `JUDGMENT`, `transport`** are this project's own provenance
  labels ([Chaos: provenance](../concepts/chaos.md#provenance)). They describe
  where a behaviour comes from and have nothing to do with the organisation.

Leave all of it. A copy loses nothing by keeping these references; scrubbing
them loses the review trail.

`AGENTS.md` and `CLAUDE.md` are instructions for coding agents working inside
the repository. The "workspace" rules they mention live outside this
repository and do not apply to a copy.

## 5. Network, vendors and publishing

**Toast's specification is fetched at run time.** Its declaration says
`"vendored": false` (`src/vendorfake/toast/fidelity/declaration.json:3`),
following the vendor's terms, and the extract is cut into
`~/.cache/vendorfake/fidelity`. The full self-test and the drift job need
outbound HTTPS to `doc.toasttab.com`. A pull request's `--quick` run is offline:
`tools/self-test.sh` checks pins with `pin --check --offline`. Square's and
Lightspeed's extracts are committed.

**Lightspeed's pinned document is gone upstream.** `api-2026-07.yaml` is no
longer served — the URL redirects to `/404` — and the vendor publishes
`api-2026-10.yaml` now. The weekly drift job reports it until the fake is
migrated; konyklabs/roadmap#170 records the decision to do that as its own
round.

**PyPI.** `release.yml`'s `publish` job uses OIDC trusted publishing and the
GitHub environment `pypi`. To use it:

1. Create the environment `pypi` in the copy.
2. Register a trusted publisher on PyPI: owner = your organisation,
   repository = the copy's name, workflow = `release.yml`, environment = `pypi`.

The distribution name `vendorfake` on a public index may already be taken by
the upstream project. For a public index, choose your own `[project] name`. For
an internal index, run `uv build` and upload what lands in `dist/`. Or skip
publishing and install straight from a git tag, as the README shows.

**Container.** `publish-image.yml` pushes to the copy's own GHCR namespace. It
needs `packages: write` for Actions in the repository settings, and Docker on
the runner (GitHub's `ubuntu-latest` has it).

**Secrets.** The organisation secrets `PROPRIETARY_BLOCKLIST` and
`CLAUDE_CODE_OAUTH_TOKEN` belong to the upstream organisation and never travel.
Nothing that stays after section 2 needs them.

## 6. Licence and attribution

Apache-2.0 (`LICENSE`; `LICENSE:189` carries the upstream copyright line).
Section 4(d) of the licence: a redistribution carries the `NOTICE` file. This
repository ships one at its root, naming the upstream project, and the wheel
and sdist carry it too. Keep it; add a line for your own modifications if you
want to state them.

Vendor names are used only to identify which public API a module imitates. The
README's "Unofficial" notice applies to a copy exactly as it does upstream.

## 7. Checklist

1. Copy the repository (fork or import).
2. Delete `title-lint.yml`, `proprietary-scan.yml` and `claude-review.yml`, or
   replace the first two with your own checks. They resolve and run from a copy,
   so nothing fails to tell you they are still there.
3. Replace the `release-please` job in `release.yml` with
   `googleapis/release-please-action` in manifest mode, or delete it and tag by
   hand.
4. If you protect `main` with a ruleset, require `check`, not `lint / check` or
   `scan / scan`.
5. Optionally retarget `konyklabs/vendorfake` in one commit with the command in
   [section 3](#3-names-to-retarget-optional-and-the-one-trap), which also
   updates `tests/unit/test_docs_pins.py`.
6. Run `uv sync --all-groups && tools/self-test.sh`.
7. In a fork, enable workflows from the Actions tab so the weekly drift
   schedule runs, or delete `fidelity-drift.yml`.
8. Publish if you want to: the `pypi` environment and a trusted publisher for
   PyPI, `packages: write` for the image.
