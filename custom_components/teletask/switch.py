"""Teletask switch platform — relays (switch type), flags, timed functions."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import FunctionCode
from .const import DOMAIN, TELETASK_EVENT
from .entity import TeletaskEntity
from .hub import TeletaskHub

DEFAULT_PULSE_MS = 500

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TeletaskHub = hass.data[DOMAIN][entry.entry_id]
    entities: list[TeletaskEntity] = []

    # RELAY with hatype "switch"
    for comp in hub.get_components_by_function(FunctionCode.RELAY):
        if comp.get("ha_type") == "switch":
            entities.append(TeletaskRelaySwitch(hub, comp))

    # RELAY with hatype "button" — momentary pulse, exposed as a switch so that
    # ON/OFF transitions appear in the HA activity log like every other RELAY.
    for comp in hub.get_components_by_function(FunctionCode.RELAY):
        if comp.get("ha_type") == "button":
            entities.append(TeletaskMomentaryButton(hub, comp))

    # FLAG components (hatype "switch" or "input_boolean" both map to a switch entity)
    for comp in hub.get_components_by_function(FunctionCode.FLAG):
        ha_type = comp.get("ha_type") or comp.get("type") or "switch"
        if ha_type in ("switch", "input_boolean"):
            entities.append(TeletaskFlagSwitch(hub, comp))

    # TIMED FUNCTION components (type=switch, not scene)
    for comp in hub.get_components_by_function(FunctionCode.TIMEDFNC):
        ha_type = comp.get("ha_type") or comp.get("type") or "switch"
        if ha_type == "switch":
            entities.append(TeletaskTimedFncSwitch(hub, comp))

    # MOODS that are configured as switch (not scene)
    for fn in (FunctionCode.LOCMOOD, FunctionCode.GENMOOD, FunctionCode.TIMEDMOOD):
        for comp in hub.get_components_by_function(fn):
            ha_type = comp.get("ha_type") or comp.get("type") or "switch"
            if ha_type == "switch":
                entities.append(TeletaskMoodSwitch(hub, comp))

    async_add_entities(entities)


class TeletaskRelaySwitch(TeletaskEntity, SwitchEntity):
    """A relay wired as a switch."""

    @property
    def is_on(self) -> bool:
        return self._state_dict.get("state") == "ON"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._hub.async_set_relay(self._number, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.async_set_relay(self._number, False)


class TeletaskFlagSwitch(TeletaskEntity, SwitchEntity):
    """A Teletask flag exposed as a switch."""

    @property
    def is_on(self) -> bool:
        return self._state_dict.get("state") == "ON"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._hub.async_set_flag(self._number, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.async_set_flag(self._number, False)


class TeletaskTimedFncSwitch(TeletaskEntity, SwitchEntity):
    """A Teletask timed function exposed as a switch."""

    @property
    def is_on(self) -> bool:
        return self._state_dict.get("state") == "ON"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._hub.async_set_timedfnc(self._number, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.async_set_timedfnc(self._number, False)


class TeletaskMoodSwitch(TeletaskEntity, SwitchEntity):
    """A Teletask mood (local/general/timed) exposed as a switch."""

    @property
    def is_on(self) -> bool:
        return self._state_dict.get("state") == "ON"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._hub.async_set_mood(self._function, self._number, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.async_set_mood(self._function, self._number, False)


class TeletaskMomentaryButton(TeletaskEntity, SwitchEntity):
    """A relay wired as a momentary dry-contact trigger (hatype=button).

    Exposed as a switch so ON/OFF transitions are written to the HA state machine
    and appear in the activity log, identical to every other RELAY entity.
    turn_on pulses the relay; turn_off is a no-op.
    """

    def __init__(self, hub: TeletaskHub, component: dict) -> None:
        super().__init__(hub, component)
        self._pulse_ms: int = int(
            component.get("config", {}).get("pulse_ms", DEFAULT_PULSE_MS)
        )

    @property
    def is_on(self) -> bool:
        return self._state_dict.get("state") == "ON"

    @callback
    def _handle_state_update(self, state: dict) -> None:
        super()._handle_state_update(state)
        if state.get("state") == "ON":
            self.hass.bus.async_fire(TELETASK_EVENT, {
                "function": "RELAY",
                "number": self._number,
                "description": self._attr_name,
                "state": "ON",
            })

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._hub.async_set_relay(self._number, True)
        await asyncio.sleep(self._pulse_ms / 1000)
        await self._hub.async_set_relay(self._number, False)

    async def async_turn_off(self, **kwargs: Any) -> None:
        pass
