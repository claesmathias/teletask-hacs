"""Teletask button platform — momentary relay pulse triggers."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .client import FunctionCode
from .const import DOMAIN, SIGNAL_STATE_UPDATED, TELETASK_EVENT
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
        if comp.get("ha_type") == "button":
            entities.append(TeletaskMomentaryButton(hub, comp))

    async_add_entities(entities)


class TeletaskMomentaryButton(ButtonEntity):
    """A relay wired as a momentary dry-contact trigger."""

    _attr_should_poll = False

    def __init__(self, hub: TeletaskHub, component: dict) -> None:
        self._hub = hub
        self._number = component["number"]
        raw = component.get("config", {})
        self._pulse_ms: int = int(raw.get("pulse_ms", DEFAULT_PULSE_MS))

        central_id = hub.central_id
        fn = int(FunctionCode.RELAY)
        self._attr_unique_id = f"teletask_{central_id}_{fn}_{self._number}"
        self._attr_name = component["description"]
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{central_id}_{fn}_{self._number}")},
            name=component["description"],
            manufacturer="Teletask",
            model=component.get("function_name", "RELAY"),
        )
        if area := component.get("area"):
            device_info["suggested_area"] = area
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        signal = SIGNAL_STATE_UPDATED.format(
            central_id=self._hub.central_id,
            function=int(FunctionCode.RELAY),
            number=self._number,
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._handle_state_update)
        )

    @callback
    def _handle_state_update(self, state: dict) -> None:
        if state.get("state") == "ON":
            _LOGGER.debug(
                "BUTTON EVENT  %s relay=%d  externally triggered",
                self._attr_name, self._number,
            )
            self._attr_last_pressed = dt_util.utcnow()
            self.async_write_ha_state()
            self.hass.bus.async_fire(TELETASK_EVENT, {
                "function": "RELAY",
                "number": self._number,
                "description": self._attr_name,
                "state": "ON",
            })

    async def async_press(self) -> None:
        """Close the relay contact, wait pulse_ms, then open it again."""
        _LOGGER.debug(
            "MOMENTARY press relay %d — pulse %d ms", self._number, self._pulse_ms
        )
        await self._hub.async_set_relay(self._number, True)
        await asyncio.sleep(self._pulse_ms / 1000)
        await self._hub.async_set_relay(self._number, False)
