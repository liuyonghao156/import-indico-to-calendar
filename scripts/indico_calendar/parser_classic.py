"""Parser for classic Indico timetable rows."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from .core import TimetableItem, clean_text, sort_items


class IndicoTimetableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.date: str | None = None
        self.item: dict[str, str] | None = None
        self.field: str | None = None
        self.field_depth = 0
        self.items: list[TimetableItem] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k: v or "" for k, v in attrs_list}
        if tag == "a" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", attrs.get("name", "")):
            self.date = attrs["name"]

        if tag == "li":
            classes = attrs.get("class", "")
            if "meetingContrib" in classes or "breakListItem" in classes:
                self.item = {
                    "date": self.date or "",
                    "kind": "break" if "breakListItem" in classes else "contrib",
                    "time": "",
                    "title": "",
                    "duration": "",
                    "speaker": "",
                }

        if self.item is None:
            return

        if self.field is not None:
            self.field_depth += 1
            return

        classes = attrs.get("class", "")
        new_field = None
        if tag == "span" and "subEventLevelTime" in classes:
            new_field = "time"
        elif tag == "span" and "subEventLevelTitle" in classes:
            new_field = "title"
        elif tag == "em":
            new_field = "duration"
        elif tag == "span" and attrs.get("itemprop") == "performers":
            new_field = "speaker"

        if new_field is not None:
            self.field = new_field
            self.field_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self.item is not None and self.field is not None:
            self.field_depth -= 1
            if self.field_depth <= 0:
                self.field = None
                self.field_depth = 0

        if self.item is not None and tag == "li":
            cleaned = {k: clean_text(v) for k, v in self.item.items()}
            if cleaned["date"] and cleaned["time"] and cleaned["title"] and cleaned["duration"]:
                self.items.append(
                    TimetableItem(
                        date=cleaned["date"],
                        kind=cleaned["kind"],
                        time=cleaned["time"],
                        title=cleaned["title"],
                        duration_text=cleaned["duration"],
                        speaker=cleaned["speaker"],
                    )
                )
            self.item = None
            self.field = None
            self.field_depth = 0

    def handle_data(self, data: str) -> None:
        if self.item is not None and self.field is not None:
            self.item[self.field] += data


def parse_classic_items(page: str, include_breaks: bool) -> list[TimetableItem]:
    parser = IndicoTimetableParser()
    parser.feed(page)
    items = parser.items
    if not include_breaks:
        items = [item for item in items if item.kind != "break"]
    return sort_items(items)
