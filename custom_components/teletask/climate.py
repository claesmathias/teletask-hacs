"""Teletask climate platform — sensor zones of type TEMPERATURECONTROL.

In the library protocol (PICOS, MICROS+) a climate zone is a SENSOR (function
20): its report carries the measured value, target, presets, mode, fan speed
and power, and it is controlled with the SET_TEMP* settings.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import (
    STATE_OFF,
    STATE_ON,
    TEMP_DAY,
    TEMP_FROST,
    TEMP_NIGHT,
    TEMP_STANDBY,
    FunctionCode,
)
from .const import DOMAIN
from .entity import TeletaskEntity
from .hub import TeletaskHub

_LOGGER = logging.getLogger(__name__)

# HA mode → SET setting
_HVAC_SETTINGS = {
    HVACMode.AUTO: 94,
    HVACMode.HEAT: 95,
    HVACMode.COOL: 96,
    HVACMode.FAN_ONLY: 105,
    HVACMode.DRY: 108,
}
# Reported mode (client.CLIMATE_MODES) → HA mode
_REPORTED_MODES = {
    "auto": HVACMode.AUTO,
    "heat": HVACMode.HEAT,
    "heat_plus": HVACMode.HEAT,
    "cool": HVACMode.COOL,
    "vent": HVACMode.FAN_ONLY,
    "dry": HVACMode.DRY,
    "stop": HVACMode.OFF,
}
_PRESET_SETTINGS = {"day": TEMP_DAY, "night": TEMP_NIGHT, "standby": TEMP_STANDBY, "frost": TEMP_FROST}
_FAN_SETTINGS = {"low": 97, "medium": 98, "high": 99, "auto": 89}
_DEFAULT_MODES = ("heat", "cool", "auto")


def is_climate_zone(component: dict) -> bool:
    return component.get("config", {}).get("type") == "TEMPERATURECONTROL"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TeletaskHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        TeletaskClimate(hub, comp)
        for comp in hub.get_components_by_function(FunctionCode.SENSOR)
        if is_climate_zone(comp)
    )


class TeletaskClimate(TeletaskEntity, ClimateEntity):
    """A Teletask climate zone."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_precision = 0.1
    _attr_min_temp = 5.0
    _attr_max_temp = 35.0
    _attr_preset_modes = list(_PRESET_SETTINGS)

    def __init__(self, hub: TeletaskHub, component: dict) -> None:
        super().__init__(hub, component)
        config = component.get("config", {})
        modes = config.get("hvac_modes") or _DEFAULT_MODES
        if isinstance(modes, str):
            modes = [m.strip() for m in modes.split(",")]
        self._attr_hvac_modes = [HVACMode.OFF] + [
            HVACMode(m) for m in modes if m in {mode.value for mode in _HVAC_SETTINGS}
        ]
        self._has_fan = bool(config.get("fan", False))
        if self._has_fan:
            self._attr_fan_modes = list(_FAN_SETTINGS)
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        if self._has_fan:
            features |= ClimateEntityFeature.FAN_MODE
        self._attr_supported_features = features

    # -- state -----------------------------------------------------------

    @property
    def _is_on(self) -> bool:
        return self._state_dict.get("power") == "ON"

    @property
    def current_temperature(self) -> float | None:
        return self._state_dict.get("current_temperature")

    @property
    def target_temperature(self) -> float | None:
        return self._state_dict.get("target_temperature")

    @property
    def hvac_mode(self) -> HVACMode | None:
        if "power" not in self._state_dict:
            return None
        if not self._is_on:
            return HVACMode.OFF
        mode = _REPORTED_MODES.get(self._state_dict.get("mode"))
        if mode is None or mode not in self._attr_hvac_modes:
            # A zone that reports no mode (heating only) still runs.
            return HVACMode.HEAT if HVACMode.HEAT in self._attr_hvac_modes else self._attr_hvac_modes[-1]
        return mode

    @property
    def hvac_action(self) -> HVACAction | None:
        if "power" not in self._state_dict:
            return None
        if not self._is_on:
            return HVACAction.OFF
        output = self._state_dict.get("output")
        if output == 128:
            return HVACAction.COOLING
        if output == 8:
            return HVACAction.HEATING
        return None  # not reported by this central

    @property
    def preset_mode(self) -> str | None:
        return self._state_dict.get("preset")

    @property
    def fan_mode(self) -> str | None:
        return self._state_dict.get("fan_speed") if self._has_fan else None

    @property
    def extra_state_attributes(self) -> dict:
        keys = ("day_preset", "night_preset", "night_cool_preset", "standby_offset", "frost_or_window")
        return {k: self._state_dict[k] for k in keys if k in self._state_dict}

    # -- commands ----------------------------------------------------------

    async def _ensure_on(self) -> None:
        if not self._is_on:
            await self._hub.async_climate_command(self._number, STATE_ON)

    async def async_turn_on(self) -> None:
        await self._hub.async_climate_command(self._number, STATE_ON)
        self._hub.optimistic_merge(FunctionCode.SENSOR, self._number, {"power": "ON"})

    async def async_turn_off(self) -> None:
        await self._hub.async_climate_command(self._number, STATE_OFF)
        self._hub.optimistic_merge(FunctionCode.SENSOR, self._number, {"power": "OFF"})

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self._hub.async_climate_set_target(self._number, float(temperature))
        if (mode := kwargs.get("hvac_mode")) is not None:
            await self.async_set_hvac_mode(mode)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
            return
        await self._ensure_on()
        await self._hub.async_climate_command(self._number, _HVAC_SETTINGS[hvac_mode])
        reported = next(k for k, v in _REPORTED_MODES.items() if v == hvac_mode)
        self._hub.optimistic_merge(FunctionCode.SENSOR, self._number, {"power": "ON", "mode": reported})

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._ensure_on()
        await self._hub.async_climate_command(self._number, _PRESET_SETTINGS[preset_mode])
        self._hub.optimistic_merge(FunctionCode.SENSOR, self._number, {"power": "ON", "preset": preset_mode})

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._ensure_on()
        await self._hub.async_climate_command(self._number, _FAN_SETTINGS[fan_mode])
        self._hub.optimistic_merge(FunctionCode.SENSOR, self._number, {"power": "ON", "fan_speed": fan_mode})
