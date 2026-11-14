"""Teletask coordinator — manages the TCP connection and component registry."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import (
    AUDIO_SOURCES,
    MOTOR_GO_TO_POSITION,
    MOTOR_SLAT_POSITION,
    MOTOR_STOP,
    MOTOR_SUN_PROTECTION,
    REPORT_ONLY_FUNCTIONS,
    RGB_COLOR,
    STATE_OFF,
    STATE_ON,
    TEMP_MANUAL_TARGET,
    TW_COLOR,
    TW_UNCHANGED_BRIGHTNESS,
    TW_UNCHANGED_KELVIN,
    TYPE_FUNCTIONS,
    WRITE_ONLY_FUNCTIONS,
    FunctionCode,
    TeletaskClient,
    TeletaskEvent,
    celsius_to_preset_byte,
    celsius_to_short,
    decode_sensor,
    display_line_length,
    display_targets,
    wrap_display_text,
)
from .const import DOMAIN, SIGNAL_HUB_STATUS, SIGNAL_STATE_UPDATED
from .webinfo import SERIAL_PATH, TIME_PATH, CentralInfo, parse_serial_page, parse_time_page

_LOGGER = logging.getLogger(__name__)

RECONNECT_INTERVAL = 30  # seconds
OUTAGE_ISSUE_DELAY = timedelta(minutes=5)  # disconnected this long → Repairs entry


def _config_bool(value: Any) -> bool | None:
    """true/false from config.json, also written as text; None when not set."""
    if isinstance(value, bool) or value is None:
        return value
    text = str(value).strip().lower()
    if text in ("true", "yes", "1", "ascii"):
        return True
    if text in ("false", "no", "0", "unicode"):
        return False
    return None


def _format_duration(delta: timedelta) -> str:
    """Compact human duration: '45s', '12m 5s', '3h 20m'."""
    seconds = max(0, int(delta.total_seconds()))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
WEB_POLL_INTERVAL = timedelta(minutes=5)
WEB_TIMEOUT = aiohttp.ClientTimeout(total=10)


@dataclass(frozen=True)
class CentralWebData:
    """Snapshot of the central's support web page."""

    info: CentralInfo
    clock: datetime | None
    clock_offset: float | None  # seconds; positive = central runs ahead of HA


