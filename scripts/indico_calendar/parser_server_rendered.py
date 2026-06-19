"""Parser for server-rendered Indico 3 timetable markup."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from .core import (
    TimetableItem,
    clean_speaker_text,
    clean_text,
    clean_timetable_title,
    duration_text_from_clock_times,
    normalize_clock_time,
    sort_items,
)


class ServerRenderedTimetableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.date: str | None = None
        self.stack: list[dict[str, object]] = []
        self.field: str | None = None
        self.field_depth = 0
        self.items: list[TimetableItem] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k: v or "" for k, v in attrs_list}
        classes = attrs.get("class", "")
        item_classes = set(classes.split())

        if tag == "li":
            day_match = re.fullmatch(r"day-(\d{4}-\d{2}-\d{2})", attrs.get("id", ""))
            if day_match:
                self.date = day_match.group(1)

            if "timetable-item" in item_classes:
                parent_session = ""
                if self.stack and self.stack[-1].get("kind") == "session":
                    parent_session = clean_text(self.stack[-1].get("title"))
                    self.stack[-1]["children"] = int(self.stack[-1].get("children", 0)) + 1
                kind = "session"
                if "timetable-break" in item_classes:
                    kind = "break"
                elif "timetable-contrib" in item_classes:
                    kind = "contribution"
                self.stack.append(
                    {
                        "date": self.date or "",
                        "kind": kind,
                        "time": "",
                        "end_time": "",
                        "title": "",
                        "duration": "",
                        "speaker": "",
                        "session": parent_session,
                        "children": 0,
                        "li_depth": 1,
                    }
                )
                return
            if self.stack:
                self.stack[-1]["li_depth"] = int(self.stack[-1].get("li_depth", 1)) + 1

        if not self.stack:
            return

        if self.field is not None:
            self.field_depth += 1
            return

        new_field = None
        if tag == "span" and "start-time" in item_classes:
            new_field = "time"
        elif tag == "span" and "end-time" in item_classes:
            new_field = "end_time"
        elif tag == "span" and "timetable-title" in item_classes:
            new_field = "title"
        elif tag == "span" and "timetable-duration" in item_classes:
            new_field = "duration"
        elif tag == "div" and "speaker-list" in item_classes:
            new_field = "speaker"

        if new_field is not None:
            self.field = new_field
            self.field_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self.stack and self.field is not None:
            self.field_depth -= 1
            if self.field_depth <= 0:
                self.field = None
                self.field_depth = 0

        if tag == "li" and self.stack:
            self.stack[-1]["li_depth"] = int(self.stack[-1].get("li_depth", 1)) - 1
            if int(self.stack[-1].get("li_depth", 0)) <= 0:
                self.finish_item(self.stack.pop())

    def handle_data(self, data: str) -> None:
        if self.stack and self.field is not None:
            self.stack[-1][self.field] = str(self.stack[-1].get(self.field, "")) + data

    def finish_item(self, raw: dict[str, object]) -> None:
        cleaned = {key: clean_text(value) for key, value in raw.items()}
        if cleaned.get("kind") == "session" and int(raw.get("children", 0)) > 0:
            return

        date = cleaned.get("date", "")
        time_value = normalize_clock_time(cleaned.get("time", ""))
        title = clean_timetable_title(cleaned.get("title", ""))
        if not (date and time_value and title):
            return

        duration_text = clean_text(raw.get("duration"))
        if not duration_text:
            duration_text = duration_text_from_clock_times(time_value, normalize_clock_time(cleaned.get("end_time", "")))
        speaker = clean_speaker_text(cleaned.get("speaker", ""))
        self.items.append(
            TimetableItem(
                date=date,
                kind=cleaned.get("kind", "session"),
                time=time_value,
                title=title,
                duration_text=duration_text,
                speaker=speaker,
                session=cleaned.get("session", ""),
            )
        )


def parse_server_rendered_items(page: str, include_breaks: bool) -> list[TimetableItem]:
    parser = ServerRenderedTimetableParser()
    parser.feed(page)
    items = parser.items
    if not include_breaks:
        items = [item for item in items if item.kind != "break"]
    return sort_items(items)
