"""One map defines Clover's event-key vocabulary; every other list derives
from it, so a key added there reaches the mapper, the stand-in's default
keys, the seeded subscriber, ``seed.event_types`` and the seed page at once
(konyklabs/roadmap#175)."""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.clover.harness import harness
from vendorfake.clover.events import CHANGE_TYPES, CLOVER_EVENT_TYPES, EVENT_KEYS
from vendorfake.clover.model.webhooks import ALL_EVENT_KEYS, RegisterSubscriptionRequest
from vendorfake.clover.seed import constants as c
from vendorfake.testing import unit

ROOT = Path(__file__).resolve().parents[3]


def test_every_key_list_derives_from_event_keys() -> None:
    assert ALL_EVENT_KEYS == tuple(EVENT_KEYS.values())
    assert "IM" in ALL_EVENT_KEYS
    assert CLOVER_EVENT_TYPES == tuple(f"{k}:{change}" for k in ALL_EVENT_KEYS for change in CHANGE_TYPES)
    assert RegisterSubscriptionRequest.model_validate({"url": "https://x.test"}).eventKeys == ALL_EVENT_KEYS


def test_the_seeded_subscriber_covers_every_key() -> None:
    for h in harness():
        rows = h.api.get("/__clover/webhooks/subscriptions").json()["subscriptions"]
        (seeded,) = [row for row in rows if row["id"] == c.SEED_WEBHOOK_SUBSCRIPTION_ID]
        assert seeded["eventKeys"] == list(ALL_EVENT_KEYS)


def test_the_driver_vocabulary_is_the_mappers() -> None:
    with unit("clover") as clover:
        assert clover.seed.event_types == CLOVER_EVENT_TYPES
        for key in ALL_EVENT_KEYS:
            clover.subscribe(f"http://127.0.0.1:1/{key}", [f"{key}:*"], "code")
        clover.subscribe("http://127.0.0.1:1/im", ["IM:*"], "code")


def test_the_seed_page_row_names_every_key() -> None:
    page = ROOT / "docs" / "concepts" / "seed.md"
    text = page.read_text(encoding="utf-8")
    start = text.index("### Clover")
    end = text.index("\n### ", start + 1)
    (row,) = [line for line in text[start:end].splitlines() if line.startswith("| Event types |")]
    assert re.findall(r"`([A-Z]+):`", row) == list(ALL_EVENT_KEYS), f"{page}: the Clover 'Event types' row: {row}"