class TeletaskHub:
    """Central hub: owns the TCP client, config, and dispatches HA events."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        central_id: str,
        config: dict,
    ) -> None:
        self.hass = hass
        self.host = host
        self.port = port
        self.central_id = central_id
        self.config = config
        self._client = TeletaskClient(host, port, self._on_event, self._on_disconnect)
        self._reconnect_task: asyncio.Task | None = None
        self._unsub_web: Any = None
        self._components: dict[tuple[int, int], dict] = {}
        self._component_states: dict[tuple[int, int], dict] = {}
        # Control-connection status, shown by the central's diagnostic entities.
        self.connected = False
        self.last_event: datetime | None = None
        self.status_signal = SIGNAL_HUB_STATUS.format(central_id=central_id)
        # Device registry id of the central, set by async_setup_entry before the
        # platforms load; component devices link to it ("Connected via").
        self.central_device_id: str | None = None
        self.outage_since: datetime | None = None
        self._reconnect_attempts = 0
        self._cancel_outage_issue: CALLBACK_TYPE | None = None
        # True while (re)subscribing: the central then replays current states,
        # which event entities must not mistake for new presses.
        self.resyncing = False
        self.web_coordinator: DataUpdateCoordinator[CentralWebData] = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"teletask_{central_id}_web",
            update_method=self._async_fetch_web,
            update_interval=WEB_POLL_INTERVAL,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> bool:
        self._parse_config()
        # Best effort: the support page is optional and must never block setup.
        await self.web_coordinator.async_refresh()
        self._unsub_web = self.web_coordinator.async_add_listener(
            self._async_sync_device_registry
        )
        connected = await self._client.connect()
        if connected:
            self._set_connected(True)
            # Run subscription in the background so async_setup_entry returns
            # quickly and entity platforms are set up immediately.  Entities
            # get their initial state from the HA recorder; real-time updates
            # arrive via the dispatcher as the central responds.
            self.hass.async_create_task(self._subscribe_all())
        else:
            _LOGGER.warning(
                "Could not connect to Teletask central at %s:%s (%s) — retrying every %ss",
                self.host, self.port, self._client.last_error, RECONNECT_INTERVAL,
            )
            self._set_connected(False)
            self._schedule_reconnect()
        return True

    async def async_stop(self) -> None:
        if self._unsub_web:
            self._unsub_web()
            self._unsub_web = None
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        # The next setup (reload) re-evaluates the connection; an unloaded or
        # removed entry must not leave a stale Repairs entry behind.
        self._cancel_outage_issue_timer()
        ir.async_delete_issue(self.hass, DOMAIN, self.outage_issue_id)
        await self._client.disconnect()

    # ------------------------------------------------------------------
    # Central web page (serial.cgi / time.cgi)
    # ------------------------------------------------------------------

    @property
    def central_info(self) -> CentralInfo:
        data = self.web_coordinator.data
        return data.info if data else CentralInfo()

    @property
    def central_device_info(self) -> dict[str, Any]:
        """Device-registry kwargs for the central unit itself."""
        info = self.central_info
        device: dict[str, Any] = {
            "identifiers": {(DOMAIN, self.central_id)},
            "name": f"Teletask {info.model or 'central'} ({self.central_id})",
            "manufacturer": "Teletask",
            "model": info.model or "DOIP central unit",
            "configuration_url": f"http://{self.host}/",
        }
        if info.serial_number:
            device["serial_number"] = info.serial_number
        if info.prosoft_version:
            device["sw_version"] = info.prosoft_version
        if info.disk_version:
            device["hw_version"] = info.disk_version
        if info.mac_address:
            device["connections"] = {(dr.CONNECTION_NETWORK_MAC, info.mac_address)}
        return device

    async def _async_get_page(self, path: str) -> str:
        session = async_get_clientsession(self.hass)
        async with session.get(f"http://{self.host}{path}", timeout=WEB_TIMEOUT) as resp:
            resp.raise_for_status()
            # Plain bytes → latin-1 never fails; the UTF-16 filename's NULs are
            # stripped by the parser.
            return (await resp.read()).decode("latin-1")

    async def _async_fetch_web(self) -> CentralWebData:
        try:
            serial_html = await self._async_get_page(SERIAL_PATH)
            time_html = await self._async_get_page(TIME_PATH)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise UpdateFailed(f"Central web page at {self.host} unreachable: {exc}") from exc
        now = dt_util.now()
        clock = parse_time_page(time_html, dt_util.get_default_time_zone())
        offset = round((clock - now).total_seconds()) if clock else None
        return CentralWebData(parse_serial_page(serial_html), clock, offset)

    @callback
    def _async_sync_device_registry(self) -> None:
        """Push refreshed versions/serial/MAC into the central's device entry."""
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, self.central_id)})
        if device is None:
            return
        info = self.central_device_info
        changes = {
            key: info[key]
            for key in ("model", "serial_number", "sw_version", "hw_version")
            if key in info and getattr(device, key) != info[key]
        }
        if "connections" in info and not info["connections"] <= device.connections:
            changes["merge_connections"] = info["connections"]
        if changes:
            registry.async_update_device(device.id, **changes)

    # ------------------------------------------------------------------
    # Config parsing
    # ------------------------------------------------------------------

    def _parse_config(self) -> None:
        component_types = self.config.get("componentsTypes", {})
        function_map = TYPE_FUNCTIONS
        for type_name, components in component_types.items():
            fn = function_map.get(type_name)
            if fn is None:
                continue
            for comp in components:
                number = comp["number"]
                key = (int(fn), number)
                self._components[key] = {
                    "function":      int(fn),
                    "function_name": type_name,
                    "number":        number,
                    "description":   comp.get("description", f"{type_name} {number}"),
                    "type":          comp.get("type"),
                    "ha_type":       comp.get("hatype"),
                    "area":          comp.get("area"),
                    "config":        comp,
                }
                self._component_states[key] = {}

    # ------------------------------------------------------------------
    # Subscribe
    # ------------------------------------------------------------------

    async def _subscribe_all(self) -> None:
        self.resyncing = True
        try:
            await self._subscribe_all_inner()
        finally:
            self.resyncing = False

    async def _subscribe_all_inner(self) -> None:
        _LOGGER.debug(
            "Subscribing %d components across %d function types",
            len(self._components),
            len({fn for fn, _ in self._components}),
        )
        # Step 1: Subscribe per function type (LOG covers all components of that type).
        # The central also sends a "welcome" event with current state for each component.
        seen: set[int] = set()
        for fn, number in self._components:
            if fn in WRITE_ONLY_FUNCTIONS or fn in seen:
                continue
            seen.add(fn)
            if fn in REPORT_ONLY_FUNCTIONS:
                # Badge reports need the DoIP per-device subscription on 202/1;
                # LOG is sent as well for centrals that only know the legacy one.
                _LOGGER.debug("SUBSCRIBE fn=%d num=1", fn)
                await self._client.subscribe_device(fn, 1)
            _LOGGER.debug("LOG subscribe fn=%d", fn)
            await self._client.log_subscribe(fn)
            await asyncio.sleep(0.02)
        # Step 2: GROUPGET per component to guarantee an immediate state reply.
        for fn, number in self._components:
            if not self.can_request_state(fn):
                continue
            _LOGGER.debug("GROUPGET fn=%d num=%d", fn, number)
            await self._client.groupget(fn, number)
            await asyncio.sleep(0.02)
        _LOGGER.debug("Waiting for central to deliver all subscription replies…")
        await asyncio.sleep(1.5)
        _LOGGER.debug("Subscription complete. Cached states: %s", self._component_states)

    # ------------------------------------------------------------------
    # Event / disconnect callbacks (called from client)
    # ------------------------------------------------------------------

    @callback
    def _set_connected(self, connected: bool) -> None:
        if connected:
            self._end_outage()
        else:
            self._start_outage()
        if connected != self.connected:
            self.connected = connected
            async_dispatcher_send(self.hass, self.status_signal)

    # ------------------------------------------------------------------
    # Outage tracking (Repairs entry)
    # ------------------------------------------------------------------

    @property
    def outage_issue_id(self) -> str:
        return f"central_unreachable_{self.central_id}"

    @callback
    def _start_outage(self) -> None:
        if self.outage_since is not None:
            return  # already in an outage
        self.outage_since = dt_util.utcnow()
        self._reconnect_attempts = 0
        # Short blips (e.g. a central reboot) shouldn't raise a Repairs entry.
        self._cancel_outage_issue = async_call_later(
            self.hass, OUTAGE_ISSUE_DELAY, self._create_outage_issue
        )

    @callback
    def _end_outage(self) -> None:
        if self.outage_since is None:
            return
        duration = dt_util.utcnow() - self.outage_since
        # WARNING, not INFO: pairs with the "lost connection" warning and stays
        # visible when debug logging is off (the logger level is WARNING then).
        _LOGGER.warning(
            "Reconnected to Teletask central at %s:%s after %s (%d reconnect attempts)",
            self.host, self.port, _format_duration(duration), self._reconnect_attempts,
        )
        self.outage_since = None
        self._cancel_outage_issue_timer()
        ir.async_delete_issue(self.hass, DOMAIN, self.outage_issue_id)

    @callback
    def _create_outage_issue(self, _now: datetime) -> None:
        self._cancel_outage_issue = None
        if self.outage_since is None:
            return
        since = dt_util.as_local(self.outage_since)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self.outage_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="central_unreachable",
            translation_placeholders={
                "central_id": self.central_id,
                "host": self.host,
                "port": str(self.port),
                "since": since.strftime("%Y-%m-%d %H:%M"),
                "error": self._client.last_error or "connection lost",
            },
        )

    @callback
    def _cancel_outage_issue_timer(self) -> None:
        if self._cancel_outage_issue is not None:
            self._cancel_outage_issue()
            self._cancel_outage_issue = None

    @callback
    def _on_event(self, event: TeletaskEvent) -> None:
        self.last_event = dt_util.utcnow()
        async_dispatcher_send(self.hass, self.status_signal)
        key = (event.function, event.number)
        if event.function == FunctionCode.SENSOR and event.raw and key in self._components:
            # The report layout is the same for every sensor zone; how its
            # values convert depends on the sensor type in config.json.
            config = self._components[key].get("config", {})
            decoded = decode_sensor(config.get("type", "TEMPERATURE"), event.raw, config)
            if decoded is not None:
                event.state = decoded
        prev = self._component_states.get(key)
        self._component_states[key] = event.state
        if prev != event.state:
            _LOGGER.debug(
                "STATE CHANGE  fn=%d num=%d  %s → %s",
                event.function, event.number, prev, event.state,
            )
        else:
            _LOGGER.debug(
                "STATE SAME    fn=%d num=%d  %s (no change)",
                event.function, event.number, event.state,
            )
        signal = SIGNAL_STATE_UPDATED.format(
            central_id=self.central_id,
            function=event.function,
            number=event.number,
        )
        async_dispatcher_send(self.hass, signal, event.state)

    @callback
    def _on_disconnect(self) -> None:
        """Called by the client when the TCP connection is lost."""
        _LOGGER.warning(
            "Lost connection to Teletask central at %s:%s — retrying every %ss",
            self.host, self.port, RECONNECT_INTERVAL,
        )
        self._set_connected(False)
        self._schedule_reconnect()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _optimistic_update(self, function: int, number: int, state: dict) -> None:
        """Update local state immediately after a SET command.

        The central does not echo SET commands back to the sender — push events
        (CMD=0x06) only go to OTHER subscribed clients.  We update state
        optimistically so HA reflects the change without waiting for a push.
        """
        prev = self._component_states.get((function, number))
        _LOGGER.debug(
            "OPTIMISTIC    fn=%d num=%d  %s → %s",
            function, number, prev, state,
        )
        key = (function, number)
        self._component_states[key] = state
        signal = SIGNAL_STATE_UPDATED.format(
            central_id=self.central_id,
            function=function,
            number=number,
        )
        async_dispatcher_send(self.hass, signal, state)

    async def async_set_relay(self, number: int, state: bool) -> None:
        await self._client.set_state(FunctionCode.RELAY, number, 0xFF if state else 0x00)
        self._optimistic_update(FunctionCode.RELAY, number, {"state": "ON" if state else "OFF"})

    async def async_set_dimmer(self, number: int, brightness: int, function: int = FunctionCode.DIMMER) -> None:
        # 103 = PREVIOUS_STATE (restore last brightness); all other values clamp to 0-100.
        if brightness != 103:
            brightness = max(0, min(100, brightness))
        await self._client.set_state(function, number, brightness)
        # Optimistic update: if PREVIOUS_STATE (103) we don't know the actual brightness,
        # so just mark as ON without changing the brightness value.
        if brightness == 103:
            current = dict(self._component_states.get((function, number), {}))
            current["state"] = "ON"
            self._optimistic_update(function, number, current)
        else:
            self._optimistic_update(function, number, {
                "state": "ON" if brightness > 0 else "OFF",
                "brightness": brightness,
            })

    async def async_set_motor(self, number: int, direction: str, function: int = FunctionCode.MOTOR) -> None:
        # STOP=3 per Teletask protocol (SET_MTRSTOP=3, not 0)
        param = {"UP": 1, "DOWN": 2, "STOP": MOTOR_STOP}.get(direction.upper(), MOTOR_STOP)
        await self._client.set_state(function, number, param)

    async def async_set_motor_position(self, number: int, position: int, function: int = FunctionCode.MOTOR) -> None:
        position = max(0, min(100, position))
        # MOTOR_GO_TO_POSITION=11 with position percentage as extra byte
        await self._client.set_state(function, number, MOTOR_GO_TO_POSITION, position)

    async def async_set_mood(self, function: int, number: int, state: bool) -> None:
        await self._client.set_state(function, number, 0xFF if state else 0x00)
        self._optimistic_update(function, number, {"state": "ON" if state else "OFF"})

    async def async_set_flag(self, number: int, state: bool) -> None:
        await self._client.set_state(FunctionCode.FLAG, number, 0xFF if state else 0x00)
        self._optimistic_update(FunctionCode.FLAG, number, {"state": "ON" if state else "OFF"})

    async def async_set_timedfnc(self, number: int, state: bool) -> None:
        await self._client.set_state(FunctionCode.TIMEDFNC, number, 0xFF if state else 0x00)
        self._optimistic_update(FunctionCode.TIMEDFNC, number, {"state": "ON" if state else "OFF"})

    async def async_set_onoff(self, function: int, number: int, state: bool) -> None:
        """ON/OFF for any single-byte function (process, service, alarm, ...)."""
        await self._client.set_state(function, number, STATE_ON if state else STATE_OFF)
        self._optimistic_update(function, number, {
            **self._component_states.get((function, number), {}),
            "state": "ON" if state else "OFF",
        })

    # Motors -------------------------------------------------------------

    async def async_set_motor_tilt(self, function: int, number: int, position: int) -> None:
        await self._client.set_state(function, number, MOTOR_SLAT_POSITION, max(0, min(100, position)))

    async def async_set_motor_sun_protection(self, function: int, number: int, on: bool) -> None:
        await self._client.set_state(function, number, MOTOR_SUN_PROTECTION, STATE_ON if on else STATE_OFF)

    # Climate (sensor zone) ----------------------------------------------

    async def async_climate_command(self, number: int, setting: int, *data: int) -> None:
        await self._client.set_state(FunctionCode.SENSOR, number, setting, *data)

    async def async_climate_set_target(self, number: int, celsius: float) -> None:
        value = celsius_to_short(celsius)
        await self._client.set_state(
            FunctionCode.SENSOR, number, TEMP_MANUAL_TARGET, (value >> 8) & 0xFF, value & 0xFF
        )
        self.optimistic_merge(FunctionCode.SENSOR, number, {"target_temperature": celsius})

    async def async_climate_set_preset_temperature(self, number: int, setting: int, key: str, celsius: float) -> None:
        await self._client.set_state(FunctionCode.SENSOR, number, setting, celsius_to_preset_byte(celsius))
        self.optimistic_merge(FunctionCode.SENSOR, number, {key: celsius})

    # Audio -----------------------------------------------------------------

    async def async_audio_command(self, number: int, setting: int) -> None:
        await self._client.set_state(FunctionCode.AUDIO, number, setting)

    async def async_audio_select_source(self, number: int, source: int) -> None:
        setting = AUDIO_SOURCES.get(source)
        if setting is None:
            raise ValueError(f"Audio source must be 1-8, got {source}")
        await self._client.set_state(FunctionCode.AUDIO, number, setting)
        self.optimistic_merge(FunctionCode.AUDIO, number, {"state": "ON", "source": source})

    # RGB / tunable white -----------------------------------------------

    async def async_set_rgb(self, function: int, number: int, rgb: tuple[int, int, int]) -> None:
        r, g, b = (max(0, min(255, int(c))) for c in rgb)
        await self._client.set_state(function, number, RGB_COLOR, r, g, b)
        self.optimistic_merge(function, number, {"state": "ON" if (r or g or b) else "OFF", "rgb": [r, g, b]})

    async def async_set_tw(
        self, function: int, number: int, kelvin: int | None = None, brightness: int | None = None
    ) -> None:
        k = TW_UNCHANGED_KELVIN if kelvin is None else max(0, min(0xFEFD, int(kelvin)))
        level = TW_UNCHANGED_BRIGHTNESS if brightness is None else max(0, min(100, int(brightness)))
        await self._client.set_state(function, number, TW_COLOR, (k >> 8) & 0xFF, k & 0xFF, level)
        changes: dict[str, Any] = {}
        if kelvin is not None:
            changes["kelvin"] = k
        if brightness is not None:
            changes["brightness"] = level
            changes["state"] = "ON" if level > 0 else "OFF"
        self.optimistic_merge(function, number, changes)

    # Display messages ---------------------------------------------------

    async def async_display_message(
        self,
        number: int,
        *,
        message: str | None = None,
        line1: str | None = None,
        line2: str | None = None,
        message_type: str | None = None,
        beeps: int | None = None,
        ascii_mode: bool | None = None,
    ) -> None:
        """Show text on the displays of a DISPLAYMESSAGE component.

        Either ``message`` (spread over both lines) or ``line1``/``line2``.
        Leaving out the type, beeps or ascii takes the component's default
        from config.json; without one, ascii is chosen when all text is ASCII.
        """
        comp = self._components.get((FunctionCode.DISPLAYMESSAGE, number))
        if comp is None:
            raise ValueError(f"Unknown display message {number}")
        cfg = comp.get("config", {})
        texts = [t for t in (message, line1, line2) if t]
        if ascii_mode is None:
            ascii_mode = _config_bool(cfg.get("ascii"))
        if ascii_mode is None:
            ascii_mode = all(t.isascii() for t in texts)
        ascii_mode = bool(ascii_mode)
        if message is not None:
            line1, line2 = wrap_display_text(message, display_line_length(ascii_mode))
        line1, line2 = line1 or "", line2 or ""
        length = display_line_length(ascii_mode)
        for index, line in ((1, line1), (2, line2)):
            if len(line) > length:
                _LOGGER.warning(
                    "Display message %s line %d %r has %d characters, the display shows %d: cut to %r",
                    number, index, line, len(line), length, line[:length],
                )
        if message_type is None:
            message_type = cfg.get("message_type", "alarm")
        if beeps is None:
            beeps = cfg.get("message_beeps", 1)
        beeps = int(beeps)
        if not 0 <= beeps <= 255:
            _LOGGER.warning("Display message %s asks for %d beeps; the display can do 0 to 255", number, beeps)
        buses, addresses = display_targets(cfg)
        await self._client.display_message(
            buses, addresses, line1, line2,
            is_message=str(message_type).lower() == "message",
            ascii_mode=ascii_mode,
            beeps=beeps,
        )

    # ------------------------------------------------------------------

    def optimistic_merge(self, function: int, number: int, changes: dict) -> None:
        if changes:
            self._optimistic_update(
                function, number, {**self._component_states.get((function, number), {}), **changes}
            )

    @staticmethod
    def can_request_state(function: int) -> bool:
        return function not in WRITE_ONLY_FUNCTIONS and function not in REPORT_ONLY_FUNCTIONS

    async def async_request_state(self, function: int, number: int) -> None:
        """Send a GET to the central; the response arrives via dispatcher signal."""
        if not self.can_request_state(function):
            return
        await self._client.get_state(function, number)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def get_state(self, function: int, number: int) -> dict:
        return self._component_states.get((function, number), {})

    def get_components_by_function(self, function: int) -> list[dict]:
        return [c for (fn, _), c in self._components.items() if fn == function]

    # ------------------------------------------------------------------
    # Reconnect
    # ------------------------------------------------------------------

    def _schedule_reconnect(self) -> None:
        if self._reconnect_task and not self._reconnect_task.done():
            return  # already running
        self._reconnect_task = self.hass.loop.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        while True:
            await asyncio.sleep(RECONNECT_INTERVAL)
            if self._client.connected:
                return
            self._reconnect_attempts += 1
            self._client.clear_subscriptions()
            connected = await self._client.connect()
            if connected:
                self._set_connected(True)
                await self._subscribe_all()
                return
            # Only the start and end of an outage are logged at WARNING; the
            # individual retries would otherwise add an error every 30 s.
            _LOGGER.debug(
                "Reconnect attempt %d to %s:%s failed: %s",
                self._reconnect_attempts, self.host, self.port, self._client.last_error,
            )
