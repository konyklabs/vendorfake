"""Every id and credential the shipped scenario contains; ``tests/unit/lightspeed_k/test_seed.py`` asserts each."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

__all__ = [
    "DEFAULT_SEED_PATH",
    "SEED_ACCESS_TOKEN",
    "SEED_BASIC_AUTH",
    "SEED_BUSINESS_ID",
    "SEED_BUSINESS_LOCATION_ID",
    "SEED_BUSINESS_LOCATION_NAME",
    "SEED_BUSINESS_NAME",
    "SEED_CLIENT_ID",
    "SEED_CLIENT_SECRET",
    "SEED_EXAMPLE_ENDPOINT_ID",
    "SEED_FINANCIAL_ONLY_ACCESS_TOKEN",
    "SEED_GROUP_ID",
    "SEED_ITEM_SKUS",
    "SEED_MENU_ID",
    "SEED_MENU_NAME",
    "SEED_REDIRECT_URI",
    "SEED_REFRESH_TOKEN",
    "SEED_UNKNOWN_SKU",
]

SEED_CLIENT_ID = "unit-lightspeed-k-client-id"
SEED_CLIENT_SECRET = "unit-lightspeed-k-client-secret"
SEED_REDIRECT_URI = "https://consumer.example/callback"
SEED_ACCESS_TOKEN = "unit-lightspeed-k-access-token-full"
SEED_REFRESH_TOKEN = "unit-lightspeed-k-refresh-token-full"
SEED_FINANCIAL_ONLY_ACCESS_TOKEN = "unit-lightspeed-k-access-token-financial"
SEED_BUSINESS_ID = 100000000001
SEED_BUSINESS_NAME = "Unit K Bistro"
SEED_BUSINESS_LOCATION_ID = 100000000101
SEED_BUSINESS_LOCATION_NAME = "Unit K Bistro - Main Street"
SEED_MENU_ID = 100000000201
SEED_MENU_NAME = "Unit Lunch Menu"
SEED_GROUP_ID = "100000000301"
SEED_ITEM_SKUS = ("UNITK-001", "UNITK-002")
SEED_UNKNOWN_SKU = "UNITK-404"
SEED_EXAMPLE_ENDPOINT_ID = "UNIT-K-EXAMPLE-ENDPOINT"
SEED_BASIC_AUTH = "Basic dW5pdC1saWdodHNwZWVkLWstY2xpZW50LWlkOnVuaXQtbGlnaHRzcGVlZC1rLWNsaWVudC1zZWNyZXQ="
DEFAULT_SEED_PATH: Path = Path(str(resources.files("vendorfake.lightspeed_k") / "seed" / "default.seed.json"))
