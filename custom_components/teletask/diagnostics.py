"""Diagnostics download for the Teletask integration.

Settings > Devices & services > Teletask > ⋮ > Download diagnostics gives one
JSON file to attach to a bug report: connection and outage state, what the
central's support page reports, the component config and the last known state
of every component. The host, MAC address, serial number and project owner
are redacted.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import CONF_CONFIG_JSON, CONF_HOST, DOMAIN
from .hub import TeletaskHub

TO_REDACT = {CONF_HOST, "host", "mac_address", "serial_number", "project_owner"}


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    hub: TeletaskHub | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    # The config text is large and the same as hub.config below.
    entry_data = {k: v for k, v in entry.data.items() if k != CONF_CONFIG_JSON}
    result: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "version": f"{entry.version}.{entry.minor_version}",
            "data": entry_data,
            "options": dict(entry.options),
        },
    }
    if hub is None:
        result["error"] = "integration not loaded"
        return async_redact_data(result, TO_REDACT)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, hub.outage_issue_id)
    web = hub.web_coordinator
    states = {
        f"{comp['function_name']} {comp['number']}": hub.get_state(fn, number)
        for (fn, number), comp in sorted(hub.components.items())
    }
    result.update({
        "connection": {
            "connected": hub.connected,
            "port": hub.port,
            "last_error": hub.last_error,
            "outage_since": _iso(hub.outage_since),
            "reconnect_attempts": hub.reconnect_attempts,
            "repairs_issue_open": issue is not None and issue.active,
            "last_event": _iso(hub.last_event),
            "resyncing": hub.resyncing,
        },
        "central_web_page": {
            "reachable": web.last_update_success,
            "last_error": str(web.last_exception) if web.last_exception else None,
            "info": asdict(hub.central_info),
            "clock": _iso(web.data.clock) if web.data else None,
            "clock_offset_seconds": web.data.clock_offset if web.data else None,
        },
        "component_counts": {
            name: sum(1 for c in hub.components.values() if c["function_name"] == name)
            for name in sorted({c["function_name"] for c in hub.components.values()})
        },
        "config": hub.config,
        "states": states,
    })
    return async_redact_data(result, TO_REDACT)
