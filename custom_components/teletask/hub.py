"""Teletask coordinator — manages the TCP connection and component registry."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .client import FunctionCode, TeletaskClient, TeletaskEvent, MOTOR_STOP, MOTOR_GO_TO_POSITION
from .const import DOMAIN, SIGNAL_STATE_UPDATED

_LOGGER = logging.getLogger(__name__)

RECONNECT_INTERVAL = 30  # seconds


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
        self._components: dict[tuple[int, int], dict] = {}
        self._component_states: dict[tuple[int, int], dict] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> bool:
        self._parse_config()
        connected = await self._client.connect()
        if connected:
            await self._subscribe_all()
        else:
            _LOGGER.warning(
                "Could not connect to Teletask central at %s:%s — will retry every %ss",
                self.host, self.port, RECONNECT_INTERVAL,
            )
            self._schedule_reconnect()
        return True

    async def async_stop(self) -> None:
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        await self._client.disconnect()

    # ------------------------------------------------------------------
    # Config parsing
    # ------------------------------------------------------------------

    def _parse_config(self) -> None:
        component_types = self.config.get("componentsTypes", {})
        function_map = {
            "RELAY":     FunctionCode.RELAY,
            "DIMMER":    FunctionCode.DIMMER,
            "MOTOR":     FunctionCode.MOTOR,
            "LOCMOOD":   FunctionCode.LOCMOOD,
            "GENMOOD":   FunctionCode.GENMOOD,
            "TIMEDMOOD": FunctionCode.TIMEDMOOD,
            "FLAG":      FunctionCode.FLAG,
            "SENSOR":    FunctionCode.SENSOR,
            "COND":      FunctionCode.COND,
            "INPUT":     FunctionCode.INPUT,
            "TIMEDFNC":  FunctionCode.TIMEDFNC,
        }
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
                    "config":        comp,
                }
                self._component_states[key] = {}

    # ------------------------------------------------------------------
    # Subscribe
    # ------------------------------------------------------------------

    async def _subscribe_all(self) -> None:
        # Step 1: Subscribe per function type (LOG covers all components of that type).
        # The central also sends a "welcome" event with current state for each component.
        seen: set[int] = set()
        for fn, _ in self._components:
            if fn not in seen:
                await self._client.log_subscribe(fn)
                seen.add(fn)
                await asyncio.sleep(0.02)
        # Step 2: GROUPGET per component to guarantee an immediate state reply.
        for fn, number in self._components:
            await self._client.groupget(fn, number)
            await asyncio.sleep(0.02)
        # Give the central time to deliver all replies before entities read hub state.
        await asyncio.sleep(1.5)

    # ------------------------------------------------------------------
    # Event / disconnect callbacks (called from client)
    # ------------------------------------------------------------------

    @callback
    def _on_event(self, event: TeletaskEvent) -> None:
        key = (event.function, event.number)
        self._component_states[key] = event.state
        signal = SIGNAL_STATE_UPDATED.format(
            central_id=self.central_id,
            function=event.function,
            number=event.number,
        )
        async_dispatcher_send(self.hass, signal, event.state)

    @callback
    def _on_disconnect(self) -> None:
        """Called by the client when the TCP connection is lost."""
        _LOGGER.warning("Lost connection to Teletask central — scheduling reconnect")
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

    async def async_set_dimmer(self, number: int, brightness: int) -> None:
        # 103 = PREVIOUS_STATE (restore last brightness); all other values clamp to 0-100.
        if brightness != 103:
            brightness = max(0, min(100, brightness))
        await self._client.set_state(FunctionCode.DIMMER, number, brightness)
        # Optimistic update: if PREVIOUS_STATE (103) we don't know the actual brightness,
        # so just mark as ON without changing the brightness value.
        if brightness == 103:
            current = dict(self._component_states.get((FunctionCode.DIMMER, number), {}))
            current["state"] = "ON"
            self._optimistic_update(FunctionCode.DIMMER, number, current)
        else:
            self._optimistic_update(FunctionCode.DIMMER, number, {
                "state": "ON" if brightness > 0 else "OFF",
                "brightness": brightness,
            })

    async def async_set_motor(self, number: int, direction: str) -> None:
        # STOP=3 per Teletask protocol (SET_MTRSTOP=3, not 0)
        param = {"UP": 1, "DOWN": 2, "STOP": MOTOR_STOP}.get(direction.upper(), MOTOR_STOP)
        await self._client.set_state(FunctionCode.MOTOR, number, param)

    async def async_set_motor_position(self, number: int, position: int) -> None:
        position = max(0, min(100, position))
        # MOTOR_GO_TO_POSITION=11 with position percentage as extra byte
        await self._client.set_state(FunctionCode.MOTOR, number, MOTOR_GO_TO_POSITION, position)

    async def async_set_mood(self, function: int, number: int, state: bool) -> None:
        await self._client.set_state(function, number, 0xFF if state else 0x00)
        self._optimistic_update(function, number, {"state": "ON" if state else "OFF"})

    async def async_set_flag(self, number: int, state: bool) -> None:
        await self._client.set_state(FunctionCode.FLAG, number, 0xFF if state else 0x00)
        self._optimistic_update(FunctionCode.FLAG, number, {"state": "ON" if state else "OFF"})

    async def async_set_timedfnc(self, number: int, state: bool) -> None:
        await self._client.set_state(FunctionCode.TIMEDFNC, number, 0xFF if state else 0x00)
        self._optimistic_update(FunctionCode.TIMEDFNC, number, {"state": "ON" if state else "OFF"})

    async def async_request_state(self, function: int, number: int) -> None:
        """Send a GET to the central; the response arrives via dispatcher signal."""
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
            _LOGGER.info("Attempting reconnect to Teletask central at %s:%s…", self.host, self.port)
            self._client.clear_subscriptions()
            connected = await self._client.connect()
            if connected:
                await self._subscribe_all()
                _LOGGER.info("Reconnected to Teletask central.")
                return
