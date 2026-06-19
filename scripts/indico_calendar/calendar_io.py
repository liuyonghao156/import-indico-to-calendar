"""Calendar output helpers for detailed Indico timetable items."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .core import (
    TimetableItem,
    apple_quote,
    event_description,
    event_title,
    fold_ics_line,
    ics_escape,
    item_datetimes,
    source_timezone_for_item,
    zoneinfo_name,
)


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
