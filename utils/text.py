from __future__ import annotations

from html import escape


def h(value: object | None) -> str:
    return escape("" if value is None else str(value), quote=False)
