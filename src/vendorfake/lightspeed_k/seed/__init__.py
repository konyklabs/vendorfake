"""The shipped lightspeed-k scenario: one business and location, one V2 menu, a full and a financial-only
token, one refresh token. :mod:`.constants` names every value; :mod:`.document` is the schema."""

from __future__ import annotations

from vendorfake.lightspeed_k.seed import constants
from vendorfake.lightspeed_k.seed.document import SeedDocument, parse_seed_document
from vendorfake.lightspeed_k.seed.hydrate import SEED_META, hydrate_lightspeed_k

__all__ = ["SEED_META", "SeedDocument", "constants", "hydrate_lightspeed_k", "parse_seed_document"]
