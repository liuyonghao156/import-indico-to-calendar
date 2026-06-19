"""Shared data types and utilities for Indico timetable conversion."""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
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


def sort_items(items: list[TimetableItem]) -> list[TimetableItem]:
    return sorted(items, key=lambda item: (item.date, item.time, item.title))


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
