"""Teletask native integration for Home Assistant."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .configfile import ConfigFileError, read_config_file
from .const import (
    CONF_CENTRAL_ID,
    CONF_CONFIG_JSON,
    CONF_CONFIG_PATH,
    CONF_DEBUG_LOG,
    CONF_HOST,
    CONF_PORT,
    DOMAIN,
)
from .hub import TeletaskHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BUTTON,
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

    config = await _async_load_config(hass, entry)

    hub = TeletaskHub(
        hass=hass,
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        central_id=entry.data[CONF_CENTRAL_ID],
        config=config,
    )

    await hub.async_setup()

    # Register the central unit first so component devices can point at it
    # ("Connected via") through its device registry id.
    central_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **hub.central_device_info
    )
    hub.central_device_id = central_device.id

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_load_config(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """Return the component config, preferring a fresh read of the linked file.

    With a linked file, every setup (HA start, integration Reload) re-reads it,
    so editing config.json and clicking Reload is enough. If the file is missing
    or invalid, the last successfully loaded copy is used and a notification
    explains why, so a typo never takes the entities down.
    """
    stored = entry.data.get(CONF_CONFIG_JSON, "{}")
    path = entry.data.get(CONF_CONFIG_PATH)
    notification_id = f"{DOMAIN}_config_{entry.entry_id}"

    if path:
        try:
            text, config = await hass.async_add_executor_job(read_config_file, path)
        except ConfigFileError as err:
            _LOGGER.warning(
                "Could not load Teletask config file %s (%s: %s); using the last loaded copy",
                path, err.code, err.detail,
            )
            persistent_notification.async_create(
                hass,
                f"Could not load `{path}`: {err.detail or err.code}.\n\n"
                "The last successfully loaded configuration is in use. Fix the file "
                "and reload the Teletask integration.",
                title="Teletask configuration not loaded",
                notification_id=notification_id,
            )
        else:
            persistent_notification.async_dismiss(hass, notification_id)
            if text != stored:
                # Keep the fallback copy current. The update listener only
                # adjusts log levels, so this does not trigger another reload.
                hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_CONFIG_JSON: text}
                )
                _LOGGER.info("Loaded updated Teletask config from %s", path)
            return config

    try:
        return json.loads(stored)
    except json.JSONDecodeError as exc:
        _LOGGER.error("Invalid stored Teletask config JSON: %s", exc)
        raise ConfigEntryNotReady("Invalid config JSON") from exc


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _apply_log_level(entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hub: TeletaskHub = hass.data[DOMAIN].pop(entry.entry_id)
        await hub.async_stop()
    return unload_ok
