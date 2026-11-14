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
from homeassistant.helpers import entity_registry as er

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
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.MEDIA_PLAYER,
    Platform.NOTIFY,
    Platform.EVENT,
]

# Function codes corrected in 1.8.0 (config entry minor version 2), in the
# order they must be renamed: old 52 is freed before 62 moves onto it.
_FUNCTION_CODE_FIXES = ((52, 5), (62, 52))  # TIMEDFNC, then INPUT


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


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Move entities and devices of push buttons and timed functions to the right codes.

    Before 1.8.0, INPUT used function 62 (which doesn't exist) and TIMEDFNC 52
    (the push-button function). The codes are part of the unique ids, so the
    ids are renamed instead of leaving orphaned entities behind.
    """
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        central_id = entry.data[CONF_CENTRAL_ID]
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)
        for old, new in _FUNCTION_CODE_FIXES:
            old_prefix = f"teletask_{central_id}_{old}_"
            for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
                if entity.unique_id.startswith(old_prefix):
                    new_id = f"teletask_{central_id}_{new}_" + entity.unique_id[len(old_prefix):]
                    if ent_reg.async_get_entity_id(entity.domain, entity.platform, new_id) is None:
                        ent_reg.async_update_entity(entity.entity_id, new_unique_id=new_id)
            old_dev = f"{central_id}_{old}_"
            for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
                identifiers = {
                    (domain, f"{central_id}_{new}_" + ident[len(old_dev):])
                    if domain == DOMAIN and ident.startswith(old_dev) else (domain, ident)
                    for domain, ident in device.identifiers
                }
                if identifiers != device.identifiers:
                    dev_reg.async_update_device(device.id, new_identifiers=identifiers)
        hass.config_entries.async_update_entry(entry, minor_version=2)
        _LOGGER.info("Migrated Teletask entry %s to minor version 2", entry.title)
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
