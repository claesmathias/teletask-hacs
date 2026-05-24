"""Teletask coordinator — manages the TCP connection and component registry."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .client import FunctionCode, TeletaskClient, TeletaskEvent
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
        self.config = config  # parsed config.json
        self._client = TeletaskClient(host, port, self._on_event)
        self._reconnect_task: asyncio.Task | None = None
        self._components: dict[tuple[int, int], dict] = {}  # (function, number) -> component cfg
        self._component_states: dict[tuple[int, int], dict] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> bool:
        """Parse config and connect."""
        self._parse_config()
        connected = await self._client.connect()
        if connected:
            await self._subscribe_all()
        else:
            self._schedule_reconnect()
        return True  # always return True; reconnect handles the rest

    async def async_stop(self) -> None:
        if self._reconnect_task:
            self._reconnect_task.cancel()
        await self._client.disconnect()

    # ------------------------------------------------------------------
    # Config parsing
    # ------------------------------------------------------------------

    def _parse_config(self) -> None:
        """Build internal component registry from config.json data."""
        component_types = self.config.get("componentsTypes", {})
        function_map = {
            "RELAY":      FunctionCode.RELAY,
            "DIMMER":     FunctionCode.DIMMER,
            "MOTOR":      FunctionCode.MOTOR,
            "LOCMOOD":    FunctionCode.LOCMOOD,
            "GENMOOD":    FunctionCode.GENMOOD,
            "TIMEDMOOD":  FunctionCode.TIMEDMOOD,
            "FLAG":       FunctionCode.FLAG,
            "SENSOR":     FunctionCode.SENSOR,
            "COND":       FunctionCode.COND,
            "INPUT":      FunctionCode.INPUT,
            "TIMEDFNC":   FunctionCode.TIMEDFNC,
        }
        for type_name, components in component_types.items():
            fn = function_map.get(type_name)
            if fn is None:
                continue
            for comp in components:
                number = comp["number"]
                key = (int(fn), number)
                self._components[key] = {
                    "function": int(fn),
                    "function_name": type_name,
                    "number": number,
                    "description": comp.get("description", f"{type_name} {number}"),
                    "type": comp.get("type"),
                    "ha_type": comp.get("hatype"),
                    "config": comp,
                }
                self._component_states[key] = {}

    # ------------------------------------------------------------------
    # Subscribe
    # ------------------------------------------------------------------

    async def _subscribe_all(self) -> None:
        """Subscribe to all configured components."""
        for fn, number in self._components:
            await self._client.subscribe(fn, number)
            await asyncio.sleep(0.02)  # small delay to avoid flooding

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    @callback
    def _on_event(self, event: TeletaskEvent) -> None:
        """Called (from the TCP receive loop) when the central sends an update."""
        key = (event.function, event.number)
        self._component_states[key] = event.state
        signal = SIGNAL_STATE_UPDATED.format(
            central_id=self.central_id,
            function=event.function,
            number=event.number,
        )
        async_dispatcher_send(self.hass, signal, event.state)

    # ------------------------------------------------------------------
    # Commands — called by HA entities
    # ------------------------------------------------------------------

    async def async_set_relay(self, number: int, state: bool) -> None:
        await self._client.set_state(FunctionCode.RELAY, number, 0xFF if state else 0x00)

    async def async_set_dimmer(self, number: int, brightness: int) -> None:
        """brightness 0-100."""
        await self._client.set_state(FunctionCode.DIMMER, number, max(0, min(100, brightness)))

    async def async_set_motor(self, number: int, direction: str) -> None:
        """direction: UP / DOWN / STOP."""
        param = {"UP": 1, "DOWN": 2, "STOP": 0}.get(direction.upper(), 0)
        await self._client.set_state(FunctionCode.MOTOR, number, param)

    async def async_set_motor_position(self, number: int, position: int) -> None:
        await self._client.set_state(FunctionCode.MOTOR, number, 3, position)

    async def async_set_mood(self, function: int, number: int, state: bool) -> None:
        await self._client.set_state(function, number, 0xFF if state else 0x00)

    async def async_set_flag(self, number: int, state: bool) -> None:
        await self._client.set_state(FunctionCode.FLAG, number, 0xFF if state else 0x00)

    async def async_set_timedfnc(self, number: int, state: bool) -> None:
        await self._client.set_state(FunctionCode.TIMEDFNC, number, 0xFF if state else 0x00)

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
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = self.hass.loop.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        while True:
            await asyncio.sleep(RECONNECT_INTERVAL)
            if self._client.connected:
                break
            _LOGGER.info("Attempting reconnect to Teletask central…")
            connected = await self._client.connect()
            if connected:
                await self._subscribe_all()
                _LOGGER.info("Reconnected to Teletask central.")
                break
