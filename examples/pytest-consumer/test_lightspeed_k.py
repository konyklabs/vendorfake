"""What an online-ordering integration does first against Lightspeed Restaurant K-Series, run against the fake.

V1 authentication puts the code exchange's parameters in the **query string** and the refresh's in a
**form body**, with HTTP Basic client authentication on both; then the Order and Pay first journey:
businesses, a location's menus, one menu in its V2 shape; then a to-go order confirmed by the webhook its
endpoint receives. Only documented facts are asserted at full strength; where this unit had to choose, the
assertion is weakened and the comment says so.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

from vendorfake.lightspeed_k import verify_basic_auth
from vendorfake.testing import LightspeedKSeed, StartedUnit, WebhookReceiver


def _menu_items(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for group in groups:
        if group.get("@type") == "menuItem":
            found.append(group)
        found.extend(_menu_items(group.get("menuEntry", [])))
    return found


def test_first_journey_from_authorize_to_a_v2_menu(lightspeed_k: StartedUnit[LightspeedKSeed]) -> None:
    client, seed = lightspeed_k.client, lightspeed_k.seed

    # The authorize URL takes response_type, client_id, scope and redirect_uri (v1-overview); the
    # consent screen itself is a stand-in that approves.
    authorized = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": seed.client_id,
            "redirect_uri": seed.redirect_uri,
            "scope": "financial-api orders-api",
            "state": "opaque-consumer-state",
        },
        follow_redirects=False,
    )
    assert authorized.status_code == 302
    code = parse_qs(urlsplit(authorized.headers["location"]).query)["code"][0]

    exchanged = client.post(
        seed.token_path,
        params={"grant_type": "authorization_code", "code": code, "redirect_uri": seed.redirect_uri},
        headers=seed.basic_auth_headers,
    )
    assert exchanged.status_code == 200, exchanged.text
    body = exchanged.json()
    assert set(body) == {"access_token", "token_type", "refresh_token", "expires_in", "scope"}
    assert body["token_type"] == "bearer"
    # The documented sample ends in a space: split on whitespace, never on " ".
    assert body["scope"].split() == ["financial-api", "orders-api"]
    bearer = {"Authorization": f"bearer {body['access_token']}"}

    businesses = client.get("/o/op/data/businesses", headers=bearer).json()
    assert businesses[0]["businessLocations"]
    location = businesses[0]["businessLocations"][0]["id"]

    menus = client.get("/o/op/1/menu/list", params={"businessLocationId": location}, headers=bearer).json()
    menu_id = menus[0]["ikentooMenuId"]

    menu = client.get(f"/o/op/2/menu/load/{menu_id}", params={"businessLocationId": location}, headers=bearer)
    assert menu.status_code == 200
    item = next(entry for entry in _menu_items(menu.json()["menuEntryGroups"]) if entry["sku"] == seed.item_skus[0])
    assert isinstance(item["productPrice"], int | float)

    form = {"grant_type": "refresh_token", "refresh_token": body["refresh_token"]}
    refreshed = client.post(seed.token_path, data=form, headers=seed.basic_auth_headers)
    assert refreshed.status_code == 200, refreshed.text
    # Single use is documented (v1-faq); the refusal's status is this unit's judgment, so only 4xx is asserted.
    replayed = client.post(seed.token_path, data=form, headers=seed.basic_auth_headers)
    assert 400 <= replayed.status_code < 500

    rotated = {"Authorization": f"bearer {refreshed.json()['access_token']}"}
    again = client.get(f"/o/op/2/menu/load/{menu_id}", params={"businessLocationId": location}, headers=rotated)
    assert again.status_code == 200


def test_a_to_go_order_is_confirmed_by_its_webhook(
    lightspeed_k: StartedUnit[LightspeedKSeed], receiver: WebhookReceiver
) -> None:
    client, seed = lightspeed_k.client, lightspeed_k.seed

    exchanged = client.post(
        seed.token_path,
        data={"grant_type": "refresh_token", "refresh_token": seed.refresh_token},
        headers=seed.basic_auth_headers,
    )
    assert exchanged.status_code == 200, exchanged.text
    bearer = {"Authorization": f"bearer {exchanged.json()['access_token']}"}

    location = client.get("/o/op/data/businesses", headers=bearer).json()[0]["businessLocations"][0]["id"]
    menu_id = client.get("/o/op/1/menu/list", params={"businessLocationId": location}, headers=bearer).json()[0][
        "ikentooMenuId"
    ]
    menu = client.get(f"/o/op/2/menu/load/{menu_id}", params={"businessLocationId": location}, headers=bearer)
    sku = next(
        entry["sku"] for entry in _menu_items(menu.json()["menuEntryGroups"]) if entry["sku"] == seed.item_skus[0]
    )

    # The tutorial's Part 2: a webhook endpoint, here with the documented optional Basic credentials.
    registered = client.put(
        "/o/wh/1/webhook",
        json={
            "endpointId": "MY-ENDPOINT",
            "url": receiver.url,
            "withBasicAuth": True,
            "username": "unit-k-user",
            "password": "unit-k-password",
        },
        headers=bearer,
    )
    assert registered.status_code == 200, registered.text

    reference = "unit-k-consumer-order-1"
    placed = client.post(
        "/o/op/1/order/toGo",
        json={
            "businessLocationId": location,
            "thirdPartyReference": reference,
            "endpointId": "MY-ENDPOINT",
            "customerInfo": {"firstName": "Jane"},
            "items": [{"quantity": 2, "sku": sku}],
            "takeAway": True,
        },
        headers=bearer,
    )
    # 200 "doesn't necessarily mean that it has been sent to the POS. This must be confirmed via the webhook."
    assert placed.status_code == 200, placed.text
    lightspeed_k.drain()

    (delivery,) = receiver.wait_for(1)
    body = json.loads(delivery.body)
    assert body["thirdPartyReference"] == reference
    # The status vocabulary is documented; that this order's first notification says SUCCESS is the fake's judgment.
    assert body["status"] == "SUCCESS"
    assert verify_basic_auth(delivery.headers, "unit-k-user", "unit-k-password")
