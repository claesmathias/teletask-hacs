"""Teletask event platform — push-button presses and badge reader attempts."""
from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import FunctionCode
from .const import DOMAIN
from .entity import TeletaskEntity
from .hub import TeletaskHub

_PRESS_EVENTS = {"SHORT_PRESS": "short_press", "CLOSED": "long_press", "OPEN": "release"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TeletaskHub = hass.data[DOMAIN][entry.entry_id]
    entities: list[EventEntity] = [
        TeletaskButtonEvent(hub, comp) for comp in hub.get_components_by_function(FunctionCode.INPUT)
    ]
    entities += [
        TeletaskAccessEvent(hub, comp) for comp in hub.get_components_by_function(FunctionCode.ACCESS)
    ]
    async_add_entities(entities)


class _TeletaskEvent(TeletaskEntity, EventEntity):
    """Fires on reports; state replies during a (re)subscribe are not events."""

    _request_state_on_add = False  # a GET reply would look like a new press

    @callback
    def _handle_state_update(self, state: dict) -> None:
        self._state_dict = state
        if self._hub.resyncing:
            return
        fired = self._event(state)
        if fired is not None:
            event_type, attributes = fired
            self._trigger_event(event_type, attributes)
            self.async_write_ha_state()

    def _event(self, state: dict) -> tuple[str, dict] | None:
        raise NotImplementedError


class TeletaskButtonEvent(_TeletaskEvent):
    """Presses of a push button on a Teletask interface."""

    _attr_event_types = list(_PRESS_EVENTS.values())
    _attr_icon = "mdi:gesture-tap-button"

    def __init__(self, hub: TeletaskHub, component: dict) -> None:
        super().__init__(hub, component)
        self._attr_unique_id = f"{self._attr_unique_id}_press"
        self._attr_name = f"{self._description} press"
        self._held = False

    def _event(self, state: dict) -> tuple[str, dict] | None:
        event_type = _PRESS_EVENTS.get(state.get("state"))
        if event_type == "release":
            if not self._held:
                return None  # no long press to end
            self._held = False
        elif event_type == "long_press":
            self._held = True
        return (event_type, {}) if event_type else None


class TeletaskAccessEvent(_TeletaskEvent):
    """Badge access attempts (DoIP access report)."""

    _attr_event_types = ["allowed", "denied"]
    _attr_icon = "mdi:badge-account-horizontal-outline"

    def _event(self, state: dict) -> tuple[str, dict] | None:
        if state.get("state") not in ("ALLOWED", "DENIED"):
            return None
        attributes = {k: state.get(k) for k in ("card_id", "user", "reader", "timestamp")}
        return state["state"].lower(), attributes
