"""Config flow for the Teletask integration.

Setup asks for the connection details and the path to config.json. The path is
remembered: the file is re-read on every setup (HA start or integration Reload),
and the options menu can reload it, edit it in the browser, or change settings.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.selector import ObjectSelector, ObjectSelectorConfig

from .configfile import (
    BACKUP_SUFFIX,
    HATYPE_OPTIONS,
    KNOWN_COMPONENT_TYPES,
    GAS_TYPES,
    SENSOR_TYPES,
    TYPE_LABELS,
    ConfigFileError,
    format_config,
    merge_from_editor,
    parse_config,
    read_config_file,
    resolve_config_path,
    split_for_editor,
    validate_config,
    write_config_file,
)
from .const import (
    CONF_CENTRAL_ID,
    CONF_CONFIG_JSON,
    CONF_CONFIG_PATH,
    CONF_DEBUG_LOG,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CONF_CONFIG_FILE_PATH = "config_file_path"   # form field (user-typed path)
CONF_COMPONENTS = "components"               # list editor field
CONF_CONFIG = "config"                       # YAML editor field
EXAMPLE_PATH = "teletask/config.json"

STEP_CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_CENTRAL_ID, default="my_teletask"): str,
    }
)


def _path_schema(default: str) -> vol.Schema:
    return vol.Schema({vol.Required(CONF_CONFIG_FILE_PATH, default=default): str})


class TeletaskConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Step 1: host / port / central_id. Step 2: path to config.json."""

    VERSION = 1
    # 2: INPUT 62→52 and TIMEDFNC 52→5; entity and device ids migrated in __init__.
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._connection_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            result = await _async_test_connection(user_input[CONF_HOST], user_input[CONF_PORT])
            if result == "cannot_resolve":
                errors["base"] = "cannot_resolve"
            elif result != "ok":
                errors["base"] = "cannot_connect"
            else:
                self._connection_data = user_input
                return await self.async_step_config()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_CONNECTION_SCHEMA,
            errors=errors,
            description_placeholders={"default_port": str(DEFAULT_PORT)},
        )

    async def async_step_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        placeholders = {"example_path": EXAMPLE_PATH, "error": ""}
        path_input = EXAMPLE_PATH

        if user_input is not None:
            path_input = user_input[CONF_CONFIG_FILE_PATH]
            try:
                path, text = await _async_load_file(self.hass, path_input)
            except ConfigFileError as err:
                errors["base"] = err.code
                placeholders["error"] = err.detail
            else:
                await self.async_set_unique_id(
                    f"{self._connection_data[CONF_HOST]}:{self._connection_data[CONF_PORT]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Teletask ({self._connection_data[CONF_CENTRAL_ID]})",
                    data={
                        **self._connection_data,
                        CONF_CONFIG_JSON: text,
                        CONF_CONFIG_PATH: path,
                    },
                )

        return self.async_show_form(
            step_id="config",
            data_schema=_path_schema(path_input),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> TeletaskOptionsFlow:
        return TeletaskOptionsFlow()


class TeletaskOptionsFlow(config_entries.OptionsFlow):
    """Configure menu: edit components, edit as YAML, reload the file, settings."""

    def __init__(self) -> None:
        self._working: dict[str, Any] | None = None  # config being edited
        self._dirty = False
        self._edit_type = ""
        self._extras: dict[str, dict[int, dict[str, Any]]] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["edit_components", "edit_yaml", "reload_file", "settings"],
            description_placeholders={"path": self._linked_path or "not linked"},
        )

    # ------------------------------------------------------------------
    # Edit components: type menu → native list editor per type
    # ------------------------------------------------------------------

    async def async_step_edit_components(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if self._working is None:
            try:
                self._working = parse_config(await self._async_current_text())
            except ConfigFileError as err:
                return self.async_abort(
                    reason="config_invalid", description_placeholders={"error": err.detail}
                )
        types = self._working["componentsTypes"]
        options = {
            f"type_{t.lower()}": f"{TYPE_LABELS[t]} ({len(types.get(t, []))})"
            for t in KNOWN_COMPONENT_TYPES
        }
        options["save_components"] = (
            "💾 Save changes and reload" if self._dirty else "Close (no changes)"
        )
        return self.async_show_menu(
            step_id="edit_components",
            menu_options=options,
            description_placeholders={
                "status": "You have unsaved changes." if self._dirty else "No changes yet."
            },
        )

    async def async_step_edit_type(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        assert self._working is not None
        type_name = self._edit_type
        types = self._working["componentsTypes"]
        current = types.get(type_name, [])
        errors: dict[str, str] = {}
        placeholders = {"type": TYPE_LABELS[type_name], "error": ""}

        if user_input is not None:
            items = user_input.get(CONF_COMPONENTS) or []
            updated = merge_from_editor(items, self._extras.get(type_name, {}))
            candidate = {**self._working, "componentsTypes": dict(types)}
            if updated:
                candidate["componentsTypes"][type_name] = updated
            else:
                candidate["componentsTypes"].pop(type_name, None)
            try:
                validate_config(candidate)
            except ConfigFileError as err:
                errors["base"] = err.code
                placeholders["error"] = err.detail
            else:
                if updated != current:
                    self._working = candidate
                    self._dirty = True
                return await self.async_step_edit_components()
        else:
            items, self._extras[type_name] = split_for_editor(type_name, current)

        return self.async_show_form(
            step_id="edit_type",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_COMPONENTS, default=items): ObjectSelector(
                        ObjectSelectorConfig(
                            fields=self._editor_fields(type_name, current),
                            multiple=True,
                            label_field="description",
                            description_field="number",
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_save_components(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if not self._dirty or self._working is None:
            return self.async_abort(reason="no_changes")
        return await self._async_write_config(self._working)

    def _editor_fields(
        self, type_name: str, current: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Native form fields for one component type."""
        fields: dict[str, dict[str, Any]] = {
            "number": {
                "label": "Number",
                "required": True,
                "selector": {"number": {"min": 1, "max": 65535, "step": 1, "mode": "box"}},
            },
            "description": {"label": "Name", "required": True, "selector": {"text": {}}},
        }
        if type_name in HATYPE_OPTIONS:
            values = list(HATYPE_OPTIONS[type_name])
            # Keep values already in the file selectable, even unusual ones.
            values += sorted({c["hatype"] for c in current if c.get("hatype") not in (None, *values)})
            fields["hatype"] = {
                "label": "Home Assistant type",
                "selector": {"select": {
                    "options": [{"value": v, "label": _HATYPE_LABELS.get(v, v)} for v in values],
                    "mode": "dropdown",
                }},
            }
        areas = {a.name for a in ar.async_get(self.hass).async_list_areas()}
        areas |= {c["area"] for c in current if isinstance(c.get("area"), str)}
        fields["area"] = {
            "label": "Area",
            "selector": {"select": {
                "options": sorted(areas), "custom_value": True, "mode": "dropdown",
            }},
        }
        if type_name == "RELAY":
            fields["pulse_ms"] = {
                "label": "Pulse length (buttons only)",
                "selector": {"number": {
                    "min": 50, "max": 10000, "step": 50, "mode": "box",
                    "unit_of_measurement": "ms",
                }},
            }
        if type_name == "SENSOR":
            sensor_types = list(SENSOR_TYPES)
            sensor_types += sorted({c["type"] for c in current if c.get("type") not in (None, *sensor_types)})
            fields["type"] = {
                "label": "Sensor type",
                "selector": {"select": {
                    "options": [{"value": v, "label": v.title()} for v in sensor_types],
                    "mode": "dropdown",
                }},
            }
            fields["decimals"] = {"label": "Decimals", "selector": {"text": {}}}
            fields["ha_unit_of_measurement"] = {
                "label": "Unit (overrides the default)", "selector": {"text": {}},
            }
            fields["gas_type"] = {
                "label": "Analog input range (gas sensors)",
                "selector": {"select": {"options": list(GAS_TYPES), "mode": "dropdown"}},
            }
            fields["gas_min"] = {"label": "Value at the bottom of the range (gas)", "selector": {"number": {"mode": "box", "step": "any"}}}
            fields["gas_max"] = {"label": "Value at the top of the range (gas)", "selector": {"number": {"mode": "box", "step": "any"}}}
            fields["pulses_per_unit"] = {
                "label": "Pulses per unit (pulse counters)",
                "selector": {"number": {"min": 1, "mode": "box", "step": "any"}},
            }
            fields["total_unit_of_measurement"] = {
                "label": "Unit of the total (pulse counters), e.g. kWh", "selector": {"text": {}},
            }
            fields["hvac_modes"] = {
                "label": "Climate modes, comma-separated: heat, cool, auto, fan_only, dry (climate zones)",
                "selector": {"text": {}},
            }
        yes_no = [{"value": "true", "label": "Yes"}, {"value": "false", "label": "No"}]
        if type_name == "SENSOR":
            fields["fan"] = {
                "label": "Has fan speeds (climate zones)",
                "selector": {"select": {"options": yes_no, "mode": "dropdown"}},
            }
        if type_name in ("MOTOR", "MOTORGRP"):
            fields["tilt"] = {
                "label": "Has slats (tilt control, DoIP)",
                "selector": {"select": {"options": yes_no, "mode": "dropdown"}},
            }
            fields["sun_protection"] = {
                "label": "Sun protection switch",
                "selector": {"select": {"options": yes_no, "mode": "dropdown"}},
            }
        if type_name == "AUDIO":
            fields["sources"] = {
                "label": "Source names, comma-separated (source 1, 2, ...)",
                "selector": {"text": {}},
            }
        if type_name == "DISPLAYMESSAGE":
            fields["bus_numbers"] = {
                "label": "Bus numbers, comma-separated (empty: all displays)",
                "selector": {"text": {}},
            }
            fields["address_numbers"] = {
                "label": "Interface addresses, same order as the buses",
                "selector": {"text": {}},
            }
            fields["message_type"] = {
                "label": "Default type",
                "selector": {"select": {"options": [
                    {"value": "message", "label": "Message"},
                    {"value": "alarm", "label": "Alarm"},
                ], "mode": "dropdown"}},
            }
            fields["message_beeps"] = {
                "label": "Default number of beeps",
                "selector": {"number": {"min": 0, "max": 255, "step": 1, "mode": "box"}},
            }
            fields["ascii"] = {
                "label": "Character set (empty: ASCII when the text allows it)",
                "selector": {"select": {"options": [
                    {"value": "true", "label": "ASCII, 16 characters per line"},
                    {"value": "false", "label": "Any character, 8 per line"},
                ], "mode": "dropdown"}},
            }
        return fields

    # ------------------------------------------------------------------
    # Edit as YAML (code editor)
    # ------------------------------------------------------------------

    async def async_step_edit_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error": "", "note": "", "target": self._target_description}

        if user_input is not None:
            data = user_input.get(CONF_CONFIG)
            try:
                validate_config(data)
            except ConfigFileError as err:
                errors["base"] = err.code
                placeholders["error"] = err.detail
            else:
                return await self._async_write_config(data)
        else:
            try:
                data = parse_config(await self._async_current_text())
            except ConfigFileError as err:
                # Open the last loaded copy so a broken file can be repaired here.
                data = json.loads(self.config_entry.data.get(CONF_CONFIG_JSON, "{}"))
                placeholders["note"] = (
                    f"**The file currently has an error ({err.detail}).** "
                    "Showing the last successfully loaded configuration instead; "
                    "saving replaces the file.\n\n"
                )

        return self.async_show_form(
            step_id="edit_yaml",
            data_schema=vol.Schema({vol.Required(CONF_CONFIG, default=data): ObjectSelector()}),
            errors=errors,
            description_placeholders=placeholders,
        )

    # ------------------------------------------------------------------
    # Reload from file (also used to link or change the file)
    # ------------------------------------------------------------------

    async def async_step_reload_file(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        placeholders = {"example_path": EXAMPLE_PATH, "error": ""}
        path_input = self._linked_path or EXAMPLE_PATH

        if user_input is not None:
            path_input = user_input[CONF_CONFIG_FILE_PATH]
            try:
                path, text = await _async_load_file(self.hass, path_input)
            except ConfigFileError as err:
                errors["base"] = err.code
                placeholders["error"] = err.detail
            else:
                return self._async_save_and_reload(text, path)

        return self.async_show_form(
            step_id="reload_file",
            data_schema=_path_schema(path_input),
            errors=errors,
            description_placeholders=placeholders,
        )

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        current_debug = self.config_entry.options.get(
            CONF_DEBUG_LOG, self.config_entry.data.get(CONF_DEBUG_LOG, False)
        )
        if user_input is not None:
            # The update listener applies the log level; no reload needed.
            return self.async_create_entry(
                data={**self.config_entry.options, CONF_DEBUG_LOG: user_input[CONF_DEBUG_LOG]}
            )
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {vol.Optional(CONF_DEBUG_LOG, default=current_debug): bool}
            ),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def _linked_path(self) -> str | None:
        return self.config_entry.data.get(CONF_CONFIG_PATH)

    @property
    def _target_description(self) -> str:
        path = self._linked_path
        if path:
            return f"`{path}` (the previous version is kept as `{path}{BACKUP_SUFFIX}`)"
        return "the integration only — no config.json file is linked"

    async def _async_current_text(self) -> str:
        """The linked file's text if readable (even if invalid), else the stored copy."""
        stored = self.config_entry.data.get(CONF_CONFIG_JSON, "{}")
        if not self._linked_path:
            return stored
        try:
            return await self.hass.async_add_executor_job(_read_raw, self._linked_path)
        except OSError:
            return stored

    async def _async_write_config(self, data: dict[str, Any]) -> FlowResult:
        """Format, write to the linked file (if any), store and reload."""
        text = format_config(data)
        path = self._linked_path
        if path:
            try:
                await self.hass.async_add_executor_job(write_config_file, path, text)
            except ConfigFileError as err:
                return self.async_abort(
                    reason="cannot_write_file", description_placeholders={"error": err.detail}
                )
        return self._async_save_and_reload(text, path)

    def _async_save_and_reload(self, text: str, path: str | None) -> FlowResult:
        data = {**self.config_entry.data, CONF_CONFIG_JSON: text}
        if path:
            data[CONF_CONFIG_PATH] = path
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)
        self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
        return self.async_create_entry(data=dict(self.config_entry.options))


def _make_type_step(type_name: str):
    async def step(self: TeletaskOptionsFlow, user_input: dict[str, Any] | None = None) -> FlowResult:
        self._edit_type = type_name
        return await self.async_step_edit_type()

    step.__name__ = f"async_step_type_{type_name.lower()}"
    return step


# One menu entry per component type: "type_relay", "type_dimmer", ...
for _type_name in KNOWN_COMPONENT_TYPES:
    setattr(TeletaskOptionsFlow, f"async_step_type_{_type_name.lower()}", _make_type_step(_type_name))

_HATYPE_LABELS = {
    "light": "Light",
    "switch": "Switch",
    "button": "Button (momentary pulse)",
    "scene": "Scene (activate only)",
    "input_boolean": "Switch (input_boolean)",
}


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

def _read_raw(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


async def _async_load_file(hass, path_input: str) -> tuple[str, str]:
    """Resolve, read and validate a config file. Returns (real path, text)."""

    def _load() -> tuple[str, str]:
        path = resolve_config_path(path_input, hass.config.config_dir)
        text, _ = read_config_file(path)
        return path, text

    return await hass.async_add_executor_job(_load)


async def _async_test_connection(host: str, port: int) -> str:
    """Test TCP reachability. Returns 'ok', 'cannot_resolve', or 'cannot_connect'."""
    loop = asyncio.get_running_loop()
    # Resolve hostname explicitly first so we can give a specific DNS error.
    try:
        await loop.run_in_executor(None, socket.getaddrinfo, host, port)
    except socket.gaierror:
        _LOGGER.warning("DNS resolution failed for %s", host)
        return "cannot_resolve"
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=10
        )
        writer.close()
        await writer.wait_closed()
        return "ok"
    except (OSError, asyncio.TimeoutError):
        return "cannot_connect"
