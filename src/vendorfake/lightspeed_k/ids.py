"""lightspeed-k identifiers over :class:`~vendorfake.core.rand.ids.IdStream`: one stream, reseeded at hydrate."""

from __future__ import annotations

from vendorfake.core.rand.ids import HEX, MIXED_ALNUM, IdStream

_DIGITS = "0123456789"

__all__ = ["LightspeedKIds"]


class LightspeedKIds(IdStream):
    """UUID-shaped tokens and six-character codes."""

    __slots__ = ()

    # DOCUMENTED v1-overview: both token samples are version-4-shaped UUIDs
    def uuid(self) -> str:
        hexes = self._pick(HEX, 30)
        variant = "89ab"[self._rng.int(4)]
        return f"{hexes[0:8]}-{hexes[8:12]}-4{hexes[12:15]}-{variant}{hexes[15:18]}-{hexes[18:30]}"

    # DOCUMENTED v1-overview: the code samples GyIpgM and Bp68Nr
    def code(self) -> str:
        return self._pick(MIXED_ALNUM, 6)

    # DOCUMENTED source.json: the examples' A17700.3 shape
    def account_identifier(self) -> str:
        return "A" + self._pick(_DIGITS, 5) + "." + str(1 + self._rng.int(9))
