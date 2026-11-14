"""Teletask notify platform — display messages on the touch panels.

``notify.send_message`` puts the text on the displays of a DISPLAYMESSAGE
component: with a title, the title is line 1 and the message line 2; without
one, the message is spread over both lines. ``teletask.send_display_message``
also takes the type (message or alarm), the beeps and the character set.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import FunctionCode
from .const import DOMAIN
from .entity import TeletaskEntity
from .hub import TeletaskHub

SERVICE_SEND_DISPLAY_MESSAGE = "send_display_message"

SEND_DISPLAY_MESSAGE_SCHEMA = {
    vol.Optional("message"): cv.string,
    vol.Optional("line1"): cv.string,
    vol.Optional("line2"): cv.string,
    vol.Optional("message_type"): vol.In(["message", "alarm"]),
    vol.Optional("beeps"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
    vol.Optional("ascii"): cv.boolean,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TeletaskHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        TeletaskDisplay(hub, comp)
        for comp in hub.get_components_by_function(FunctionCode.DISPLAYMESSAGE)
    )
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SEND_DISPLAY_MESSAGE,
        SEND_DISPLAY_MESSAGE_SCHEMA,
        "async_send_display_message",
    )


class TeletaskDisplay(TeletaskEntity, NotifyEntity):
    """The displays (interfaces) one DISPLAYMESSAGE component writes to."""

    _attr_icon = "mdi:message-text-outline"

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        if title:
            await self._hub.async_display_message(self._number, line1=title, line2=message)
        else:
            await self._hub.async_display_message(self._number, message=message)

    async def async_send_display_message(
        self,
        message: str | None = None,
        line1: str | None = None,
        line2: str | None = None,
        message_type: str | None = None,
        beeps: int | None = None,
        ascii: bool | None = None,  # noqa: A002 — service field name
    ) -> None:
        if message is not None and (line1 is not None or line2 is not None):
            raise vol.Invalid("Use either 'message' or 'line1'/'line2', not both")
        if message is None and line1 is None and line2 is None:
            raise vol.Invalid("Give a 'message' or 'line1'/'line2'")
        await self._hub.async_display_message(
            self._number,
            message=message,
            line1=line1,
            line2=line2,
            message_type=message_type,
            beeps=beeps,
            ascii_mode=ascii,
        )
