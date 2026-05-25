"""Teletask native integration for Home Assistant."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_CONFIG_JSON, CONF_DEBUG_LOG, CONF_HOST, CONF_PORT, CONF_CENTRAL_ID, DOMAIN
from .hub import TeletaskHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.COVER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SCENE,
]


def _apply_log_level(entry: ConfigEntry) -> None:
    debug = entry.options.get(CONF_DEBUG_LOG, entry.data.get(CONF_DEBUG_LOG, False))
    level = logging.DEBUG if debug else logging.WARNING
    for name in ("custom_components.teletask", "custom_components.teletask.client",
                 "custom_components.teletask.hub", "custom_components.teletask.entity"):
        logging.getLogger(name).setLevel(level)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Teletask from a config entry."""
    _apply_log_level(entry)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    config_json_str = entry.data.get(CONF_CONFIG_JSON, "{}")
    try:
        config = json.loads(config_json_str)
    except json.JSONDecodeError as exc:
        _LOGGER.error("Invalid Teletask config JSON: %s", exc)
        raise ConfigEntryNotReady("Invalid config JSON") from exc

    hub = TeletaskHub(
        hass=hass,
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        central_id=entry.data[CONF_CENTRAL_ID],
        config=config,
    )

    await hub.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _apply_log_level(entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hub: TeletaskHub = hass.data[DOMAIN].pop(entry.entry_id)
        await hub.async_stop()
    return unload_ok
