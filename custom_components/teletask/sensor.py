"""Teletask sensor platform — temperature, humidity, light, gas, pulse counter."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import FunctionCode
from .const import DOMAIN
from .entity import TeletaskEntity
from .hub import TeletaskHub

_LOGGER = logging.getLogger(__name__)

_SENSOR_TYPE_MAP = {
    "TEMPERATURE": {
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "HUMIDITY": {
        "device_class": SensorDeviceClass.HUMIDITY,
        "state_class": SensorStateClass.MEASUREMENT,
        "unit": PERCENTAGE,
    },
    "LIGHT": {
        "device_class": SensorDeviceClass.ILLUMINANCE,
        "state_class": SensorStateClass.MEASUREMENT,
        "unit": LIGHT_LUX,
    },
    "GAS": {
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "unit": None,
    },
    "PULSECOUNTER": {
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "unit": None,
    },
    "TEMPERATURECONTROL": {
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "unit": UnitOfTemperature.CELSIUS,
    },
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: TeletaskHub = hass.data[DOMAIN][entry.entry_id]
    entities = [TeletaskSensor(hub, comp) for comp in hub.get_components_by_function(FunctionCode.SENSOR)]
    async_add_entities(entities)


class TeletaskSensor(TeletaskEntity, SensorEntity):
    """A Teletask sensor."""

    def __init__(self, hub: TeletaskHub, component: dict) -> None:
        super().__init__(hub, component)
        sensor_type = component.get("config", {}).get("type", "TEMPERATURE")
        meta = _SENSOR_TYPE_MAP.get(sensor_type, _SENSOR_TYPE_MAP["TEMPERATURE"])
        self._attr_device_class = meta["device_class"]
        self._attr_state_class = meta["state_class"]
        # Allow config.json to override unit
        self._attr_native_unit_of_measurement = (
            component.get("config", {}).get("ha_unit_of_measurement")
            or meta["unit"]
        )

    @property
    def native_value(self) -> float | None:
        raw = self._state_dict.get("value")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict:
        attrs = dict(self._state_dict)
        attrs.pop("value", None)
        return attrs
