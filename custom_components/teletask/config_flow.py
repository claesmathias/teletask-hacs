"""Config flow for Teletask integration — with JSON file upload support."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_CENTRAL_ID,
    CONF_CONFIG_JSON,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Step 1 — connection details only (no JSON here)
STEP_CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_CENTRAL_ID, default="my_teletask"): str,
    }
)

# Step 2 — config file path (resolved on the HA server filesystem)
STEP_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required("config_file_path"): str,
    }
)


class TeletaskConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Two-step config flow:
      Step 1 — host / port / central_id
      Step 2 — path to the config.json file on the HA server
               (e.g. /config/teletask/config.json)
    """

    VERSION = 1

    def __init__(self) -> None:
        self._connection_data: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Step 1 — connection details
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            ok = await self._test_connection(user_input[CONF_HOST], user_input[CONF_PORT])
            if not ok:
                errors["base"] = "cannot_connect"
            else:
                self._connection_data = user_input
                return await self.async_step_config()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_CONNECTION_SCHEMA,
            errors=errors,
            description_placeholders={
                "default_port": str(DEFAULT_PORT),
            },
        )

    # ------------------------------------------------------------------
    # Step 2 — config.json file path
    # ------------------------------------------------------------------

    async def async_step_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        config_json = "{}"

        if user_input is not None:
            file_path = user_input["config_file_path"].strip()

            # Resolve relative paths against /config
            if not os.path.isabs(file_path):
                file_path = os.path.join("/config", file_path)

            # Security guard — must stay within /config
            real_path = os.path.realpath(file_path)
            if not real_path.startswith(os.path.realpath("/config")):
                errors["config_file_path"] = "path_outside_config"
            elif not os.path.isfile(real_path):
                errors["config_file_path"] = "file_not_found"
            else:
                try:
                    with open(real_path, encoding="utf-8") as fh:
                        raw = fh.read()
                    # Validate it's actually JSON
                    json.loads(raw)
                    config_json = raw
                except json.JSONDecodeError:
                    errors["config_file_path"] = "invalid_json"
                except OSError:
                    errors["config_file_path"] = "cannot_read_file"

            if not errors:
                entry_data = {
                    **self._connection_data,
                    CONF_CONFIG_JSON: config_json,
                }
                await self.async_set_unique_id(
                    f"{self._connection_data[CONF_HOST]}:{self._connection_data[CONF_PORT]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Teletask ({self._connection_data[CONF_CENTRAL_ID]})",
                    data=entry_data,
                )

        return self.async_show_form(
            step_id="config",
            data_schema=STEP_CONFIG_SCHEMA,
            errors=errors,
            description_placeholders={
                "example_path": "/config/teletask/config.json",
            },
        )

    # ------------------------------------------------------------------
    # Options flow — allows changing the config file path later
    # ------------------------------------------------------------------

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> TeletaskOptionsFlow:
        return TeletaskOptionsFlow(config_entry)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _test_connection(host: str, port: int) -> bool:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, asyncio.TimeoutError):
            return False


class TeletaskOptionsFlow(config_entries.OptionsFlow):
    """Allow re-pointing to a different config.json after initial setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            file_path = user_input["config_file_path"].strip()
            if not os.path.isabs(file_path):
                file_path = os.path.join("/config", file_path)

            real_path = os.path.realpath(file_path)
            if not real_path.startswith(os.path.realpath("/config")):
                errors["config_file_path"] = "path_outside_config"
            elif not os.path.isfile(real_path):
                errors["config_file_path"] = "file_not_found"
            else:
                try:
                    with open(real_path, encoding="utf-8") as fh:
                        raw = fh.read()
                    json.loads(raw)
                    # Persist new JSON into the config entry data
                    self.hass.config_entries.async_update_entry(
                        self._config_entry,
                        data={**self._config_entry.data, CONF_CONFIG_JSON: raw},
                    )
                    return self.async_create_entry(title="", data={})
                except json.JSONDecodeError:
                    errors["config_file_path"] = "invalid_json"
                except OSError:
                    errors["config_file_path"] = "cannot_read_file"

        current_path = ""  # don't pre-fill for security
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required("config_file_path", default=current_path): str}
            ),
            errors=errors,
            description_placeholders={
                "example_path": "/config/teletask/config.json",
            },
        )
