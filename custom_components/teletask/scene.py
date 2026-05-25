"""Teletask scene platform — moods and timed functions configured as scenes."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import FunctionCode
from .const import DOMAIN
from .hub import TeletaskHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TeletaskHub = hass.data[DOMAIN][entry.entry_id]
    entities: list[Scene] = []

    for fn in (FunctionCode.LOCMOOD, FunctionCode.GENMOOD, FunctionCode.TIMEDMOOD):
        for comp in hub.get_components_by_function(fn):
            ha_type = comp.get("ha_type") or comp.get("type") or "switch"
            if ha_type == "scene":
                entities.append(TeletaskScene(hub, comp))

    for comp in hub.get_components_by_function(FunctionCode.TIMEDFNC):
        ha_type = comp.get("ha_type") or comp.get("type") or "switch"
        if ha_type == "scene":
            entities.append(TeletaskScene(hub, comp))

    async_add_entities(entities)


class TeletaskScene(Scene):
    """A Teletask mood or timed function exposed as a scene (activate only)."""

    def __init__(self, hub: TeletaskHub, component: dict) -> None:
        self._hub = hub
        self._component = component
        self._function = component["function"]
        self._number = component["number"]
        description = component["description"]
        central_id = hub.central_id

        self._attr_unique_id = f"teletask_{central_id}_{self._function}_{self._number}"
        self._attr_name = description
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{central_id}_{self._function}_{self._number}")},
            name=description,
            manufacturer="Teletask",
            model=component.get("function_name", "Component"),
        )
        if area := component.get("area"):
            device_info["suggested_area"] = area
        self._attr_device_info = device_info

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scene (turn on the mood/timed function)."""
        fn = self._function
        if fn in (FunctionCode.LOCMOOD, FunctionCode.GENMOOD, FunctionCode.TIMEDMOOD):
            await self._hub.async_set_mood(fn, self._number, True)
        elif fn == FunctionCode.TIMEDFNC:
            await self._hub.async_set_timedfnc(self._number, True)
