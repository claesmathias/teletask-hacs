"""Base entity for Teletask."""
from __future__ import annotations

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_STATE_UPDATED
from .hub import TeletaskHub


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
        # Load state already cached by the hub from startup subscriptions.
        # Call async_write_ha_state() explicitly so we override any stale state
        # HA may have restored from a previous session.
        self._state_dict = self._hub.get_state(self._function, self._number)
        self.async_write_ha_state()

    def _handle_state_update(self, state: dict) -> None:
        self._state_dict = state
        self.async_write_ha_state()
