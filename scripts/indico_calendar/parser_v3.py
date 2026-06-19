"""Parser for Indico v3 pages that embed timetableArgs data."""

from __future__ import annotations

import json
import re

from .core import TimetableItem, clean_text, duration_text_from_minutes, sort_items


def indico_date_time(value: object) -> tuple[str, str, str | None]:
    if not isinstance(value, dict):
        return "", "", None
    date = clean_text(value.get("date"))
    time_value = clean_text(value.get("time"))
    if re.fullmatch(r"\d{2}:\d{2}:\d{2}", time_value):
        time_value = time_value[:5]
    timezone = clean_text(value.get("tz")) or None
    return date, time_value, timezone


def person_label(person: object) -> str:
    if not isinstance(person, dict):
        return clean_text(person)
    name = clean_text(person.get("name"))
    if not name:
        name = " ".join(
            part
            for part in [clean_text(person.get("firstName")), clean_text(person.get("familyName"))]
            if part
        )
    affiliation = clean_text(person.get("affiliation"))
    if name and affiliation:
        return f"{name} ({affiliation})"
    return name


def people_text(people: object) -> str:
    if not isinstance(people, list):
        return ""
    return ", ".join(label for label in (person_label(person) for person in people) if label)


def entry_location(entry: dict[str, object], parent: dict[str, object] | None = None) -> str:
    room = clean_text(entry.get("roomFullname") or entry.get("room"))
    location = clean_text(entry.get("location"))
    if (not room or not location) and parent is not None:
        room = room or clean_text(parent.get("roomFullname") or parent.get("room"))
        location = location or clean_text(parent.get("location"))
    if room and location:
        if location in room:
            return room
        return f"{room}, {location}"
    return room or location


def extract_v3_timetable_args(page: str) -> tuple[dict[str, object], dict[str, object]] | None:
    marker = "var timetableArgs = ["
    start = page.find(marker)
    if start == -1:
        return None

    decoder = json.JSONDecoder()
    position = start + len(marker)
    values: list[object] = []
    try:
        while len(values) < 3:
            while position < len(page) and page[position] in " \t\r\n,":
                position += 1
            value, position = decoder.raw_decode(page, position)
            values.append(value)
    except json.JSONDecodeError:
        return None

    if len(values) < 3 or not isinstance(values[1], dict) or not isinstance(values[2], dict):
        return None
    return values[1], values[2]


def v3_entry_to_item(
    entry: dict[str, object],
    *,
    kind: str,
    parent: dict[str, object] | None = None,
) -> TimetableItem | None:
    date, time_value, timezone = indico_date_time(entry.get("startDate"))
    title = clean_text(entry.get("title") or entry.get("slotTitle"))
    if not (date and time_value and title):
        return None
    if kind == "contribution":
        speaker = people_text(entry.get("presenters"))
    elif kind == "session":
        speaker = people_text(entry.get("conveners"))
    else:
        speaker = ""
    session = ""
    if parent is not None:
        session = clean_text(parent.get("title") or parent.get("slotTitle"))
    return TimetableItem(
        date=date,
        kind=kind,
        time=time_value,
        title=title,
        duration_text=duration_text_from_minutes(entry.get("duration")),
        speaker=speaker,
        timezone=timezone,
        location=entry_location(entry, parent),
        session=session,
    )


def append_v3_entry(
    items: list[TimetableItem],
    entry: object,
    *,
    include_breaks: bool,
    parent: dict[str, object] | None = None,
) -> None:
    if not isinstance(entry, dict):
        return

    entry_type = clean_text(entry.get("entryType"))
    if entry_type == "Session":
        child_entries = entry.get("entries")
        if isinstance(child_entries, dict) and child_entries:
            for child in child_entries.values():
                append_v3_entry(items, child, include_breaks=include_breaks, parent=entry)
            return
        item = v3_entry_to_item(entry, kind="session", parent=parent)
        if item is not None:
            items.append(item)
        return

    if entry_type == "Contribution":
        item = v3_entry_to_item(entry, kind="contribution", parent=parent)
        if item is not None:
            items.append(item)
        return

    if entry_type == "Break" and include_breaks:
        item = v3_entry_to_item(entry, kind="break", parent=parent)
        if item is not None:
            items.append(item)


def parse_v3_items(page: str, include_breaks: bool) -> list[TimetableItem]:
    timetable_args = extract_v3_timetable_args(page)
    if timetable_args is None:
        return []
    days, _conference = timetable_args
    items: list[TimetableItem] = []
    for day in days.values():
        if isinstance(day, dict):
            entries = day.values()
        elif isinstance(day, list):
            entries = day
        else:
            continue
        for entry in entries:
            append_v3_entry(items, entry, include_breaks=include_breaks)
    return sort_items(items)
