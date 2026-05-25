"""Teletask TCP client — speaks the binary protocol directly to the central unit."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

_LOGGER = logging.getLogger(__name__)

TELETASK_STX = 0x02


class FunctionCode(IntEnum):
    RELAY     = 1
    DIMMER    = 2
    MOTOR     = 6
    LOCMOOD   = 8
    TIMEDMOOD = 9
    GENMOOD   = 10
    FLAG      = 15
    SENSOR    = 20
    COND      = 60
    INPUT     = 62
    TIMEDFNC  = 52


CMD_SET        = 0x07
CMD_GET        = 0x06
CMD_LOG        = 0x03
CMD_GROUPGET   = 0x09  # batch state request; central replies with EVENT per output
CMD_KEEP_ALIVE = 0x0B  # must be sent immediately after TCP connect
CMD_EVENT      = 0x10  # command byte used in all frames sent BY the central
CMD_ACK        = 0x0A  # acknowledge byte sent by central after valid checksum

STATE_OFF = 0
STATE_ON  = 255

# Motor direction SET constants (per Teletask protocol docs)
MOTOR_UP             = 1
MOTOR_DOWN           = 2
MOTOR_STOP           = 3
MOTOR_GO_TO_POSITION = 11


@dataclass
class TeletaskEvent:
    function: int
    number: int
    state: dict[str, Any]


class TeletaskClient:
    """Async TCP client for the Teletask binary protocol."""

    def __init__(
        self,
        host: str,
        port: int,
        event_callback: Callable[[TeletaskEvent], None],
        disconnect_callback: Callable[[], None] | None = None,
        central_id: int = 1,
    ) -> None:
        self.host = host
        self.port = port
        self._central_id = central_id
        self._event_callback = event_callback
        self._disconnect_callback = disconnect_callback
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._keep_alive_task: asyncio.Task | None = None
        self._receive_task: asyncio.Task | None = None
        self._subscribed_components: list[tuple[int, int]] = []

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=10,
            )
            self._connected = True
            _LOGGER.info("Connected to Teletask central at %s:%s", self.host, self.port)
            # Send the mandatory handshake before the central times out and closes.
            await self._handshake()
            self._receive_task = asyncio.ensure_future(self._receive_loop())
            self._keep_alive_task = asyncio.ensure_future(self._keep_alive_loop())
            return True
        except (OSError, asyncio.TimeoutError) as exc:
            _LOGGER.error("Failed to connect to Teletask central: %s", exc)
            return False

    async def _handshake(self) -> None:
        """Send the initial KEEP_ALIVE packet required by the central."""
        _LOGGER.debug("Sending KEEP_ALIVE handshake")
        await self._send(self._build_keep_alive())

    async def disconnect(self) -> None:
        self._connected = False
        for task in (self._keep_alive_task, self._receive_task):
            if task and not task.done():
                task.cancel()
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass

    @property
    def connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def set_state(self, function: int, number: int, param1: int, param2: int | None = None) -> None:
        await self._send(self._build_set(function, number, param1, param2))

    async def get_state(self, function: int, number: int) -> None:
        await self._send(self._build_get(function, number))

    async def groupget(self, function: int, number: int) -> None:
        await self._send(self._build_groupget(function, [number]))

    async def log_subscribe(self, function: int) -> None:
        """Subscribe for push events for ALL components of a function type."""
        await self._send(self._build_log(function))

    def clear_subscriptions(self) -> None:
        self._subscribed_components.clear()

    async def subscribe(self, function: int, number: int) -> None:
        self._subscribed_components.append((function, number))

    # ------------------------------------------------------------------
    # Framing
    # ------------------------------------------------------------------

    def _build_keep_alive(self) -> bytes:
        # KEEP_ALIVE has no parameters — LENGTH=3 means just [CMD_KEEP_ALIVE].
        payload = bytes([CMD_KEEP_ALIVE])
        return self._frame(payload)

    def _build_set(self, function: int, number: int, param1: int, param2: int | None = None) -> bytes:
        payload = bytes([CMD_SET, self._central_id, function, (number >> 8) & 0xFF, number & 0xFF, param1])
        if param2 is not None:
            payload += bytes([param2])
        return self._frame(payload)

    def _build_get(self, function: int, number: int) -> bytes:
        payload = bytes([CMD_GET, self._central_id, function, (number >> 8) & 0xFF, number & 0xFF])
        return self._frame(payload)

    def _build_log(self, function: int) -> bytes:
        # LOG subscribes for ALL components of a function type: [CMD, FN, 0xFF=subscribe].
        # No component number — this matches the Teletask protocol spec.
        payload = bytes([CMD_LOG, function, 0xFF])
        return self._frame(payload)

    def _build_groupget(self, function: int, numbers: list[int]) -> bytes:
        payload = bytes([CMD_GROUPGET, self._central_id, function])
        for n in numbers:
            payload += bytes([(n >> 8) & 0xFF, n & 0xFF])
        return self._frame(payload)

    @staticmethod
    def _frame(payload: bytes) -> bytes:
        # LENGTH includes the STX and LENGTH bytes themselves but NOT the checksum.
        # So: LENGTH = len(payload) + 2 (for STX + LENGTH byte).
        length = len(payload) + 2
        msg = bytes([TELETASK_STX, length]) + payload
        checksum = sum(msg) & 0xFF
        return msg + bytes([checksum])

    async def _send(self, data: bytes) -> None:
        if not self._connected or self._writer is None:
            _LOGGER.warning("Cannot send: not connected")
            return
        _LOGGER.debug("TX: %s", data.hex(" "))
        try:
            self._writer.write(data)
            await self._writer.drain()
        except (OSError, ConnectionResetError) as exc:
            _LOGGER.error("Send failed: %s", exc)
            self._handle_disconnect()

    # ------------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        buffer = bytearray()
        while self._connected and self._reader:
            try:
                data = await asyncio.wait_for(self._reader.read(256), timeout=60)
                if not data:
                    _LOGGER.warning("Teletask central closed the connection")
                    break
                _LOGGER.debug("RX: %s", data.hex(" "))
                buffer.extend(data)
                while buffer:
                    # Single ACK byte from central — acknowledges a valid frame was received.
                    if buffer[0] == CMD_ACK:
                        _LOGGER.debug("RX: ACK (0x0A)")
                        buffer = buffer[1:]
                        continue
                    event, consumed = self._parse_frame(buffer)
                    if consumed == 0:
                        break
                    buffer = buffer[consumed:]
                    if event is not None:
                        try:
                            self._event_callback(event)
                        except Exception as exc:
                            _LOGGER.exception("Event callback error: %s", exc)
            except asyncio.TimeoutError:
                continue
            except (OSError, ConnectionResetError) as exc:
                _LOGGER.error("Connection lost: %s", exc)
                break
            except asyncio.CancelledError:
                return
        self._handle_disconnect()

    def _handle_disconnect(self) -> None:
        """Mark disconnected and notify hub so it can schedule a reconnect."""
        if not self._connected:
            return  # already handled
        self._connected = False
        if self._disconnect_callback:
            self._disconnect_callback()

    def _parse_frame(self, buf: bytearray) -> tuple[TeletaskEvent | None, int]:
        if len(buf) < 2:
            return None, 0
        if buf[0] != TELETASK_STX:
            try:
                idx = buf.index(TELETASK_STX, 1)
                return None, idx
            except ValueError:
                return None, len(buf)

        length = buf[1]
        # LENGTH already counts STX + LENGTH byte; total frame = LENGTH + 1 (just the CS byte).
        total = length + 1
        if len(buf) < total:
            return None, 0

        frame = buf[:total]
        expected_cs = sum(frame[:-1]) & 0xFF
        if frame[-1] != expected_cs:
            _LOGGER.debug("Checksum mismatch, skipping byte")
            return None, 1

        event = self._decode_frame(frame)
        return event, total

    def _decode_frame(self, frame: bytes) -> TeletaskEvent | None:
        if len(frame) < 8:
            return None
        command = frame[2]

        if command == CMD_EVENT:
            # [STX, LEN, 0x10, CID, FN, NUM_HI, NUM_LO, ERROR, STATE..., CS]
            if len(frame) < 10:
                return None
            function = frame[4]
            number   = (frame[5] << 8) | frame[6]
            # State bytes start at index 8 (after ERROR byte at [7]).
            state_bytes = bytes(frame[8:-1])
        elif command == CMD_GET:
            # PICOS LOG push: [STX, LEN, 0x06, FN, NUM_HI, NUM_LO, STATE..., CS]
            # (PICOS omits the CID byte that MICROS+ includes)
            if len(frame) < 8:
                return None
            function = frame[3]
            number   = (frame[4] << 8) | frame[5]
            state_bytes = bytes(frame[6:-1])
        else:
            return None

        state = self._decode_state(function, state_bytes)
        if state is None:
            return None
        return TeletaskEvent(function=function, number=number, state=state)

    @staticmethod
    def _decode_state(function: int, state_bytes: bytes) -> dict[str, Any] | None:
        if not state_bytes:
            return None
        param1 = state_bytes[0]
        param2 = state_bytes[1] if len(state_bytes) > 1 else 0

        if function == FunctionCode.RELAY:
            return {"state": "ON" if param1 == STATE_ON else "OFF"}
        if function == FunctionCode.DIMMER:
            # Some firmware versions send 0xFF (relay-style "full on") instead of 100.
            brightness = 100 if param1 == 0xFF else min(param1, 100)
            return {"state": "ON" if param1 > 0 else "OFF", "brightness": brightness}
        if function == FunctionCode.MOTOR:
            # state_bytes: [direction, power, protection, requested_pos, current_pos, ...]
            direction_map = {1: "UP", 2: "DOWN", 3: "STOP", 6: "START_STOP", 7: "UP_STOP", 8: "DOWN_STOP"}
            direction = direction_map.get(param1, "STOP")
            # param2 is the power byte (0=OFF, 255=ON); position is at byte[4]
            is_on = param2 == STATE_ON if len(state_bytes) > 1 else param1 in (1, 2)
            result: dict[str, Any] = {
                "state": "ON" if is_on else "OFF",
                "last_direction": direction,
            }
            if len(state_bytes) > 4:
                result["current_position"] = state_bytes[4]
            return result
        if function in (FunctionCode.LOCMOOD, FunctionCode.GENMOOD, FunctionCode.TIMEDMOOD):
            return {"state": "ON" if param1 == STATE_ON else "OFF"}
        if function == FunctionCode.FLAG:
            return {"state": "ON" if param1 == STATE_ON else "OFF"}
        if function == FunctionCode.COND:
            return {"state": "ON" if param1 == STATE_ON else "OFF"}
        if function == FunctionCode.INPUT:
            # Values per protocol: 1=short press, 2=closed, 3=open
            input_map = {1: "SHORT_PRESS", 2: "CLOSED", 3: "OPEN"}
            return {"state": input_map.get(param1, "OPEN")}
        if function == FunctionCode.TIMEDFNC:
            return {"state": "ON" if param1 == STATE_ON else "OFF"}
        if function == FunctionCode.SENSOR:
            # Temperature: 2-byte big-endian in tenths of Kelvin → Celsius.
            raw = ((param1 << 8) | param2) / 10.0 - 273.0
            return {"state": raw, "value": raw}
        return None

    # ------------------------------------------------------------------
    # Keep-alive
    # ------------------------------------------------------------------

    async def _keep_alive_loop(self) -> None:
        """Send a KEEP_ALIVE every 60s to prevent the central from timing out."""
        while self._connected:
            await asyncio.sleep(60)
            if self._connected:
                await self._send(self._build_keep_alive())
