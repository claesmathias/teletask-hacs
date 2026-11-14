"""Loading, validating and saving the Teletask component configuration (config.json).

This module has no Home Assistant imports so it can be unit-tested without HA
installed. All functions that touch the filesystem are blocking and must be run
in an executor from async code.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Any

# Component types the hub knows how to map to a Teletask function code.
KNOWN_COMPONENT_TYPES = (
    "RELAY",
    "DIMMER",
    "MOTOR",
    "LOCMOOD",
    "GENMOOD",
    "TIMEDMOOD",
    "FLAG",
    "SENSOR",
    "COND",
    "INPUT",
    "TIMEDFNC",
    "PROCES",
    "SERVICE",
    "AUDIO",
    "DISPLAYMESSAGE",
    "DIGITALINPUT",
    "DIMMERGRP",
    "MOTORGRP",
    "RGB",
    "RGBGRP",
    "TW",
    "TWGRP",
    "ALARM",
    "ACCESS",
)

BACKUP_SUFFIX = ".bak"


class ConfigFileError(Exception):
    """A config problem the UI can show.

    ``code`` matches a key in the ``error`` section of strings.json;
    ``detail`` is a human-readable explanation shown via the ``{error}``
    placeholder.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def resolve_config_path(path: str, config_dir: str) -> str:
    """Resolve ``path`` against ``config_dir`` and make sure it stays inside it.

    Relative paths are taken relative to ``config_dir``. Returns the real path.
    Raises ConfigFileError("path_outside_config") or ("file_not_found").
    """
    path = path.strip()
    if not path:
        raise ConfigFileError("file_not_found", "No path given.")
    if not os.path.isabs(path):
        path = os.path.join(config_dir, path)
    real_path = os.path.realpath(path)
    real_dir = os.path.realpath(config_dir)
    if os.path.commonpath([real_path, real_dir]) != real_dir:
        raise ConfigFileError("path_outside_config", real_path)
    if not os.path.isfile(real_path):
        raise ConfigFileError("file_not_found", real_path)
    return real_path


def parse_config(text: str) -> dict[str, Any]:
    """Parse and validate config JSON text. Returns the parsed dict.

    Raises ConfigFileError("invalid_json") with line/column, or
    ConfigFileError("invalid_config") naming the first structural problem.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigFileError(
            "invalid_json", f"line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    validate_config(data)
    return data


def validate_config(data: Any) -> None:
    """Check the structure the hub relies on. Raises ConfigFileError("invalid_config")."""

    def fail(detail: str) -> None:
        raise ConfigFileError("invalid_config", detail)

    if not isinstance(data, dict):
        fail("The top level must be a JSON object.")
    types = data.get("componentsTypes")
    if not isinstance(types, dict):
        fail('Missing "componentsTypes" object.')

    for type_name, components in types.items():
        if type_name not in KNOWN_COMPONENT_TYPES:
            fail(
                f'Unknown component type "{type_name}". '
                f"Known types: {', '.join(KNOWN_COMPONENT_TYPES)}."
            )
        if not isinstance(components, list):
            fail(f"{type_name} must be a list of components.")
        seen: set[int] = set()
        for index, comp in enumerate(components, start=1):
            where = f"{type_name} entry {index}"
            if not isinstance(comp, dict):
                fail(f"{where} must be an object.")
            number = comp.get("number")
            # bool is a subclass of int; reject it explicitly.
            if not isinstance(number, int) or isinstance(number, bool) or number < 1:
                fail(f'{where} needs a positive whole "number".')
            if number in seen:
                fail(f"{type_name} number {number} appears more than once.")
            seen.add(number)
            description = comp.get("description")
            if description is not None and not isinstance(description, str):
                fail(f'{type_name} {number}: "description" must be text.')
            if type_name == "DISPLAYMESSAGE":
                _validate_display(comp, f"DISPLAYMESSAGE {number}", fail)
            if type_name == "ACCESS" and number != 1:
                fail("ACCESS: the central reports badge readers as number 1 only.")


def _numbers(value: Any) -> list[int] | None:
    """A comma-separated string or list of whole numbers; None if invalid."""
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
    elif isinstance(value, list):
        parts = value
    elif isinstance(value, int) and not isinstance(value, bool):
        parts = [value]
    else:
        return None
    result = []
    for part in parts:
        try:
            number = int(part)
        except (TypeError, ValueError):
            return None
        if isinstance(part, bool) or not 0 <= number <= 255:
            return None
        result.append(number)
    return result


def _validate_display(comp: dict[str, Any], where: str, fail: Any) -> None:
    buses = comp.get("bus_numbers")
    addresses = comp.get("address_numbers")
    if buses is not None or addresses is not None:  # both left out: every display
        bus_list, address_list = _numbers(buses), _numbers(addresses)
        if bus_list is None or address_list is None:
            fail(f'{where}: "bus_numbers" and "address_numbers" need comma-separated numbers 0-255, e.g. "1,1".')
        if len(bus_list) != len(address_list):
            fail(f'{where}: "bus_numbers" and "address_numbers" must list the same number of entries.')
    message_type = comp.get("message_type")
    if message_type is not None and message_type not in MESSAGE_TYPES:
        fail(f'{where}: "message_type" must be "message" or "alarm".')
    beeps = comp.get("message_beeps")
    if beeps is not None and (not isinstance(beeps, int) or isinstance(beeps, bool) or not 0 <= beeps <= 255):
        fail(f'{where}: "message_beeps" must be a whole number from 0 to 255.')


def read_config_file(path: str) -> tuple[str, dict[str, Any]]:
    """Read and validate a config file. Returns (raw text, parsed dict)."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError as exc:
        raise ConfigFileError("file_not_found", path) from exc
    except OSError as exc:
        raise ConfigFileError("cannot_read_file", f"{path}: {exc.strerror or exc}") from exc
    return text, parse_config(text)


