"""Extract detailed Indico timetables and import/write Apple Calendar events."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


LOCATION_FALLBACK = ""
TIMEZONE_RE = re.compile(
    r"\b(?:(?:Africa|America|Antarctica|Arctic|Asia|Atlantic|Australia|Europe|Indian|Pacific|US)/"
    r"[A-Za-z0-9_+./-]+|UTC|GMT)\b"
)


@dataclass
class TimetableItem:
    date: str
    kind: str
    time: str
    title: str
    duration_text: str
    speaker: str = ""
    timezone: str | None = None
    location: str = ""
    session: str = ""

    @property
    def duration_minutes(self) -> int:
        text = self.duration_text.strip().lower()
        classic = re.fullmatch(r"\s*(?:(\d+)h)?\s*(?:(\d+))?\s*'\s*", text)
        if classic:
            return int(classic.group(1) or 0) * 60 + int(classic.group(2) or 0)
        modern = re.fullmatch(r"\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*", text)
        if modern and (modern.group(1) or modern.group(2)):
            return int(modern.group(1) or 0) * 60 + int(modern.group(2) or 0)
        raise ValueError(f"Unsupported duration {self.duration_text!r} for {self.title!r}")


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(html.unescape(str(value)).split())


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


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Codex Indico importer)"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def inspect_ics(url: str) -> tuple[str, int]:
    text = fetch_text(url)
    return url, len(re.findall(r"^BEGIN:VEVENT\b", text, flags=re.MULTILINE))


def normalize_event_url(url: str) -> str:
    parsed = urlparse(url)
    match = re.search(r"(/event/\d+)", parsed.path)
    if not match:
        raise ValueError(f"Could not find /event/<id> in URL: {url}")
    return f"{parsed.scheme}://{parsed.netloc}{match.group(1)}"


def timetable_url(url: str) -> str:
    return normalize_event_url(url).rstrip("/") + "/timetable/"


def event_ics_url(url: str) -> str:
    return normalize_event_url(url).rstrip("/") + "/event.ics"


def fetch_timetable_page(preferred_url: str, fallback_url: str) -> tuple[str, str]:
    try:
        return preferred_url, fetch_text(preferred_url)
    except HTTPError as exc:
        if exc.code != 404:
            raise
    return fallback_url, fetch_text(fallback_url)


def duration_text_from_minutes(minutes: object) -> str:
    try:
        total_minutes = max(0, int(round(float(minutes))))
    except (TypeError, ValueError):
        total_minutes = 0
    return f"{total_minutes}'"


def normalize_clock_time(value: str) -> str:
    match = re.search(r"\b(\d{1,2}):(\d{2})(?:\s*([AP])\.?M\.?)?\b", value, flags=re.IGNORECASE)
    if not match:
        return ""
    hour = int(match.group(1))
    marker = (match.group(3) or "").upper()
    if marker == "A" and hour == 12:
        hour = 0
    elif marker == "P" and hour != 12:
        hour += 12
    return f"{hour:02d}:{match.group(2)}"


def duration_text_from_clock_times(start: str, end: str) -> str:
    start_match = re.fullmatch(r"(\d{2}):(\d{2})", start)
    end_match = re.fullmatch(r"(\d{2}):(\d{2})", end)
    if not (start_match and end_match):
        return "0'"
    start_minutes = int(start_match.group(1)) * 60 + int(start_match.group(2))
    end_minutes = int(end_match.group(1)) * 60 + int(end_match.group(2))
    if end_minutes < start_minutes:
        end_minutes += 24 * 60
    return duration_text_from_minutes(end_minutes - start_minutes)


def clean_speaker_text(value: str) -> str:
    value = clean_text(value)
    return re.sub(r"^Speakers?\s*:\s*", "", value, flags=re.IGNORECASE)


def clean_timetable_title(value: str) -> str:
    value = clean_text(value)
    return re.sub(r"\s*\((?:\d+\s*m|(?:(?:\d+)\s*h)?\s*(?:\d+)?\s*')\)\s*$", "", value)


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


def sort_items(items: list[TimetableItem]) -> list[TimetableItem]:
    return sorted(items, key=lambda item: (item.date, item.time, item.title))


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


def parse_server_rendered_items(page: str, include_breaks: bool) -> list[TimetableItem]:
    parser = ServerRenderedTimetableParser()
    parser.feed(page)
    items = parser.items
    if not include_breaks:
        items = [item for item in items if item.kind != "break"]
    return sort_items(items)


def parse_items(page: str, include_breaks: bool) -> list[TimetableItem]:
    parser = IndicoTimetableParser()
    parser.feed(page)
    items = parser.items
    if not items:
        items = parse_v3_items(page, include_breaks)
    if not items:
        return parse_server_rendered_items(page, include_breaks)
    if not include_breaks:
        items = [item for item in items if item.kind != "break"]
    return sort_items(items)


def detect_source_timezone(
    *pages: str, override: str | None, items: list[TimetableItem] | None = None
) -> ZoneInfo:
    if override:
        return ZoneInfo(override)
    for item in items or []:
        if item.timezone:
            try:
                return ZoneInfo(item.timezone)
            except Exception:
                pass
    for page in pages:
        for option in re.findall(r"<option\b[^>]*>", html.unescape(page), flags=re.IGNORECASE):
            if "selected" not in option:
                continue
            match = TIMEZONE_RE.search(option)
            if match:
                try:
                    return ZoneInfo(match.group(0))
                except Exception:
                    pass
    for page in pages:
        for match in TIMEZONE_RE.findall(html.unescape(page)):
            try:
                return ZoneInfo(match)
            except Exception:
                pass
    raise ValueError("Could not detect source timezone; pass --source-timezone")


def detect_local_timezone() -> ZoneInfo:
    if "TZ" in os.environ:
        try:
            return ZoneInfo(os.environ["TZ"])
        except Exception:
            pass
    localtime = Path("/etc/localtime")
    try:
        target = localtime.resolve()
        marker = "zoneinfo/"
        if marker in str(target):
            return ZoneInfo(str(target).split(marker, 1)[1])
    except Exception:
        pass
    # Fallback preserves the current offset but may not model future DST transitions.
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def zoneinfo_name(tz: ZoneInfo) -> str:
    return getattr(tz, "key", str(tz))


def source_timezone_for_item(item: TimetableItem, fallback: ZoneInfo) -> ZoneInfo:
    if item.timezone:
        try:
            return ZoneInfo(item.timezone)
        except Exception:
            pass
    return fallback


def item_datetimes(
    item: TimetableItem, source_tz: ZoneInfo, local_tz: ZoneInfo
) -> tuple[datetime, datetime, datetime, datetime]:
    item_source_tz = source_timezone_for_item(item, source_tz)
    time_value = item.time
    if re.fullmatch(r"\d{2}:\d{2}", time_value):
        time_value += ":00"
    start_source = datetime.fromisoformat(f"{item.date}T{time_value}").replace(tzinfo=item_source_tz)
    end_source = start_source + timedelta(minutes=item.duration_minutes)
    return start_source, end_source, start_source.astimezone(local_tz), end_source.astimezone(local_tz)


def apple_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def fold_ics_line(line: str) -> str:
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    parts: list[str] = []
    current = ""
    for char in line:
        candidate = current + char
        if len(candidate.encode("utf-8")) > 73:
            parts.append(current)
            current = " " + char
        else:
            current = candidate
    parts.append(current)
    return "\r\n".join(parts)


def event_title(item: TimetableItem, prefix: str) -> str:
    return f"{prefix} {item.title}".strip()


def event_description(
    item: TimetableItem,
    source_url: str,
    start_source: datetime,
    end_source: datetime,
    source_tz_name: str,
) -> str:
    desc = (
        "Indico timetable event. "
        f"Published time: {start_source:%Y-%m-%d %H:%M}-{end_source:%H:%M} {source_tz_name}."
    )
    if item.session:
        desc += f" Session: {item.session}."
    if item.speaker:
        desc += f" Speaker: {item.speaker}."
    desc += f" Source: {source_url}"
    return desc


def write_ics(
    items: list[TimetableItem],
    output: Path,
    source_url: str,
    source_tz: ZoneInfo,
    location: str,
    prefix: str,
) -> None:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Codex//Indico Timetable Import//EN",
        "CALSCALE:GREGORIAN",
    ]
    timestamp = datetime.now(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    for index, item in enumerate(items, start=1):
        start_source, end_source, _, _ = item_datetimes(item, source_tz, source_tz)
        item_tz = source_timezone_for_item(item, source_tz)
        source_tz_name = zoneinfo_name(item_tz)
        uid_seed = f"{source_url}|{item.date}|{item.time}|{item.title}|{index}".encode("utf-8")
        uid = f"indico-{hashlib.sha1(uid_seed).hexdigest()}@codex.local"
        desc = event_description(item, source_url, start_source, end_source, source_tz_name)
        location_value = item.location or location
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{timestamp}",
                f"DTSTART;TZID={source_tz_name}:{start_source:%Y%m%dT%H%M%S}",
                f"DTEND;TZID={source_tz_name}:{end_source:%Y%m%dT%H%M%S}",
                f"SUMMARY:{ics_escape(event_title(item, prefix))}",
                f"LOCATION:{ics_escape(location_value)}",
                f"DESCRIPTION:{ics_escape(desc)}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    output.write_text("\r\n".join(fold_ics_line(line) for line in lines) + "\r\n", encoding="utf-8")


def list_calendars() -> int:
    script = textwrap.dedent(
        """
        tell application "Calendar"
          set out to ""
          repeat with i from 1 to count of calendars
            set c to calendar i
            set lineText to i & " | " & (name of c as text)
            try
              set lineText to lineText & " | writable=" & (writable of c as text)
            on error
              set lineText to lineText & " | writable=?"
            end try
            try
              set lineText to lineText & " | description=" & (description of c as text)
            on error
              set lineText to lineText & " | description=?"
            end try
            set out to out & lineText & linefeed
          end repeat
          return out
        end tell
        """
    ).strip()
    result = subprocess.run(["osascript", "-e", script], text=True, capture_output=True, check=False)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    return result.returncode


def build_import_script(
    items: list[TimetableItem],
    source_url: str,
    source_tz: ZoneInfo,
    local_tz: ZoneInfo,
    calendar_index: int,
    location: str,
    prefix: str,
    duplicate_check: bool,
) -> str:
    lines = [
        "on makeDate(y, mo, da, hh, mi)",
        "  set d to current date",
        "  set year of d to y",
        "  set month of d to mo",
        "  set day of d to da",
        "  set hours of d to hh",
        "  set minutes of d to mi",
        "  set seconds of d to 0",
        "  return d",
        "end makeDate",
        "",
        'tell application "Calendar"',
        f"  set targetCal to calendar {calendar_index}",
        "  set createdCount to 0",
        "  set skippedCount to 0",
    ]
    for item in items:
        start_source, end_source, start_local, end_local = item_datetimes(item, source_tz, local_tz)
        item_tz = source_timezone_for_item(item, source_tz)
        source_tz_name = zoneinfo_name(item_tz)
        title = event_title(item, prefix)
        desc = event_description(item, source_url, start_source, end_source, source_tz_name)
        location_value = item.location or location
        lines.extend(
            [
                f"  set theSummary to {apple_quote(title)}",
                (
                    "  set startDate to my makeDate"
                    f"({start_local.year}, {start_local.month}, {start_local.day},"
                    f" {start_local.hour}, {start_local.minute})"
                ),
                (
                    "  set endDate to my makeDate"
                    f"({end_local.year}, {end_local.month}, {end_local.day},"
                    f" {end_local.hour}, {end_local.minute})"
                ),
                f"  set theLocation to {apple_quote(location_value)}",
                f"  set theDescription to {apple_quote(desc)}",
            ]
        )
        if duplicate_check:
            lines.extend(
                [
                    "  set duplicateFound to false",
                    "  try",
                    "    set matches to every event of targetCal whose summary is theSummary and start date is startDate",
                    "    if (count of matches) > 0 then set duplicateFound to true",
                    "  end try",
                    "  if duplicateFound then",
                    "    set skippedCount to skippedCount + 1",
                    "  else",
                    (
                        "    make new event at end of events of targetCal with properties "
                        "{summary:theSummary, start date:startDate, end date:endDate, "
                        "location:theLocation, description:theDescription}"
                    ),
                    "    set createdCount to createdCount + 1",
                    "  end if",
                ]
            )
        else:
            lines.extend(
                [
                    (
                        "  make new event at end of events of targetCal with properties "
                        "{summary:theSummary, start date:startDate, end date:endDate, "
                        "location:theLocation, description:theDescription}"
                    ),
                    "  set createdCount to createdCount + 1",
                ]
            )
    lines.extend(
        [
            '  return "created=" & createdCount & ", skipped=" & skippedCount & ", calendar=" & (name of targetCal as text)',
            "end tell",
        ]
    )
    return "\n".join(lines) + "\n"


def import_to_calendar(script: str) -> int:
    result = subprocess.run(["osascript"], input=script, text=True, capture_output=True, check=False)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    return result.returncode


def print_summary(items: list[TimetableItem], source_tz: ZoneInfo, local_tz: ZoneInfo) -> None:
    print(f"items={len(items)}")
    print(f"source_timezone={zoneinfo_name(source_tz)}")
    print(f"local_timezone={zoneinfo_name(local_tz)}")
    if not items:
        return
    for label, item in [("first", items[0]), ("last", items[-1])]:
        start_source, end_source, start_local, end_local = item_datetimes(item, source_tz, local_tz)
        print(
            f"{label}={item.title} | "
            f"{start_source:%Y-%m-%d %H:%M}-{end_source:%H:%M} source | "
            f"{start_local:%Y-%m-%d %H:%M}-{end_local:%H:%M} local"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", help="Indico event URL, e.g. https://host/event/123/overview")
    parser.add_argument("--list-calendars", action="store_true", help="List Apple Calendar indexes")
    parser.add_argument("--dry-run", action="store_true", help="Parse and summarize without writing")
    parser.add_argument("--import", dest="do_import", action="store_true", help="Import to Apple Calendar")
    parser.add_argument("--calendar-index", type=int, help="AppleScript Calendar calendar index")
    parser.add_argument("--output", type=Path, help="Write detailed ICS file")
    parser.add_argument("--no-breaks", action="store_true", help="Skip breakListItem entries")
    parser.add_argument("--prefix", default="Indico:", help="Prefix for imported event titles")
    parser.add_argument("--location", default=LOCATION_FALLBACK, help="Event location")
    parser.add_argument("--source-timezone", help="Override timetable timezone, e.g. Europe/Rome")
    parser.add_argument("--no-duplicate-check", action="store_true", help="Do not skip existing same-summary/start events")
    parser.add_argument("--show-official-ics", action="store_true", help="Print and inspect the likely top-level event.ics URL")
    parser.add_argument("--dump-detail-html", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.list_calendars:
        return list_calendars()
    if not args.url:
        parser.error("url is required unless --list-calendars is used")

    normalized_url = normalize_event_url(args.url)
    detail_url = timetable_url(args.url)
    if args.show_official_ics:
        official_url = event_ics_url(args.url)
        try:
            _, event_count = inspect_ics(official_url)
            print(f"official_event_ics={official_url}")
            print(f"official_event_ics_vevents={event_count}")
        except Exception as exc:
            print(f"official_event_ics={official_url}")
            print(f"official_event_ics_error={exc}")

    detail_url, page = fetch_timetable_page(detail_url, normalized_url.rstrip("/") + "/")
    if args.dump_detail_html:
        args.dump_detail_html.write_text(page, encoding="utf-8")
        print(f"dumped_detail_html={args.dump_detail_html}")
    try:
        overview_page = fetch_text(normalized_url + "/overview")
    except Exception:
        overview_page = ""
    items = parse_items(page, include_breaks=not args.no_breaks)
    source_tz = detect_source_timezone(page, overview_page, override=args.source_timezone, items=items)
    local_tz = detect_local_timezone()

    if args.dry_run or not (args.output or args.do_import):
        print_summary(items, source_tz, local_tz)

    if args.output:
        write_ics(items, args.output, detail_url, source_tz, args.location, args.prefix)
        print(f"wrote={args.output}")

    if args.do_import:
        if not args.calendar_index:
            parser.error("--calendar-index is required with --import")
        script = build_import_script(
            items=items,
            source_url=detail_url,
            source_tz=source_tz,
            local_tz=local_tz,
            calendar_index=args.calendar_index,
            location=args.location,
            prefix=args.prefix,
            duplicate_check=not args.no_duplicate_check,
        )
        return import_to_calendar(script)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
