"""DHCP discovery matchers in manifest.json — no live HA or central required.

Home Assistant matches ``macaddress`` patterns with fnmatch against the MAC in
upper case without separators.
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

import pytest

MANIFEST = Path(__file__).parent.parent / "custom_components" / "teletask" / "manifest.json"


def _mac_patterns() -> list[str]:
    dhcp = json.loads(MANIFEST.read_text())["dhcp"]
    return [m["macaddress"] for m in dhcp if "macaddress" in m]


def _matches(mac: str) -> bool:
    mac = mac.replace(":", "").upper()
    return any(fnmatch.fnmatch(mac, p) for p in _mac_patterns())


def test_registered_devices_rediscovered():
    """Known centrals (device MAC connection) follow DHCP address changes."""
    dhcp = json.loads(MANIFEST.read_text())["dhcp"]
    assert {"registered_devices": True} in dhcp


@pytest.mark.parametrize(
    "mac",
    [
        "00:50:C2:6A:40:00",  # IAB 00-50-C2-6A-4
        "00:50:c2:6a:4f:ff",
        "70:B3:D5:C5:60:12",  # MA-S 70-B3-D5-C5-6
        "E4:1E:0A:C1:23:45",  # MA-M E4-1E-0A-C
    ],
)
def test_teletask_blocks_match(mac):
    assert _matches(mac)


@pytest.mark.parametrize(
    "mac",
    [
        "00:50:C2:6A:50:00",  # next IAB in the same OUI, another vendor
        "70:B3:D5:C5:70:00",
        "E4:1E:0A:00:00:01",  # other MA-M holder in the shared OUI
        "E4:1E:0A:D0:00:00",
    ],
)
def test_other_vendors_do_not_match(mac):
    assert not _matches(mac)


def test_patterns_are_uppercase_hex():
    for pattern in _mac_patterns():
        assert pattern == pattern.upper()
        assert all(c in "0123456789ABCDEF*" for c in pattern)
