"""Path constants, one per route; ``tests/unit/test_paths_drift.py`` checks them against the router."""

from __future__ import annotations

__all__ = ["APE_GET_MENU_BY_ID_V2", "APE_LOAD_MENUS", "APE_LOOKUP_BUSINESSES", "OAUTH_AUTHORIZE", "OAUTH_TOKEN"]

OAUTH_AUTHORIZE = "/oauth/authorize"
OAUTH_TOKEN = "/oauth/token"
APE_LOOKUP_BUSINESSES = "/o/op/data/businesses"
APE_LOAD_MENUS = "/o/op/1/menu/list"
APE_GET_MENU_BY_ID_V2 = "/o/op/2/menu/load/{menuId}"
