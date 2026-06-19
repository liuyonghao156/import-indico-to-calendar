# Import Indico To Calendar

Extract detailed timetables from Indico event pages and turn them into Apple Calendar events or a detailed `.ics` file.

This is useful for conference, workshop, and summer-school pages where the official Indico calendar export exists but only contains one broad event for the whole meeting. The detailed lecture-by-lecture schedule is often present only in the timetable HTML.

## Intended Use

This repository is structured as a Codex skill first. The expected workflow is that an agent reads `SKILL.md`, checks whether the official Indico `.ics` is detailed enough, dry-runs the parser, disambiguates the target Apple Calendar account if needed, and only then imports events or writes a detailed `.ics` file.

Humans can still run the bundled script directly; the command examples below are the deterministic steps the agent is expected to use.

## What It Does

- Guides an agent through official `.ics` inspection, timetable parsing, target-calendar disambiguation, dry-run validation, and import.
- Parses detailed Indico timetable pages such as `https://indico.example.org/event/12345/timetable/`.
- Supports older Indico timetable HTML and Indico v3 pages that embed timetable data in `timetableArgs`.
- Counts the official top-level `event.ics` entries so you can tell whether it is useful.
- Preserves talks, discussions, coffee breaks, and lunch breaks by default.
- Extracts speakers when Indico exposes them in the timetable HTML.
- Writes a detailed `.ics` file for any calendar app.
- On macOS, imports directly into Apple Calendar through AppleScript.
- Handles source timezone to local timezone conversion for Apple Calendar imports.

## Manual CLI Quick Start

Run a dry parse first:

```bash
python3 scripts/indico_to_apple_calendar.py \
  "https://indico.ictp.it/event/11149/overview" \
  --dry-run \
  --show-official-ics
```

Example output:

```text
official_event_ics=https://indico.ictp.it/event/11149/event.ics
official_event_ics_vevents=1
items=70
source_timezone=Europe/Rome
local_timezone=Asia/Shanghai
first=Large Scale Structure 1 | 2026-06-29 09:15-10:30 source | 2026-06-29 15:15-16:30 local
last=Discussion Session | 2026-07-10 15:45-17:00 source | 2026-07-10 21:45-23:00 local
```

Write a detailed `.ics` file:

```bash
python3 scripts/indico_to_apple_calendar.py \
  "https://indico.ictp.it/event/11149/overview" \
  --output ictp-summer-school-detailed.ics \
  --prefix "ICTP:" \
  --location "ICTP Budinich Lecture Hall (LB), Trieste, Italy"
```

Skip breaks if you only want talks and discussion sessions:

```bash
python3 scripts/indico_to_apple_calendar.py \
  "https://indico.ictp.it/event/11149/overview" \
  --dry-run \
  --no-breaks
```

## Import Into Apple Calendar

First list Apple Calendar calendars:

```bash
python3 scripts/indico_to_apple_calendar.py --list-calendars
```

Then import into the desired calendar index:

```bash
python3 scripts/indico_to_apple_calendar.py \
  "https://indico.ictp.it/event/11149/overview" \
  --import \
  --calendar-index 3 \
  --prefix "ICTP:" \
  --location "ICTP Budinich Lecture Hall (LB), Trieste, Italy"
```

Use `--calendar-index` rather than calendar name when Apple Calendar has duplicate names such as multiple calendars named `Calendar`.

## Timezone Notes

Indico pages usually expose a source timezone such as `Europe/Rome`. The script uses that timezone for `.ics` files.

For direct Apple Calendar imports, the script converts source times to the Mac's local timezone before constructing AppleScript dates. This matters because AppleScript's date constructor creates local-time dates.

If timezone detection fails or the page is ambiguous, pass it explicitly:

```bash
python3 scripts/indico_to_apple_calendar.py \
  "https://indico.example.org/event/12345/overview" \
  --dry-run \
  --source-timezone Europe/Rome
```

## Install As A Codex Skill

Clone this repository into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/liuyonghao156/import-indico-to-calendar.git \
  ~/.codex/skills/import-indico-to-calendar
```

Then ask Codex to use `$import-indico-to-calendar` for Indico-to-calendar tasks.

## Requirements

- Python 3.9 or newer.
- No third-party Python packages are required.
- macOS Calendar.app is required only for direct Apple Calendar import.

## Limitations

- The parser targets the classic Indico timetable HTML structure and Indico v3's embedded `timetableArgs` format. Other heavily customized Indico timetable templates may still need parser updates.
- Direct Apple Calendar import depends on macOS AppleScript support, which can be slow for many events.
- Duplicate checking compares event summary and start time in the target calendar. Use `--no-duplicate-check` only if duplicates are acceptable.

## Why Not Just Use Indico's ICS?

Always check it first. For some events it is enough.

For other events, including the ICTP example above, the official `event.ics` contains only one top-level event for the whole programme. This tool extracts the detailed timetable rows instead.
