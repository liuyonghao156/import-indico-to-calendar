"""Command line interface for extracting detailed Indico timetables."""

from __future__ import annotations

import argparse
from pathlib import Path
from zoneinfo import ZoneInfo

from .calendar_io import build_import_script, import_to_calendar, list_calendars, print_summary, write_ics
from .core import LOCATION_FALLBACK, detect_local_timezone, detect_source_timezone
from .fetching import event_ics_url, fetch_text, fetch_timetable_page, inspect_ics, normalize_event_url, timetable_url
from .parsers import parse_items


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
    try:
        source_tz = detect_source_timezone(page, overview_page, override=args.source_timezone, items=items)
    except ValueError:
        if items:
            raise
        source_tz = ZoneInfo("UTC")
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
