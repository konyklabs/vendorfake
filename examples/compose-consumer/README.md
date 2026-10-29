# compose consumer example

vendorfake as one service in a consumer's docker compose stack, installed
from the release's source archive on GitHub: no checkout, no registry, no
token. The vendor is Clover; the profile is `no-faults`, which is what a CI
suite that only wants happy paths should run.

    cd examples/compose-consumer
    docker compose up --build --wait
    curl -s http://127.0.0.1:8080/__unit/health
    # -> {"status":"ok","vendor":"clover","profile":"no-faults", ...}
    docker compose down -v

`VENDORFAKE_REF` in the Dockerfile is the one place to bump; the release
process keeps it on the current tag. `VENDORFAKE_REF=refs/heads/<branch>
docker compose build --no-cache` consumes a branch before its tag.

## Your app service

Three things your own service adds, beside this one:

    app:
      environment:
        CLOVER_OAUTH_BASE_URL: http://clover:8080     # one origin serves OAuth and /v3
        CLOVER_API_BASE_URL: http://clover:8080
        CLOVER_APP_ID: UNITCLOVERAPP                  # the seeded app; docs/concepts/seed.md
        CLOVER_APP_SECRET: unit-clover-app-secret
        CLOVER_WEBHOOK_AUTH_CODE: unit-seeded-clover-webhook-auth-code
      depends_on:
        clover:
          condition: service_healthy

Set `VENDORFAKE_VENDOR_REDIRECT_URI` in `compose.yaml` to your service's
callback; the fake's authorize answers 400 to any other `redirect_uri`.

## Where the procedure is

The whole adoption — fit check, image, service, settings, seed, the first
journey test and the two runs that prove it can fail — is the
`adopting-vendorfake` skill in the `vendorfake` plugin of
`konyklabs/claude-plugins`. The bindings and the multi-vendor form are in
[docs/start/bindings.md](../../docs/start/bindings.md#docker-compose); the
image and the loopback rule in [docs/start/install.md](../../docs/start/install.md#as-a-container).
`tools/verify_compose_example.sh` is this example's own proof, run by the
self-test.
