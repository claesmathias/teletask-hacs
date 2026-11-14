"""Teletask light platform — handles RELAY (type=light) and DIMMER components."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
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

    # RELAY components with hatype "light" (default for relays)
    for comp in hub.get_components_by_function(FunctionCode.RELAY):
        if (comp.get("ha_type") or "light") == "light":
            entities.append(TeletaskRelayLight(hub, comp))

    # All DIMMER and DIMMERGRP components are lights
    for fn in (FunctionCode.DIMMER, FunctionCode.DIMMERGRP):
        for comp in hub.get_components_by_function(fn):
            entities.append(TeletaskDimmerLight(hub, comp))

    for fn in (FunctionCode.RGB, FunctionCode.RGBGRP):
        for comp in hub.get_components_by_function(fn):
            entities.append(TeletaskRgbLight(hub, comp))

    for fn in (FunctionCode.TW, FunctionCode.TWGRP):
        for comp in hub.get_components_by_function(fn):
            entities.append(TeletaskTunableWhiteLight(hub, comp))

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
        await self._hub.async_set_dimmer(self._number, teletask_brightness, self._function)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.async_set_dimmer(self._number, 0, self._function)


def _to_ha(level: int) -> int:
    """Teletask 0-100 → HA 0-255."""
    return min(255, max(0, round(level * 255 / 100)))


def _to_teletask(brightness: int) -> int:
    """HA 0-255 → Teletask 0-100."""
    return min(100, max(0, round(brightness * 100 / 255)))


class TeletaskRgbLight(TeletaskEntity, LightEntity):
    """An RGB light or group (DoIP). The central only knows R, G and B, so
    brightness is the strongest channel and the colour is the rest."""

    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}

    def __init__(self, hub: TeletaskHub, component: dict) -> None:
        super().__init__(hub, component)
        self._last_color: tuple[int, int, int] = (255, 255, 255)

    def _rgb(self) -> tuple[int, int, int] | None:
        rgb = self._state_dict.get("rgb")
        return tuple(rgb) if rgb else None

    @property
    def is_on(self) -> bool | None:
        rgb = self._rgb()
        return None if rgb is None else any(rgb)

    @property
    def brightness(self) -> int | None:
        rgb = self._rgb()
        return max(rgb) if rgb else None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        rgb = self._rgb()
        if not rgb or not any(rgb):
            return self._last_color
        peak = max(rgb)
        color = tuple(round(c * 255 / peak) for c in rgb)
        self._last_color = color
        return color

    async def async_turn_on(self, **kwargs: Any) -> None:
        color = kwargs.get(ATTR_RGB_COLOR) or self.rgb_color or (255, 255, 255)
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if brightness is None:
            brightness = self.brightness if self.is_on else 255
        peak = max(color) or 255
        scaled = tuple(round(c * 255 / peak * brightness / 255) for c in color)
        self._last_color = tuple(color)
        await self._hub.async_set_rgb(self._function, self._number, scaled)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.async_set_rgb(self._function, self._number, (0, 0, 0))


class TeletaskTunableWhiteLight(TeletaskEntity, LightEntity):
    """A tunable white light or group (DoIP): colour temperature + brightness."""

    _attr_color_mode = ColorMode.COLOR_TEMP
    _attr_supported_color_modes = {ColorMode.COLOR_TEMP}

    DEFAULT_MIN_KELVIN = 2700
    DEFAULT_MAX_KELVIN = 6500

    def __init__(self, hub: TeletaskHub, component: dict) -> None:
        super().__init__(hub, component)
        self._last_level = 100

    @property
    def min_color_temp_kelvin(self) -> int:
        return self._state_dict.get("min_kelvin") or self.DEFAULT_MIN_KELVIN

    @property
    def max_color_temp_kelvin(self) -> int:
        return self._state_dict.get("max_kelvin") or self.DEFAULT_MAX_KELVIN

    @property
    def color_temp_kelvin(self) -> int | None:
        return self._state_dict.get("kelvin")

    @property
    def is_on(self) -> bool | None:
        level = self._state_dict.get("brightness")
        return None if level is None else level > 0

    @property
    def brightness(self) -> int | None:
        level = self._state_dict.get("brightness")
        if level:
            self._last_level = level
        return None if level is None else _to_ha(level)

    async def async_turn_on(self, **kwargs: Any) -> None:
        kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        if ATTR_BRIGHTNESS in kwargs:
            level = _to_teletask(kwargs[ATTR_BRIGHTNESS])
        elif self.is_on:
            level = None  # colour change only
        else:
            level = self._last_level
        await self._hub.async_set_tw(self._function, self._number, kelvin, level)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.async_set_tw(self._function, self._number, None, 0)
