"""Teletask light platform — handles RELAY (type=light) and DIMMER components."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import FunctionCode
from .const import DOMAIN
from .entity import TeletaskEntity
from .hub import TeletaskHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TeletaskHub = hass.data[DOMAIN][entry.entry_id]
    entities: list[TeletaskEntity] = []

    # RELAY components with type "light" (default for relays)
    for comp in hub.get_components_by_function(FunctionCode.RELAY):
        ha_type = comp.get("type") or comp.get("ha_type") or "light"
        if ha_type == "light":
            entities.append(TeletaskRelayLight(hub, comp))

    # All DIMMER components are lights
    for comp in hub.get_components_by_function(FunctionCode.DIMMER):
        entities.append(TeletaskDimmerLight(hub, comp))

    async_add_entities(entities)


class TeletaskRelayLight(TeletaskEntity, LightEntity):
    """A simple on/off relay wired as a light."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def is_on(self) -> bool:
        return self._state_dict.get("state") == "ON"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._hub.async_set_relay(self._number, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.async_set_relay(self._number, False)


class TeletaskDimmerLight(TeletaskEntity, LightEntity):
    """A dimmable light."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    @property
    def is_on(self) -> bool:
        return self._state_dict.get("state") == "ON"

    @property
    def brightness(self) -> int | None:
        """Return brightness scaled from Teletask 0-100 to HA 0-255."""
        raw = self._state_dict.get("brightness")
        if raw is None:
            return None
        return min(255, max(0, round(raw * 255 / 100)))

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            # Convert HA 0-255 to Teletask 0-100
            teletask_brightness = round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
        else:
            # 103 = restore previous brightness (PREVIOUS_STATE per Teletask protocol)
            teletask_brightness = 103
        await self._hub.async_set_dimmer(self._number, teletask_brightness)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.async_set_dimmer(self._number, 0)
