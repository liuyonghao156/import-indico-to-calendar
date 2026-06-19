---
name: import-indico-to-calendar
description: Extract detailed schedules from classic and Indico v3 conference/event pages and import them into Apple Calendar on macOS. Use when the user asks to find or verify Indico .ics exports, convert an Indico timetable into calendar events, add an Indico programme to Apple Calendar, broaden parser coverage across Indico services, or target a specific Apple Calendar account/calendar such as Exchange/iCloud/Google calendars with duplicate names.
---

# Import Indico To Calendar

## Workflow

1. Start by checking the official Indico export:
   - Try `<event-url>/event.ics` for an event-level calendar feed.
   - Count `VEVENT` entries before trusting it. Some Indico deployments expose only one broad all-school/conference event while the detailed timetable exists only in HTML.
2. Parse the detailed timetable with `scripts/indico_to_apple_calendar.py`.
   - The script first tries the older timetable HTML rows (`meetingContrib` / `breakListItem`).
   - If those rows are absent, it falls back to Indico v3's embedded `timetableArgs` data and flattens session blocks into individual contribution events.
   - If neither format is present, it parses server-rendered Indico 3 timetable markup (`timetable-item`, `timetable-block`, `timetable-contrib`, `timetable-break`).
   - Some Indico 3 events serve timetable rows at `/event/<id>/` instead of `/event/<id>/timetable/`; the CLI falls back to the event root when the timetable route returns 404.
3. If importing into Apple Calendar, identify the target calendar precisely:
   - Run AppleScript list commands to get calendar order and writability.
   - When duplicate names exist, use Computer Use or Chronicle to inspect Calendar.app's sidebar account groups. Calendar sidebar order normally matches AppleScript calendar index order.
   - Prefer `--calendar-index` over name matching for duplicate names.
4. Run a dry import first. Check item count, first/last items, timezone, and whether breaks are included.
5. Import only after the target calendar and slot count are clear.

## Script

Use the bundled script:

```bash
python3 /Users/yonghao/.codex/skills/import-indico-to-calendar/scripts/indico_to_apple_calendar.py \
  "https://indico.example.org/event/12345/overview" --dry-run
```

Useful options:

- `--list-calendars`: print Apple Calendar indexes, names, writability, and descriptions.
- `--show-official-ics`: print the likely top-level `event.ics` URL and its `VEVENT` count.
- `--calendar-index N --import`: write events directly to Apple Calendar calendar `N`.
- `--output FILE.ics`: write a detailed `.ics` file instead of importing.
- `--no-breaks`: skip timetable break items such as coffee/lunch.
- `--prefix "ICTP:"`: prefix event titles for easier verification and cleanup.
- `--source-timezone Europe/Rome`: override timezone if the page does not expose it or the parser guesses wrong.
- `--no-duplicate-check`: skip duplicate checks when speed matters and duplicates are acceptable.

The script converts source event times to the Mac's local timezone before using AppleScript, because Calendar's AppleScript date constructor creates local-time dates.

Most reusable code lives in `scripts/indico_calendar/subroutines.py`; `scripts/indico_to_apple_calendar.py` is intentionally only the stable CLI wrapper.

## Apple Calendar Notes

Calendar.app's AppleScript support often fails for bulk `properties` or `id` reads. Use smaller queries:

```applescript
tell application "Calendar" to get name of calendars
tell application "Calendar" to get writable of calendars
```

For account grouping, inspect Calendar.app's sidebar via Computer Use:

```text
get_app_state(app="Calendar")
```

The accessibility tree exposes rows under groups such as `Exchange`, `iCloud`, or `Google`, which is the safest way to distinguish duplicate calendars named `Calendar`.

## Validation

After import, verify the count in the target calendar:

```applescript
tell application "Calendar"
  set targetCal to calendar 3
  -- inspect events in the date range whose summary begins with the chosen prefix
end tell
```

Report three things back to the user: number of events created/skipped, target calendar/account, and any timezone conversion caveat.
