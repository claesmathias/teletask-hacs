"""Teletask TCP client — speaks the binary protocol directly to the central unit."""
from __future__ import annotations

import asyncio
import logging
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Teletask binary protocol constants
# ---------------------------------------------------------------------------

TELETASK_STX = 0x02  # start-of-text byte every message begins with

# Function codes used in the protocol
class FunctionCode(IntEnum):
    RELAY       = 1
    DIMMER      = 2
    MOTOR       = 6
    LOCMOOD     = 8
    TIMEDMOOD   = 9
    GENMOOD     = 10
    FLAG        = 15
    SENSOR      = 20
    COND        = 60
    INPUT       = 62  # read-only digital input
    TIMEDFNC    = 52

# Command bytes
CMD_SET     = 0x07
CMD_GET     = 0x06
CMD_LOG     = 0x03  # subscribe / ask for push updates

# State values
STATE_OFF = 0
STATE_ON  = 255


@dataclass
class TeletaskEvent:
    """A state-change event received from the central unit."""
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
    ) -> None:
        self.host = host
        self.port = port
        self._event_callback = event_callback
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._keep_alive_task: asyncio.Task | None = None
        self._receive_task: asyncio.Task | None = None
        self._subscribed_components: list[tuple[int, int]] = []  # (function, number)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Open TCP connection to the central unit."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=10,
            )
            self._connected = True
            _LOGGER.info("Connected to Teletask central at %s:%s", self.host, self.port)
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._keep_alive_task = asyncio.create_task(self._keep_alive_loop())
            return True
        except (OSError, asyncio.TimeoutError) as exc:
            _LOGGER.error("Failed to connect to Teletask central: %s", exc)
            return False

    async def disconnect(self) -> None:
        """Close the TCP connection."""
        self._connected = False
        if self._keep_alive_task:
            self._keep_alive_task.cancel()
        if self._receive_task:
            self._receive_task.cancel()
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
    # Sending commands
    # ------------------------------------------------------------------

    async def set_state(self, function: int, number: int, param1: int, param2: int = 0) -> None:
        """Send a SET command to the central unit."""
        await self._send(self._build_set(function, number, param1, param2))

    async def get_state(self, function: int, number: int) -> None:
        """Send a GET command to request current state."""
        await self._send(self._build_get(function, number))

    async def subscribe(self, function: int, number: int) -> None:
        """Ask central unit to push updates for this component."""
        self._subscribed_components.append((function, number))
        await self._send(self._build_log(function, number))

    async def resubscribe_all(self) -> None:
        """Re-subscribe after reconnect."""
        for function, number in self._subscribed_components:
            await self._send(self._build_log(function, number))
            await asyncio.sleep(0.05)

    # ------------------------------------------------------------------
    # Protocol framing
    # ------------------------------------------------------------------

    def _build_set(self, function: int, number: int, param1: int, param2: int) -> bytes:
        """
        SET command frame:
        STX | length | CMD_SET | function | number_hi | number_lo | param1 | param2 | checksum
        """
        payload = bytes([CMD_SET, function, (number >> 8) & 0xFF, number & 0xFF, param1, param2])
        return self._frame(payload)

    def _build_get(self, function: int, number: int) -> bytes:
        """GET command frame."""
        payload = bytes([CMD_GET, function, (number >> 8) & 0xFF, number & 0xFF, 0, 0])
        return self._frame(payload)

    def _build_log(self, function: int, number: int) -> bytes:
        """LOG/subscribe command frame."""
        payload = bytes([CMD_LOG, function, (number >> 8) & 0xFF, number & 0xFF, 0, 0])
        return self._frame(payload)

    @staticmethod
    def _frame(payload: bytes) -> bytes:
        """Wrap payload: STX + length + payload + checksum."""
        length = len(payload) + 3  # STX + length byte + payload + checksum
        msg = bytes([TELETASK_STX, length]) + payload
        checksum = sum(msg) & 0xFF
        return msg + bytes([checksum])

    async def _send(self, data: bytes) -> None:
        if not self._connected or self._writer is None:
            _LOGGER.warning("Cannot send: not connected")
            return
        try:
            self._writer.write(data)
            await self._writer.drain()
        except (OSError, ConnectionResetError) as exc:
            _LOGGER.error("Send failed: %s", exc)
            self._connected = False

    # ------------------------------------------------------------------
    # Receiving & parsing
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        """Continuously read frames from the central unit."""
        buffer = bytearray()
        while self._connected and self._reader:
            try:
                data = await asyncio.wait_for(self._reader.read(256), timeout=60)
                if not data:
                    break
                buffer.extend(data)
                while True:
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
                continue  # timeout is fine, keep looping
            except (OSError, ConnectionResetError) as exc:
                _LOGGER.error("Connection lost: %s", exc)
                break
        self._connected = False

    def _parse_frame(self, buf: bytearray) -> tuple[TeletaskEvent | None, int]:
        """
        Try to parse one frame from the buffer.
        Returns (event_or_None, bytes_consumed).
        Returns (None, 0) if not enough data yet.
        """
        if len(buf) < 2:
            return None, 0
        if buf[0] != TELETASK_STX:
            # Scan forward to find STX
            try:
                idx = buf.index(TELETASK_STX, 1)
                return None, idx
            except ValueError:
                return None, len(buf)

        length = buf[1]
        if len(buf) < length:
            return None, 0  # wait for more data

        frame = buf[:length]
        # Validate checksum (last byte = sum of all preceding bytes & 0xFF)
        expected_cs = sum(frame[:-1]) & 0xFF
        if frame[-1] != expected_cs:
            _LOGGER.debug("Checksum mismatch, skipping byte")
            return None, 1

        event = self._decode_frame(frame)
        return event, length

    def _decode_frame(self, frame: bytes) -> TeletaskEvent | None:
        """Decode a validated frame into a TeletaskEvent."""
        if len(frame) < 8:
            return None
        # frame: STX | length | command | function | number_hi | number_lo | param1 | param2 | ... | cs
        command  = frame[2]
        function = frame[3]
        number   = (frame[4] << 8) | frame[5]
        param1   = frame[6]
        param2   = frame[7] if len(frame) > 8 else 0

        if command not in (CMD_SET, CMD_GET, CMD_LOG):
            return None

        state = self._decode_state(function, param1, param2, frame)
        if state is None:
            return None
        return TeletaskEvent(function=function, number=number, state=state)

    @staticmethod
    def _decode_state(function: int, param1: int, param2: int, frame: bytes) -> dict[str, Any] | None:
        """Convert raw param bytes to a meaningful state dict."""
        if function == FunctionCode.RELAY:
            return {"state": "ON" if param1 == STATE_ON else "OFF"}

        if function == FunctionCode.DIMMER:
            brightness = param1  # 0-100
            return {
                "state": "ON" if brightness > 0 else "OFF",
                "brightness": brightness,
            }

        if function == FunctionCode.MOTOR:
            direction_map = {0: "STOP", 1: "UP", 2: "DOWN"}
            return {
                "state": "ON" if param1 in (1, 2) else "OFF",
                "last_direction": direction_map.get(param1, "STOP"),
                "current_position": param2,
            }

        if function in (FunctionCode.LOCMOOD, FunctionCode.GENMOOD, FunctionCode.TIMEDMOOD):
            return {"state": "ON" if param1 == STATE_ON else "OFF"}

        if function == FunctionCode.FLAG:
            return {"state": "ON" if param1 == STATE_ON else "OFF"}

        if function == FunctionCode.COND:
            return {"state": "ON" if param1 == STATE_ON else "OFF"}

        if function == FunctionCode.INPUT:
            return {"state": "CLOSED" if param1 == STATE_ON else "OPEN"}

        if function == FunctionCode.TIMEDFNC:
            return {"state": "ON" if param1 == STATE_ON else "OFF"}

        if function == FunctionCode.SENSOR:
            # Sensor: param1 = integer part, param2 = decimal part (optional)
            raw = param1 + param2 / 10.0 if param2 else float(param1)
            return {"state": raw, "value": raw}

        return None

    # ------------------------------------------------------------------
    # Keep-alive
    # ------------------------------------------------------------------

    async def _keep_alive_loop(self) -> None:
        """Send a keep-alive GET every 30 s to prevent central from closing idle connections."""
        while self._connected:
            await asyncio.sleep(30)
            if self._subscribed_components:
                fn, num = self._subscribed_components[0]
                await self.get_state(fn, num)
