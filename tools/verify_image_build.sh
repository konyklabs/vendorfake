#!/usr/bin/env bash
# Build the image and prove it serves every installed vendor from the wheel.
#
# What this catches that the source-tree tests cannot: a data file hatch does
# not package. Inside the image there is no source tree -- only the wheel,
# installed into a clean venv -- so a profile or seed document missing from
# the wheel is a unit that fails to construct, and HEALTHCHECK says so.
#
# Vendor-agnostic on purpose. The vendors are read off the image itself
# (`vendorfake vendors`), and the Dockerfile is checked for naming none of
# them, so adding a vendor changes nothing here and forgetting one cannot pass.
#
# Usage: tools/verify_image_build.sh [image-tag]     (default: vendorfake:verify)

set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

IMAGE="${1:-vendorfake:verify}"
HEALTH_TIMEOUT_S="${HEALTH_TIMEOUT_S:-60}"
failed=0

say()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; failed=1; }

cleanup() {
  for name in "${containers[@]:-}"; do
    [ -n "$name" ] && docker rm -f "$name" >/dev/null 2>&1
  done
}
containers=()
trap cleanup EXIT

say "build $IMAGE"
if docker build --quiet -t "$IMAGE" . >/dev/null; then
  ok "built"
else
  fail "docker build failed"
  exit 1
fi

say "the Dockerfile names no vendor"
vendors=()
while IFS= read -r line; do
  [ -n "$line" ] && vendors+=("$line")
done < <(docker run --rm "$IMAGE" vendors)
if [ "${#vendors[@]}" -eq 0 ]; then
  fail "the image reports no vendors"
fi
for vendor in "${vendors[@]}"; do
  hits=$(grep -ci "$vendor" Dockerfile || true)
  if [ "$hits" -eq 0 ]; then
    ok "'$vendor' does not appear in Dockerfile"
  else
    fail "'$vendor' appears $hits time(s) in Dockerfile; the vendor is chosen by VENDORFAKE_VENDOR, never baked in"
  fi
done

say "without a vendor the image refuses and lists them"
if refusal=$(docker run --rm "$IMAGE" 2>&1); then
  fail "serve with no vendor exited 0; expected a refusal naming the vendors"
else
  if printf '%s' "$refusal" | grep -q "Available:"; then
    ok "refused: $(printf '%s' "$refusal" | tail -1)"
  else
    fail "refused, but without listing the vendors: $refusal"
  fi
fi

# The HEALTHCHECK's command, copied: the next step fails unless the built image's HEALTHCHECK carries it verbatim.
HEALTHCHECK_PY="import os, sys, urllib.request; port = os.environ.get('VENDORFAKE_CONTROL_PORT') or os.environ.get('VENDORFAKE_PORT', '8080'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/__unit/health', timeout=2).status == 200 else 1)"

say "the image's HEALTHCHECK is the command this script runs"
# Matched as one quoted JSON array element; the command holds no <, > or &, which Go's JSON would escape.
if ! healthcheck=$(docker inspect --format '{{json .Config.Healthcheck.Test}}' "$IMAGE"); then
  fail "could not read the image's HEALTHCHECK (docker inspect failed)"
elif printf '%s' "$healthcheck" | grep -qF -- "\"$HEALTHCHECK_PY\""; then
  ok "the Dockerfile HEALTHCHECK is HEALTHCHECK_PY"
else
  fail "the Dockerfile HEALTHCHECK differs from HEALTHCHECK_PY in this script; change both together. The image has: $healthcheck"
fi

wait_healthy() {
  local status="starting"
  for _ in $(seq 1 "$HEALTH_TIMEOUT_S"); do
    status=$(docker inspect --format '{{.State.Health.Status}}' "$1" 2>/dev/null || echo "gone")
    [ "$status" = "healthy" ] && break
    [ "$status" = "gone" ] && break
    sleep 1
  done
  printf '%s' "$status"
}

say "the image runs as a non-root user"
# The exit status is checked before the value: a failed `docker run` leaves
# an empty capture, and an empty string compared against "0" reads as ok.
if ! who=$(docker run --rm --entrypoint id "$IMAGE" -u); then
  fail "could not read the image's uid (docker run failed)"
elif [ "$who" != "0" ]; then
  ok "uid $who"
