"""Teletask button platform — momentary relay pulse triggers."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import FunctionCode
from .const import DOMAIN
from .hub import TeletaskHub

_LOGGER = logging.getLogger(__name__)

DEFAULT_PULSE_MS = 500


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TeletaskHub = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = []

    for comp in hub.get_components_by_function(FunctionCode.RELAY):
        if comp.get("type") == "momentary":
            entities.append(TeletaskMomentaryButton(hub, comp))

    async_add_entities(entities)


class TeletaskMomentaryButton(ButtonEntity):
    """A relay wired as a momentary dry-contact trigger."""

    def __init__(self, hub: TeletaskHub, component: dict) -> None:
        self._hub = hub
        self._number = component["number"]
        raw = component.get("config", {})
        self._pulse_ms: int = int(raw.get("pulse_ms", DEFAULT_PULSE_MS))

        central_id = hub.central_id
        self._attr_unique_id = (
            f"teletask_{central_id}_{int(FunctionCode.RELAY)}_{self._number}"
        )
        self._attr_name = component["description"]

    async def async_press(self) -> None:
        """Close the relay contact, wait pulse_ms, then open it again."""
        _LOGGER.debug(
            "MOMENTARY press relay %d — pulse %d ms", self._number, self._pulse_ms
        )
        await self._hub.async_set_relay(self._number, True)
        await asyncio.sleep(self._pulse_ms / 1000)
        await self._hub.async_set_relay(self._number, False)
