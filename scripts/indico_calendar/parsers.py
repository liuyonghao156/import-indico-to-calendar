"""Dispatch across supported Indico timetable parser modes."""

from __future__ import annotations

from .core import TimetableItem
from .parser_classic import parse_classic_items
from .parser_server_rendered import parse_server_rendered_items
from .parser_v3 import parse_v3_items


def parse_items(page: str, include_breaks: bool) -> list[TimetableItem]:
    items = parse_classic_items(page, include_breaks)
    if items:
        return items
    items = parse_v3_items(page, include_breaks)
    if items:
        return items
    return parse_server_rendered_items(page, include_breaks)