else
  fail "runs as root"
fi

for vendor in "${vendors[@]}"; do
  say "serve $vendor and wait for HEALTHCHECK"
  name="vendorfake-verify-$vendor-$$"
  containers+=("$name")
  if ! docker run -d --name "$name" -e "VENDORFAKE_VENDOR=$vendor" -p "127.0.0.1::8080" "$IMAGE" >/dev/null; then
    fail "docker run failed for $vendor"
    continue
  fi
  port=$(docker port "$name" 8080/tcp | head -1 | sed 's/.*://')
  if [ -z "$port" ]; then
    fail "no published port for $vendor"
    continue
  fi

  status=$(wait_healthy "$name")
  if [ "$status" = "healthy" ]; then
    ok "HEALTHCHECK healthy"
  else
    fail "HEALTHCHECK is '$status' after ${HEALTH_TIMEOUT_S}s"
    docker logs "$name" 2>&1 | tail -20
    continue
  fi

  health=$(curl -sf "http://127.0.0.1:$port/__unit/health")
  if printf '%s' "$health" | grep -q "\"vendor\":\"$vendor\""; then
    ok "/__unit/health: $health"
  else
    fail "/__unit/health did not name $vendor: $health"
  fi

  routes=$(curl -sf "http://127.0.0.1:$port/__unit/routes" | grep -o '"method"' | wc -l | tr -d ' ')
  if [ "$routes" -gt 0 ]; then
    ok "/__unit/routes lists $routes routes"
  else
    fail "/__unit/routes listed nothing"
  fi

  # The exact command the HEALTHCHECK runs, exit code and all.
  if docker exec "$name" python -c "$HEALTHCHECK_PY"; then
    ok "healthcheck command exits 0"
  else
    fail "healthcheck command exited non-zero"
  fi

  # The ASGI adapter logs this line when the framework answered a request
  # instead of the unit; after the traffic above it must not have.
  if docker logs "$name" 2>&1 | grep -q "the web framework answered a request instead of the unit"; then
    fail "the web framework answered a request inside the container"
  else
    ok "every request was answered by the unit"
  fi
done

vendor="${vendors[0]:-}"
if [ -n "$vendor" ]; then
  say "serve $vendor with a control listener and a token, and wait for HEALTHCHECK"
  name="vendorfake-verify-control-$$"
  containers+=("$name")
  if ! docker run -d --name "$name" -e "VENDORFAKE_VENDOR=$vendor" -e VENDORFAKE_CONTROL_PORT=8081 \
      -e VENDORFAKE_CONTROL_TOKEN=verify-token -p "127.0.0.1::8080" -p "127.0.0.1::8081" "$IMAGE" >/dev/null; then
    fail "docker run failed for $vendor with a control listener"
  else
    vendor_port=$(docker port "$name" 8080/tcp | head -1 | sed 's/.*://')
    control_port=$(docker port "$name" 8081/tcp | head -1 | sed 's/.*://')
    status=$(wait_healthy "$name")
    if [ "$status" = "healthy" ]; then
      ok "HEALTHCHECK healthy on the control port, with no token"
    else
      fail "HEALTHCHECK is '$status' after ${HEALTH_TIMEOUT_S}s with a control listener"
      docker logs "$name" 2>&1 | tail -20
    fi
    expect_status() {
      local want="$1" what="$2"
      shift 2
      local got
      got=$(curl -s -o /dev/null -w '%{http_code}' "$@")
      if [ "$got" = "$want" ]; then ok "$what: $got"; else fail "$what: $got, expected $want"; fi
    }
    expect_status 401 "control /__unit/info without the token" "http://127.0.0.1:$control_port/__unit/info"
    expect_status 200 "control /__unit/info with the token" -H "vendorfake-control-token: verify-token" \
      "http://127.0.0.1:$control_port/__unit/info"
    expect_status 404 "vendor port /__unit/info" -H "vendorfake-control-token: verify-token" \
      "http://127.0.0.1:$vendor_port/__unit/info"
  fi
fi

say "summary"
if [ "$failed" -ne 0 ]; then
  printf 'verify_image_build: FAILED\n'
  exit 1
fi
printf 'verify_image_build: PASSED (%s)\n' "${vendors[*]}"
