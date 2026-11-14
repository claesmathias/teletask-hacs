"""Teletask number platform — preset temperatures of climate zones."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import TEMP_SET_DAY, TEMP_SET_NIGHT, TEMP_SET_NIGHTCOOL, FunctionCode
from .climate import is_climate_zone
from .const import DOMAIN
from .entity import TeletaskEntity
from .hub import TeletaskHub

# (state key, SET setting, name suffix)
_PRESETS = (
    ("day_preset", TEMP_SET_DAY, "day temperature"),
    ("night_preset", TEMP_SET_NIGHT, "night temperature"),
    ("night_cool_preset", TEMP_SET_NIGHTCOOL, "night temperature when cooling"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TeletaskHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        TeletaskPresetNumber(hub, comp, key, setting, suffix)
        for comp in hub.get_components_by_function(FunctionCode.SENSOR)
        if is_climate_zone(comp)
        for key, setting, suffix in _PRESETS
    )


class TeletaskPresetNumber(TeletaskEntity, NumberEntity):
    """One preset temperature of a climate zone (SET_TEMPSET*, 0.5 °C steps)."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 5.0
    _attr_native_max_value = 35.0
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: TeletaskHub, component: dict, key: str, setting: int, suffix: str) -> None:
        super().__init__(hub, component)
        self._key = key
        self._setting = setting
        self._attr_unique_id = f"{self._attr_unique_id}_{key}"
        self._attr_name = f"{self._description} {suffix}"
        if key == "night_cool_preset":
            self._attr_entity_registry_enabled_default = False  # only for zones that cool

    @property
    def native_value(self) -> float | None:
        return self._state_dict.get(self._key)

    async def async_set_native_value(self, value: float) -> None:
        await self._hub.async_climate_set_preset_temperature(self._number, self._setting, self._key, value)
