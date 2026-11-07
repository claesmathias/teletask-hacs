"""Base entity for Teletask."""
from __future__ import annotations

import logging

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_STATE_UPDATED
from .hub import TeletaskHub

_LOGGER = logging.getLogger(__name__)

_SUPPORTS_VIA_DEVICE_ID = "via_device_id" in getattr(dr.DeviceInfo, "__annotations__", {})


def central_link(hub: TeletaskHub) -> dict:
    """Device-info keys that show a component device as "Connected via" the central.

    HA 2026.11 deprecates via_device (removed in 2027.8) in favour of
    via_device_id; older HA versions only know via_device.
    """
    if _SUPPORTS_VIA_DEVICE_ID and hub.central_device_id:
        return {"via_device_id": hub.central_device_id}
    return {"via_device": (DOMAIN, hub.central_id)}


class TeletaskEntity(Entity):
    """Shared base for all Teletask entities."""

    _attr_should_poll = False

    def __init__(self, hub: TeletaskHub, component: dict) -> None:
        self._hub = hub
        self._component = component
        self._function = component["function"]
        self._number = component["number"]
        self._description = component["description"]
        self._state_dict: dict = {}

        central_id = hub.central_id
        fn = self._function
        num = self._number

        self._attr_unique_id = f"teletask_{central_id}_{fn}_{num}"
        self._attr_name = self._description
        device_info = {
            "identifiers": {(DOMAIN, f"{central_id}_{fn}_{num}")},
            "name": self._description,
            "manufacturer": "Teletask",
            "model": component.get("function_name", "Component"),
            **central_link(hub),
        }
        if area := component.get("area"):
            device_info["suggested_area"] = area
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        signal = SIGNAL_STATE_UPDATED.format(
            central_id=self._hub.central_id,
            function=self._function,
            number=self._number,
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._handle_state_update)
        )
        # Apply whatever the hub already has cached, overriding any state HA
        # may have restored from a previous session.
        cached = self._hub.get_state(self._function, self._number)
        _LOGGER.debug(
            "ENTITY INIT   %s  fn=%d num=%d  hub_cache=%s",
            self._description, self._function, self._number, cached,
        )
        self._state_dict = cached
        self.async_write_ha_state()
        # Ask the central for the actual current state.  The CMD=0x10 response
        # arrives asynchronously via _on_event → dispatcher signal →
        # _handle_state_update → async_write_ha_state, guaranteeing the entity
        # always reflects reality regardless of hub-cache timing at startup.
        await self._hub.async_request_state(self._function, self._number)

    @callback
    def _handle_state_update(self, state: dict) -> None:
        prev = self._state_dict
        self._state_dict = state
        _LOGGER.debug(
            "ENTITY UPDATE %s  fn=%d num=%d  %s → %s",
            self._description, self._function, self._number, prev, state,
        )
        self.async_write_ha_state()


class TeletaskCentralStatusEntity(Entity):
    """Diagnostic entity on the central device that follows the hub's status.

    Updated through the hub's status signal (connection changes and events),
    not through the support web page, so it stays available when port 80 is
    unreachable.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _key: str

    def __init__(self, hub: TeletaskHub) -> None:
        self._hub = hub
        self._attr_unique_id = f"teletask_{hub.central_id}_central_{self._key}"
        self._attr_device_info = {"identifiers": {(DOMAIN, hub.central_id)}}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._hub.status_signal, self._handle_status)
        )

    @callback
    def _handle_status(self) -> None:
        self.async_write_ha_state()
