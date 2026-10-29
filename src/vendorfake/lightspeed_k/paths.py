"""Path constants, one per route; ``tests/unit/test_paths_drift.py`` checks them against the router."""

from __future__ import annotations

__all__ = [
    "APE_CREATE_WEBHOOK_OO",
    "APE_DELETE_WEBHOOK_ENDPOINT",
    "APE_GET_MENU_BY_ID_V2",
    "APE_GET_WEBHOOK_OO",
    "APE_LOAD_MENUS",
    "APE_LOOKUP_BUSINESSES",
    "APE_PLACE_TO_GO_ORDER",
    "APE_UPDATE_WEBHOOK_OO",
    "OAUTH_AUTHORIZE",
    "OAUTH_TOKEN",
]

OAUTH_AUTHORIZE = "/oauth/authorize"
OAUTH_TOKEN = "/oauth/token"
APE_LOOKUP_BUSINESSES = "/o/op/data/businesses"
APE_LOAD_MENUS = "/o/op/1/menu/list"
APE_GET_MENU_BY_ID_V2 = "/o/op/2/menu/load/{menuId}"
APE_PLACE_TO_GO_ORDER = "/o/op/1/order/toGo"
APE_CREATE_WEBHOOK_OO = "/o/wh/1/webhook"
APE_UPDATE_WEBHOOK_OO = "/o/wh/1/webhook"
APE_GET_WEBHOOK_OO = "/o/wh/1/webhook/{endpointId}"
APE_DELETE_WEBHOOK_ENDPOINT = "/o/wh/1/webhook/{endpointId}"
