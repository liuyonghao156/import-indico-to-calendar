"""Compatibility exports for the Indico timetable importer.

The implementation is split into focused modules. This file keeps the broad
subroutine import surface stable for existing examples and agent workflows.
"""

from __future__ import annotations

from .calendar_io import build_import_script, import_to_calendar, list_calendars, print_summary, write_ics
from .cli import main
from .core import (
    LOCATION_FALLBACK,
    TIMEZONE_RE,
    TimetableItem,
    apple_quote,
    clean_speaker_text,
    clean_text,
    clean_timetable_title,
    detect_local_timezone,
    detect_source_timezone,
    duration_text_from_clock_times,
    duration_text_from_minutes,
    event_description,
    event_title,
    fold_ics_line,
    ics_escape,
    item_datetimes,
    normalize_clock_time,
    sort_items,
    source_timezone_for_item,
    zoneinfo_name,
)
from .fetching import event_ics_url, fetch_text, fetch_timetable_page, inspect_ics, normalize_event_url, timetable_url
from .parser_classic import IndicoTimetableParser, parse_classic_items
from .parser_server_rendered import ServerRenderedTimetableParser, parse_server_rendered_items
from .parser_v3 import (
    append_v3_entry,
    entry_location,
    extract_v3_timetable_args,
    indico_date_time,
    people_text,
    person_label,
    parse_v3_items,
    v3_entry_to_item,
)
from .parsers import parse_items


__all__ = [
    "LOCATION_FALLBACK",
    "TIMEZONE_RE",
    "IndicoTimetableParser",
    "ServerRenderedTimetableParser",
    "TimetableItem",
    "append_v3_entry",
    "apple_quote",
    "build_import_script",
    "clean_speaker_text",
    "clean_text",
    "clean_timetable_title",
    "detect_local_timezone",
    "detect_source_timezone",
    "duration_text_from_clock_times",
    "duration_text_from_minutes",
    "entry_location",
    "event_description",
    "event_ics_url",
    "event_title",
    "extract_v3_timetable_args",
    "fetch_text",
    "fetch_timetable_page",
    "fold_ics_line",
    "ics_escape",
    "import_to_calendar",
    "indico_date_time",
    "inspect_ics",
    "item_datetimes",
    "list_calendars",
    "main",
    "normalize_clock_time",
    "normalize_event_url",
    "parse_classic_items",
    "parse_items",
    "parse_server_rendered_items",
    "parse_v3_items",
    "people_text",
    "person_label",
    "print_summary",
    "sort_items",
    "source_timezone_for_item",
    "timetable_url",
    "v3_entry_to_item",
    "write_ics",
    "zoneinfo_name",
]
