"""Turning a validated scenario into store state, at start and on ``POST /__unit/state/reset``."""

from __future__ import annotations

from vendorfake.core.kernel.types import UnitContext, UnitError, UnitErrorKind
from vendorfake.lightspeed_k.config import LightspeedKConfig
from vendorfake.lightspeed_k.entities import COL, RefreshTokenEntity, TokenEntity
from vendorfake.lightspeed_k.seed.document import SeedDocument, parse_seed_document

__all__ = ["SEED_META", "hydrate_lightspeed_k"]

SEED_META = {"seed": True, "operation_id": "SeedScenario"}


def hydrate_lightspeed_k(ctx: UnitContext, seed: object, config: LightspeedKConfig) -> SeedDocument | None:
    """Load ``seed`` into ``ctx.store``; ``None`` loads nothing and is legal."""
    if seed is None:
        return None
    doc = parse_seed_document(seed)
    _check_scopes(doc, config)
    for business in doc.businesses:
        ctx.store.collection(COL.businesses).insert(
            {"id": str(business.id), "document": business.model_dump()}, SEED_META
        )
    for menu in doc.menus:
        document = {
            "menuName": menu.menuName,
            "ikentooMenuId": menu.ikentooMenuId,
            "menuEntryGroups": menu.menuEntryGroups,
            "richDataMissing": False,
            "conditionalTaxRules": False,
        }
        row = {
            "id": str(menu.ikentooMenuId),
            "business_location_ids": list(menu.businessLocationIds),
            "document": document,
        }
        ctx.store.collection(COL.menus).insert(row, SEED_META)
    now = int(ctx.clock.now())
    for token in doc.tokens:
        ttl_s = config.access_token_ttl_s if token.expires_in_s is None else token.expires_in_s
        entity = TokenEntity(
            id=token.id,
            access_token=token.access_token,
            client_id=config.client_id,
            scopes=tuple(token.scopes),
            expires_at_ms=now + ttl_s * 1000,
            created_at_ms=now,
        )
        ctx.store.collection(COL.tokens).insert(entity.to_entity(), SEED_META)
    for refresh in doc.refresh_tokens:
        stored = RefreshTokenEntity(
            id=refresh.id,
            refresh_token=refresh.refresh_token,
            client_id=config.client_id,
            scopes=tuple(refresh.scopes),
            expires_at_ms=now + config.refresh_token_ttl_ms,
            access_token_id=refresh.access_token_id,
            created_at_ms=now,
        )
        ctx.store.collection(COL.refresh_tokens).insert(stored.to_entity(), SEED_META)
    return doc


def _check_scopes(doc: SeedDocument, config: LightspeedKConfig) -> None:
    rows = [("tokens", index, row.scopes) for index, row in enumerate(doc.tokens)]
    rows += [("refresh_tokens", index, row.scopes) for index, row in enumerate(doc.refresh_tokens)]
    for collection, index, scopes in rows:
        unknown = [scope for scope in scopes if scope not in config.scopes]
        if unknown:
            raise UnitError(
                UnitErrorKind.INVALID_VALUE,
                detail=f"The seed document is not valid at {collection}[{index}].scopes: {unknown} not in {list(config.scopes)}.",
                field="seed",
                info={"path": f"{collection}[{index}].scopes"},
            )
