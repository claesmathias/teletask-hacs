"""Teletask sensor platform — temperature, humidity, light, gas, pulse counter."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from datetime import datetime

from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import FunctionCode
from .const import DOMAIN
from .entity import TeletaskCentralStatusEntity, TeletaskEntity
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
    entities: list[SensorEntity] = [
        TeletaskSensor(hub, comp) for comp in hub.get_components_by_function(FunctionCode.SENSOR)
    ]
    entities += [
        TeletaskCentralClockSensor(hub),
        TeletaskCentralClockOffsetSensor(hub),
        TeletaskCentralProjectSensor(hub),
        TeletaskCentralLastEventSensor(hub),
    ]
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


# ----------------------------------------------------------------------
# Central unit diagnostics (from the built-in support web page)
# ----------------------------------------------------------------------


class _TeletaskCentralSensor(CoordinatorEntity, SensorEntity):
    """Diagnostic sensor attached to the central unit device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _key: str

    def __init__(self, hub: TeletaskHub) -> None:
        super().__init__(hub.web_coordinator)
        self._hub = hub
        self._attr_unique_id = f"teletask_{hub.central_id}_central_{self._key}"
        self._attr_device_info = {"identifiers": {(DOMAIN, hub.central_id)}}


class TeletaskCentralClockSensor(_TeletaskCentralSensor):
    """The central's own clock (drives its timed functions)."""

    _key = "clock"
    _attr_name = "Clock"
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        data = self.coordinator.data
        return data.clock if data else None


class TeletaskCentralClockOffsetSensor(_TeletaskCentralSensor):
    """Seconds the central's clock is ahead (+) or behind (−) Home Assistant."""

    _key = "clock_offset"
    _attr_name = "Clock offset"
    _attr_icon = "mdi:clock-alert-outline"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        return data.clock_offset if data else None


class TeletaskCentralProjectSensor(_TeletaskCentralSensor):
    """PROSOFT project file currently loaded in the central."""

    _key = "project_file"
    _attr_name = "Project file"
    _attr_icon = "mdi:file-cog-outline"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        return data.info.project_file if data else None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if not data:
            return {}
        info = data.info
        return {
            "owner": info.project_owner,
            "type_code": info.type_code,
            "os_date": info.os_date,
        }


class TeletaskCentralLastEventSensor(TeletaskCentralStatusEntity, SensorEntity):
    """When the central last reported a state (any output, input, mood, ...).

    The first event after the entity is added is written immediately, so the
    value isn't "unknown" for a minute after every start or reload. After that,
    writes are throttled: at most one per WRITE_INTERVAL, with a trailing write
    so the value is never more than WRITE_INTERVAL out of date. A resubscribe
    delivers hundreds of events in a second, which would otherwise flood the
    recorder.
    """

    WRITE_INTERVAL = 60  # seconds

    _key = "last_event"
    _attr_name = "Last event"
    _attr_icon = "mdi:message-arrow-left-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    _last_write: float | None = None
    _written_value: datetime | None = None
    _cancel_pending: CALLBACK_TYPE | None = None

    @property
    def native_value(self) -> datetime | None:
        return self._hub.last_event

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_scheduled_write)
        # The platform writes the initial state right after this returns.
        self._last_write = self.hass.loop.time()
        self._written_value = self._hub.last_event

    @callback
    def _handle_status(self) -> None:
        if self._written_value is None and self._hub.last_event is not None:
            self._write_now()  # first value: don't make it wait
            return
        if self._cancel_pending is not None:
            return  # a trailing write is already scheduled
        elapsed = self.hass.loop.time() - (self._last_write or 0.0)
        if elapsed >= self.WRITE_INTERVAL:
            self._write_now()
        else:
            self._cancel_pending = async_call_later(
                self.hass, self.WRITE_INTERVAL - elapsed, self._scheduled_write
            )

    @callback
    def _scheduled_write(self, _now: datetime) -> None:
        self._cancel_pending = None
        self._write_now()

    @callback
    def _write_now(self) -> None:
        self._last_write = self.hass.loop.time()
        self._written_value = self._hub.last_event
        self.async_write_ha_state()

    @callback
    def _cancel_scheduled_write(self) -> None:
        if self._cancel_pending is not None:
            self._cancel_pending()
            self._cancel_pending = None
