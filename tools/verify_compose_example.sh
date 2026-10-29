#!/usr/bin/env bash
# Build examples/compose-consumer from the release archive its Dockerfile
# pins and prove the service comes up healthy and answers /__unit/health
# with that vendor, that profile and that version.
#
# What this catches that verify_image_build.sh cannot: the archive install
# path a consumer with no checkout uses -- a tag that does not exist, a
# pyproject the sdist build cannot handle, a pin the release left behind.
#
# Exit 3 (SKIP in tools/self-test.sh) only when Docker is absent or its
# daemon does not answer. Everything else is a FAIL: no network, a 404
# archive, a build error, an unhealthy service. On the release commit the
# archive may 404 for a minute until release-please has tagged; re-run.
#
# Usage: tools/verify_compose_example.sh

set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

EXAMPLE=examples/compose-consumer
PROJECT="vendorfake-compose-example-$$"
HEALTH_TIMEOUT_S="${HEALTH_TIMEOUT_S:-120}"
failed=0

say()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; failed=1; }
compose() { VENDORFAKE_HOST_PORT=0 docker compose -f "$EXAMPLE/compose.yaml" -p "$PROJECT" "$@"; }

cleanup() { compose down -v --remove-orphans >/dev/null 2>&1; }
trap cleanup EXIT

say "docker"
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  printf 'skipped: docker is not on PATH or its daemon does not answer\n'
  exit 3
fi
ok "daemon answers"

# The version the health reply must carry is the one the Dockerfile pins.
ref=$(sed -n 's/^ARG VENDORFAKE_REF=\(v[0-9][0-9.]*\).*/\1/p' "$EXAMPLE/Dockerfile")
[ -n "$ref" ] || { fail "no 'ARG VENDORFAKE_REF=vX.Y.Z' line in $EXAMPLE/Dockerfile"; exit 1; }
want_version="${ref#v}"

say "build from the $ref archive"
if compose build --quiet; then ok "built"; else fail "docker compose build failed (if this is the release commit, the tag may not exist yet: re-run)"; exit 1; fi

say "up and wait for healthy"
if compose up -d --wait --wait-timeout "$HEALTH_TIMEOUT_S"; then ok "healthy"; else fail "not healthy after ${HEALTH_TIMEOUT_S}s"; compose logs --no-color | tail -20; exit 1; fi

port=$(compose port clover 8080 | sed 's/.*://')
[ -n "$port" ] || { fail "no published port"; exit 1; }
health=$(curl -sf "http://127.0.0.1:$port/__unit/health") || { fail "GET /__unit/health failed on 127.0.0.1:$port"; exit 1; }
for want in '"vendor":"clover"' '"profile":"no-faults"' "\"version\":\"$want_version\""; do
  if printf '%s' "$health" | grep -qF "$want"; then ok "$want"; else fail "$want missing from $health"; fi
done

say "summary"
if [ "$failed" -ne 0 ]; then printf 'verify_compose_example: FAILED\n'; exit 1; fi
printf 'verify_compose_example: PASSED (clover %s on 127.0.0.1:%s)\n' "$ref" "$port"
