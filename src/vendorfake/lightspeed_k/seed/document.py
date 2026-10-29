"""The seed document's schema: validated whole before anything is inserted; every reference resolves inside it."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from vendorfake.core.kernel.types import UnitError, UnitErrorKind

__all__ = [
    "ENTRY_TYPES",
    "SeedBusiness",
    "SeedBusinessLocation",
    "SeedDocument",
    "SeedMenu",
    "SeedRefreshToken",
    "SeedToken",
    "parse_seed_document",
]

_SEED = ConfigDict(extra="forbid")
ENTRY_TYPES = frozenset({"menuItem", "menuDeal", "group", "menuProductModifier"})


class SeedBusinessLocation(BaseModel):
    model_config = _SEED

    id: int
    name: str = Field(min_length=1)


class SeedBusiness(BaseModel):
    model_config = _SEED

    id: int
    name: str = Field(min_length=1)
    businessLocations: list[SeedBusinessLocation] = Field(default_factory=list)


def _check_entries(entries: Any, path: str) -> None:
    if not isinstance(entries, list):
        raise ValueError(f"{path} must be a list")
    for index, entry in enumerate(entries):
        where = f"{path}[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be an object")
        # source.json: the four oneOf branches differ only by @type, which is not required
        if entry.get("@type") not in ENTRY_TYPES:
            raise ValueError(f"{where} has no @type in {sorted(ENTRY_TYPES)}")
        if "menuEntry" in entry:
            _check_entries(entry["menuEntry"], f"{where}.menuEntry")


class SeedMenu(BaseModel):
    model_config = _SEED

    ikentooMenuId: int
    menuName: str = Field(min_length=1)
    businessLocationIds: list[int] = Field(min_length=1)
    menuEntryGroups: list[dict[str, Any]]

    @field_validator("menuEntryGroups")
    @classmethod
    def _typed(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _check_entries(value, "menuEntryGroups")
        return value


class SeedToken(BaseModel):
    model_config = _SEED

    id: str = Field(min_length=1)
    access_token: str = Field(min_length=1)
    scopes: list[str] = Field(min_length=1)
    expires_in_s: int | None = None


class SeedRefreshToken(BaseModel):
    model_config = _SEED

    id: str = Field(min_length=1)
    refresh_token: str = Field(min_length=1)
    scopes: list[str] = Field(min_length=1)
    access_token_id: str = Field(min_length=1)


class SeedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    comment: list[str] | None = Field(default=None, alias="_comment")
    businesses: list[SeedBusiness] = Field(default_factory=list)
    menus: list[SeedMenu] = Field(default_factory=list)
    tokens: list[SeedToken] = Field(default_factory=list)
    refresh_tokens: list[SeedRefreshToken] = Field(default_factory=list)


def _refuse(path: str, message: str) -> UnitError:
    return UnitError(
        UnitErrorKind.INVALID_VALUE,
        detail=f"The seed document is not valid at {path}: {message}.",
        field="seed",
        info={"path": path},
    )


def _check_references(doc: SeedDocument) -> None:
    locations = {location.id for business in doc.businesses for location in business.businessLocations}
    for index, menu in enumerate(doc.menus):
        for position, location in enumerate(menu.businessLocationIds):
            if location not in locations:
                raise _refuse(f"menus[{index}].businessLocationIds[{position}]", f"location {location} is absent")
    tokens = {token.id for token in doc.tokens}
    for index, refresh in enumerate(doc.refresh_tokens):
        if refresh.access_token_id not in tokens:
            raise _refuse(
                f"refresh_tokens[{index}].access_token_id", f"access token {refresh.access_token_id!r} is absent"
            )


def parse_seed_document(raw: object) -> SeedDocument:
    """Validate a seed document, raising ``invalid_value`` on field ``seed`` with the offending path."""
    try:
        doc = SeedDocument.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        path = ".".join(str(part) for part in first.get("loc", ())) or "seed"
        raise _refuse(path, str(first.get("msg", "invalid"))) from exc
    _check_references(doc)
    return doc
