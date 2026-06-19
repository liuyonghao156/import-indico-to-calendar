"""Network and URL helpers for Indico event pages."""

from __future__ import annotations

import re
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


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
