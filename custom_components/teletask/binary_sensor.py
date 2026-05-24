"""Teletask binary sensor platform — digital inputs and conditions."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
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

    for comp in hub.get_components_by_function(FunctionCode.INPUT):
        entities.append(TeletaskInputBinarySensor(hub, comp))

    for comp in hub.get_components_by_function(FunctionCode.COND):
        entities.append(TeletaskConditionBinarySensor(hub, comp))

    async_add_entities(entities)


class TeletaskInputBinarySensor(TeletaskEntity, BinarySensorEntity):
    """A Teletask digital input (button/contact)."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    @property
    def is_on(self) -> bool:
        state = self._state_dict.get("state", "OPEN")
        # CLOSED = pressed/active, OPEN = not pressed
        return state in ("CLOSED", "SHORT_PRESS", "LONG_PRESS")

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "raw_state": self._state_dict.get("state"),
            "press_duration_millis": self._state_dict.get("press_duration_millis"),
        }


class TeletaskConditionBinarySensor(TeletaskEntity, BinarySensorEntity):
    """A Teletask condition."""

    @property
    def is_on(self) -> bool:
        return self._state_dict.get("state") == "ON"
