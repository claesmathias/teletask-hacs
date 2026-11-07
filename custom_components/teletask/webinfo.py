"""Read-only access to the central unit's built-in web pages.

The DOIP central (PICOS, MICROS+, …) serves a small "technical support page"
on HTTP port 80 with two frames:

* ``/cgi-bin/serial.cgi`` — unit type, serial number, MAC address, installed
  PROSOFT version, disk version, OS date and the PROSOFT project filename.
* ``/cgi-bin/time.cgi`` — the central's current clock.

This module has no Home Assistant imports so the parsers can be unit-tested
without HA installed.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, tzinfo

SERIAL_PATH = "/cgi-bin/serial.cgi"
TIME_PATH = "/cgi-bin/time.cgi"


@dataclass(frozen=True)
class CentralInfo:
    """Static information about the central unit."""

    type_code: str | None = None
    model: str | None = None
    serial_number: str | None = None
    mac_address: str | None = None
    prosoft_version: str | None = None
    disk_version: str | None = None
    os_date: str | None = None
    project_file: str | None = None
    project_owner: str | None = None


def _clean(text: str) -> str:
    """Strip tags, decode entities, drop NULs/CRs and collapse whitespace."""
    text = text.replace("\x00", "")
    text = re.sub(r"<[^>]*>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _field(body: str, label: str) -> str | None:
    """Return the value after ``label =`` up to the next field / end of body."""
    match = re.search(
        rf"{re.escape(label)}\s*=\s*(.*?)(?=<h3>|</h3>|</body>|$)",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    value = _clean(match.group(1))
    return value or None


def parse_serial_page(body: str) -> CentralInfo:
    """Parse the HTML of ``serial.cgi``."""
    # The project filename is sent as UTF-16 (NUL-interleaved); strip NULs first
    # so every field can be matched as plain text.
    body = body.replace("\x00", "")

    type_code = _field(body, "type")
    model = None
    if type_code:
        # "000010009 Type = PICOS" — the lowercase "type=" match swallows the
        # following "Type = …" line because both sit inside the same <h3>.
        parts = re.split(r"\s*Type\s*=\s*", type_code, maxsplit=1, flags=re.IGNORECASE)
        type_code = parts[0] or None
        if len(parts) > 1:
            model = parts[1] or None

    prosoft = _field(body, "Installed PROSOFT")
    if prosoft:
        prosoft = re.sub(r"^Version\s*:\s*", "", prosoft, flags=re.IGNORECASE)

    project_file = project_owner = None
    if raw := _field(body, "Filename"):
        path, _, owner = raw.partition(";")
        # Keep just the filename; the full Windows path is noise in HA.
        project_file = re.split(r"[\\/]", path.strip())[-1] or None
        project_owner = owner.strip() or None

    mac = _field(body, "Mac Address")
    return CentralInfo(
        type_code=type_code,
        model=model,
        serial_number=_field(body, "Serial Number"),
        mac_address=mac.lower() if mac else None,
        prosoft_version=prosoft,
        disk_version=_field(body, "Disk version"),
        os_date=_field(body, "OS date"),
        project_file=project_file,
        project_owner=project_owner,
    )


def parse_time_page(body: str, tz: tzinfo) -> datetime | None:
    """Parse ``time.cgi`` (``Thu Nov  5 19:16:09 CET 2026``) into an aware datetime.

    The central prints a timezone *abbreviation* (CET/CEST) which Python cannot
    resolve reliably, so the wall-clock time is interpreted in ``tz`` (HA's
    configured timezone, which should match the central's).
    """
    raw = _field(body, "Current Time")
    if not raw:
        return None
    match = re.match(
        r"\w{3}\s+(\w{3})\s+(\d{1,2})\s+(\d{1,2}:\d{2}:\d{2})\s+(?:[A-Z]{2,5}\s+)?(\d{4})",
        raw,
    )
    if not match:
        return None
    month, day, clock, year = match.groups()
    try:
        naive = datetime.strptime(f"{month} {day} {year} {clock}", "%b %d %Y %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=tz)
