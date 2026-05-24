"""Config flow for Teletask integration."""
from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .client import TeletaskClient
from .const import (
    CONF_CENTRAL_ID,
    CONF_CONFIG_JSON,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_CENTRAL_ID, default="my_teletask"): str,
        vol.Required(CONF_CONFIG_JSON, default="{}"): str,
    }
)


class TeletaskConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Teletask."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate JSON
            try:
                json.loads(user_input[CONF_CONFIG_JSON])
            except json.JSONDecodeError:
                errors[CONF_CONFIG_JSON] = "invalid_json"

            if not errors:
                # Test TCP connection
                ok = await self._test_connection(
                    user_input[CONF_HOST], user_input[CONF_PORT]
                )
                if not ok:
                    errors["base"] = "cannot_connect"

            if not errors:
                await self.async_set_unique_id(
                    f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Teletask ({user_input[CONF_CENTRAL_ID]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "config_example": (
                    '{"type":"MICROS_PLUS","componentsTypes":{"RELAY":[{"number":1,"description":"Light","type":"light"}]}}'
                )
            },
        )

    @staticmethod
    async def _test_connection(host: str, port: int) -> bool:
        """Try to open a TCP connection to verify host/port."""
        import asyncio

        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, asyncio.TimeoutError):
            return False
