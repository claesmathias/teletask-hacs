"""Tests for parsing the central unit's support web page (no HA needed)."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "teletask_webinfo",
    Path(__file__).parent.parent / "custom_components" / "teletask" / "webinfo.py",
)
webinfo = importlib.util.module_from_spec(_spec)
# @dataclass looks the module up in sys.modules (Python 3.14+), so register it first.
sys.modules[_spec.name] = webinfo
_spec.loader.exec_module(webinfo)

CET = timezone(timedelta(hours=1))


def _utf16(text: str) -> str:
    """Mimic how the central emits the project filename: NUL-interleaved UTF-16."""
    return "".join("\x00" + ch for ch in text)


# Same structure as a real PICOS serial.cgi (values anonymised).
SERIAL_HTML = (
    "<HTML>\n<BODY bgcolor=white>\n<div class=Section1>\n"
    "<p class=MsoNormal align=center><span>TELETASK\nDOIP Central Unit<o:p></o:p></span>\n"
    "<p class=MsoNormal align=center><span>Technical support page<o:p></o:p></span></p>\n"
    "</div>\n\n<h3>\ntype=000010009\nType = PICOS</h3>\n"
    "<h3>Serial Number = \n123456789\n</h3>\n"
    "<h3>Mac Address = \nE4:1E:0A:00:00:01\n</h3>\n"
    "<h3>Installed PROSOFT = \nVersion:4.1.2.0\n"
    "<h3>Disk version = \n 1.14\n</h3>\n"
    "OS date = \nWed Dec 9\n 2009\n</h3>\n"
    "<h3>Filename = \n"
    + _utf16("C:\\Users\\Jane\\Documents\\PICOS Home 01012026.nbt;Jane Doe\r")
    + "\x00\n</h3>\n</BODY>\n</HTML>\n"
)

TIME_HTML = (
    '<HTML>\n<meta http-equiv="refresh" content="1">\n\n</div>\n\n'
    "<h3>Current Time = \nThu Nov  5 19:16:09 CET 2026\n</h3>\n</BODY>\n</HTML>\n"
)


class TestParseSerialPage:
    def test_all_fields(self):
        info = webinfo.parse_serial_page(SERIAL_HTML)
        assert info == webinfo.CentralInfo(
            type_code="000010009",
            model="PICOS",
            serial_number="123456789",
            mac_address="e4:1e:0a:00:00:01",
            prosoft_version="4.1.2.0",
            disk_version="1.14",
            os_date="Wed Dec 9 2009",
            project_file="PICOS Home 01012026.nbt",
            project_owner="Jane Doe",
        )

    def test_filename_without_owner(self):
        body = SERIAL_HTML.replace(_utf16(";Jane Doe"), "")
        info = webinfo.parse_serial_page(body)
        assert info.project_file == "PICOS Home 01012026.nbt"
        assert info.project_owner is None

    def test_garbage_yields_empty_info(self):
        assert webinfo.parse_serial_page("<html>nope</html>") == webinfo.CentralInfo()


class TestParseTimePage:
    def test_parses_wall_clock_in_given_tz(self):
        assert webinfo.parse_time_page(TIME_HTML, CET) == datetime(
            2026, 11, 5, 19, 16, 9, tzinfo=CET
        )

    def test_two_digit_day_and_summer_tz(self):
        body = TIME_HTML.replace("Thu Nov  5 19:16:09 CET", "Sun Jul 12 08:00:00 CEST")
        assert webinfo.parse_time_page(body, CET) == datetime(
            2026, 7, 12, 8, 0, 0, tzinfo=CET
        )

    def test_garbage_returns_none(self):
        assert webinfo.parse_time_page("<h3>Current Time = soon</h3>", CET) is None
        assert webinfo.parse_time_page("", CET) is None