def write_config_file(path: str, text: str) -> None:
    """Atomically replace ``path`` with ``text``, keeping the old file as ``path + .bak``.

    The text is written exactly as given so the user's formatting is preserved.
    """
    directory = os.path.dirname(path) or "."
    try:
        if os.path.isfile(path):
            shutil.copy2(path, path + BACKUP_SUFFIX)
        fd, tmp_path = tempfile.mkstemp(prefix=".teletask-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text if text.endswith("\n") else text + "\n")
            if os.path.isfile(path):
                shutil.copymode(path, tmp_path)
            os.replace(tmp_path, path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
    except OSError as exc:
        raise ConfigFileError("cannot_write_file", f"{path}: {exc.strerror or exc}") from exc


# ----------------------------------------------------------------------
# Structured editing (Configure → Edit components)
# ----------------------------------------------------------------------

TYPE_LABELS = {
    "RELAY": "Relays",
    "DIMMER": "Dimmers",
    "MOTOR": "Motors",
    "LOCMOOD": "Local moods",
    "GENMOOD": "General moods",
    "TIMEDMOOD": "Timed moods",
    "FLAG": "Flags",
    "SENSOR": "Sensors and climate zones",
    "COND": "Conditions",
    "INPUT": "Push buttons (interface inputs)",
    "TIMEDFNC": "Timed functions",
    "PROCES": "Process functions",
    "SERVICE": "Service functions",
    "AUDIO": "Audio zones",
    "DISPLAYMESSAGE": "Display messages",
    "DIGITALINPUT": "Digital inputs (DoIP)",
    "DIMMERGRP": "Dimmer groups (DoIP)",
    "MOTORGRP": "Motor groups (DoIP)",
    "RGB": "RGB lights (DoIP)",
    "RGBGRP": "RGB groups (DoIP)",
    "TW": "Tunable white (DoIP)",
    "TWGRP": "Tunable white groups (DoIP)",
    "ALARM": "Alarms (DoIP)",
    "ACCESS": "Badge readers (DoIP)",
}

# Which "hatype" values each type supports (types without one have no hatype field).
HATYPE_OPTIONS = {
    "RELAY": ("light", "switch", "button"),
    "DIMMER": ("light",),
    "LOCMOOD": ("scene", "switch"),
    "GENMOOD": ("scene", "switch"),
    "TIMEDMOOD": ("scene", "switch"),
    "FLAG": ("switch", "input_boolean"),
    "TIMEDFNC": ("switch", "scene"),
}

SENSOR_TYPES = ("TEMPERATURE", "HUMIDITY", "LIGHT", "GAS", "PULSECOUNTER", "TEMPERATURECONTROL")
GAS_TYPES = ("4-20ma", "0-20ma", "0-10v", "5-10v")
MESSAGE_TYPES = ("message", "alarm")

_TYPE_SPECIFIC_FIELDS = {
    "RELAY": ("pulse_ms",),
    "SENSOR": ("type", "decimals", "ha_unit_of_measurement",
               "gas_type", "gas_min", "gas_max", "pulses_per_unit", "total_unit_of_measurement",
               "hvac_modes", "fan"),
    "MOTOR": ("tilt", "sun_protection"),
    "MOTORGRP": ("tilt", "sun_protection"),
    "AUDIO": ("sources",),
    "DISPLAYMESSAGE": ("bus_numbers", "address_numbers", "message_type", "message_beeps", "ascii"),
}

# Key order used when writing components, so files stay easy to scan.
_KEY_ORDER = (
    "number", "description", "hatype", "type", "area",
    "pulse_ms", "decimals", "ha_unit_of_measurement",
    "gas_type", "gas_min", "gas_max", "pulses_per_unit", "total_unit_of_measurement",
    "hvac_modes", "fan", "tilt", "sun_protection", "sources",
    "bus_numbers", "address_numbers", "message_type", "message_beeps", "ascii",
)
_INT_FIELDS = ("number", "pulse_ms", "message_beeps")
# Editor selects return text; these keys are stored as JSON booleans.
_BOOL_FIELDS = ("ascii", "tilt", "sun_protection", "fan")


def editable_fields(type_name: str) -> tuple[str, ...]:
    """Keys the structured editor shows for a component type."""
    fields = ["number", "description"]
    if type_name in HATYPE_OPTIONS:
        fields.append("hatype")
    fields.append("area")
    fields.extend(_TYPE_SPECIFIC_FIELDS.get(type_name, ()))
    return tuple(fields)


def split_for_editor(
    type_name: str, components: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    """Split components into editor items and the keys the editor doesn't show.

    HA's object selector rejects keys it has no field for, so anything else
    (e.g. a legacy "type" on a mood) is held back per component number and put
    back by merge_from_editor.
    """
    fields = editable_fields(type_name)
    items: list[dict[str, Any]] = []
    extras: dict[int, dict[str, Any]] = {}
    for comp in components:
        item = {k: v for k, v in comp.items() if k in fields}
        if "decimals" in item and not isinstance(item["decimals"], str):
            item["decimals"] = str(item["decimals"])  # shown in a text field
        for key in _BOOL_FIELDS:
            if isinstance(item.get(key), bool):
                item[key] = "true" if item[key] else "false"  # shown in a select
        for key in ("bus_numbers", "address_numbers", "sources", "hvac_modes"):
            if isinstance(item.get(key), list):
                item[key] = ", ".join(str(v) for v in item[key])  # shown in a text field
        items.append(item)
        hidden = {k: v for k, v in comp.items() if k not in fields}
        if hidden:
            extras[comp["number"]] = hidden
    return items, extras


def merge_from_editor(
    items: list[dict[str, Any]], extras: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Turn editor items back into components: clean, restore extras, sort."""
    components = []
    for item in items:
        comp = {k: v for k, v in item.items() if v is not None and v != ""}
        for key in _INT_FIELDS:
            value = comp.get(key)
            if isinstance(value, float) and value.is_integer():
                comp[key] = int(value)
        for key in _BOOL_FIELDS:
            if comp.get(key) in ("true", "false"):
                comp[key] = comp[key] == "true"
        for key, value in extras.get(comp.get("number"), {}).items():
            comp.setdefault(key, value)
        components.append(_ordered(comp))
    components.sort(key=lambda c: (not isinstance(c.get("number"), int), c.get("number", 0)))
    return components


def _ordered(comp: dict[str, Any]) -> dict[str, Any]:
    first = {k: comp[k] for k in _KEY_ORDER if k in comp}
    return {**first, **{k: v for k, v in comp.items() if k not in first}}


def format_config(data: dict[str, Any]) -> str:
    """Serialize the config with one component per line, like a hand-written file."""

    def dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    lines = ["{"]
    top = [(k, v) for k, v in data.items() if k != "componentsTypes"]
    types = data.get("componentsTypes", {})
    for key, value in top:
        lines.append(f"  {dump(key)}: {dump(value)},")
    lines.append('  "componentsTypes": {')
    type_items = list(types.items())
    for t_index, (type_name, components) in enumerate(type_items):
        type_comma = "," if t_index < len(type_items) - 1 else ""
        if not components:
            lines.append(f"    {dump(type_name)}: []{type_comma}")
            continue
        lines.append(f"    {dump(type_name)}: [")
        for c_index, comp in enumerate(components):
            inner = ", ".join(f"{dump(k)}: {dump(v)}" for k, v in comp.items())
            comma = "," if c_index < len(components) - 1 else ""
            lines.append(f"      {{ {inner} }}{comma}")
        lines.append(f"    ]{type_comma}")
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"
