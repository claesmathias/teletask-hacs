"""Base entity for Teletask."""
from __future__ import annotations

import logging

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_STATE_UPDATED
from .hub import TeletaskHub

_LOGGER = logging.getLogger(__name__)


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
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{central_id}_{fn}_{num}")},
            "name": self._description,
            "manufacturer": "Teletask",
            "model": component.get("function_name", "Component"),
        }

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
