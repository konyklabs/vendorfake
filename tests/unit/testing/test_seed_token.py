"""``seed.token``: the stored-credential half of the neutral seed view.

``credentials`` (0.2) neutralised what an application authenticates *as*;
this is what a consumer *stores* per tenant, and it is on the ``Seed``
protocol so a body parametrized over vendors reads it with no ``Any``
(konyklabs/roadmap#101, item 16). The values are asserted against the
vendor-spelled fields, not against literals, so a re-seeded profile cannot
make this pass by coincidence.
"""

from __future__ import annotations

import pytest

from vendorfake import available_vendors
from vendorfake.testing import CloverSeed, Seed, SquareSeed, ToastSeed, Token, unit


@pytest.mark.parametrize("vendor", sorted(available_vendors()))
def test_every_vendor_publishes_a_token_that_agrees_with_its_grant(vendor: str) -> None:
    with unit(vendor) as started:
        seed: Seed = started.seed
        token = seed.token
        assert isinstance(token, Token)
        assert token.access_token and token.tenant_id
        # The one real lifecycle difference, stated twice and agreeing.
        assert (token.refresh_token is None) == (seed.credentials.grant == "client_credentials")
        # It is the token ``auth`` sends, not a second one.
        assert seed.auth["Authorization"] == f"Bearer {token.access_token}"


def test_square_tenant_is_the_seller_not_a_location() -> None:
    with unit("square") as started:
        seed: SquareSeed = started.seed
        assert seed.token == Token(seed.access_token, seed.refresh_token, seed.merchant_id)
        assert seed.token.tenant_id != seed.location_id


def test_clover_tenant_is_the_merchant() -> None:
    with unit("clover") as started:
        seed: CloverSeed = started.seed
        assert seed.token == Token(seed.access_token, seed.refresh_token, seed.merchant_id)


def test_toast_has_no_refresh_token_and_the_restaurant_as_tenant() -> None:
    with unit("toast") as started:
        seed: ToastSeed = started.seed
        assert seed.token == Token(seed.access_token, None, seed.restaurant_guid)


def test_a_running_units_token_expiry_is_patchable_and_advances_with_the_virtual_clock() -> None:
    """The control-plane route documented in ``docs/concepts/seed.md``'s
    "Token lifetimes" section: `POST /__unit/state/update` on `tokens`,
    paired with `POST /__unit/clock/advance` (konyklabs/roadmap#131, item 4)."""
    start_ms = 1767225600000  # 2026-01-01T00:00:00Z, epoch ms
    with unit(
        "clover",
        clock_start="2026-01-01T00:00:00Z",
        env={"VENDORFAKE_CLOCK": "virtual"},
    ) as clover:
        token = clover.seed.token
        merchant_path = f"/v3/merchants/{clover.seed.merchant_id}"

        patched = clover.client.post(
            "/__unit/state/update",
            json={
                "collection": "tokens",
                "id": "tok_seed_full",
                "patch": {"access_token_expiration_ms": start_ms + 60_000},
            },
        )
        assert patched.status_code == 200, patched.text

        still_good = clover.client.get(merchant_path, headers=clover.seed.auth)
        assert still_good.status_code == 200, still_good.text

        advanced = clover.client.post("/__unit/clock/advance", json={"ms": 61_000})
        assert advanced.status_code == 200, advanced.text

        expired = clover.client.get(merchant_path, headers=clover.seed.auth)
        assert expired.status_code == 401
        assert expired.headers.get("x-unit-error") == "token_expired"

        refreshed = clover.client.post(
            "/oauth/v2/refresh",
            json={"client_id": clover.seed.credentials.app_id, "refresh_token": token.refresh_token},
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["access_token_expiration"] > (start_ms + 61_000) // 1000


def test_the_token_refreshes_on_a_rotating_vendor() -> None:
    """The neutral view is enough to drive a refresh, which is what a
    consumer's stored row exists for."""
    with unit("clover", "oauth-only") as clover:
        token = clover.seed.token
        answered = clover.client.post(
            "/oauth/v2/refresh",
            json={"client_id": clover.seed.credentials.app_id, "refresh_token": token.refresh_token},
        )
    assert answered.status_code == 200, answered.text
    assert answered.json()["refresh_token"] != token.refresh_token
