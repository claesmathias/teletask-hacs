"""Teletask cover platform — MOTOR components (blinds, shutters, garage doors)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
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
    entities = [TeletaskCover(hub, comp) for comp in hub.get_components_by_function(FunctionCode.MOTOR)]
    async_add_entities(entities)


class TeletaskCover(TeletaskEntity, CoverEntity):
    """A Teletask motor exposed as a HA cover (blind/shutter)."""

    _attr_device_class = CoverDeviceClass.BLIND
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    @property
    def is_closed(self) -> bool | None:
        pos = self._state_dict.get("current_position")
        if pos is None:
            return None
        return pos == 0

    @property
    def is_opening(self) -> bool:
        return (
            self._state_dict.get("state") == "ON"
            and self._state_dict.get("last_direction") == "UP"
        )

    @property
    def is_closing(self) -> bool:
        return (
            self._state_dict.get("state") == "ON"
            and self._state_dict.get("last_direction") == "DOWN"
        )

    @property
    def current_cover_position(self) -> int | None:
        """Return position 0-100 (100 = fully open)."""
        return self._state_dict.get("current_position")

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._hub.async_set_motor(self._number, "UP")

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._hub.async_set_motor(self._number, "DOWN")

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._hub.async_set_motor(self._number, "STOP")

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        position = kwargs.get(ATTR_POSITION, 0)
        await self._hub.async_set_motor_position(self._number, position)
