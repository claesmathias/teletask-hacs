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
    """Function ("device type") codes.

    Sources: TDS LIBRARY V3.4/V3.7 (FNC_* constants) and TDS15132 DoIP API
    (2026). Where they differ, the library wins: PICOS/MICROS+ centrals speak
    the library protocol (e.g. 2-byte sensor values).
    """

    RELAY          = 1
    DIMMER         = 2
    PROCES         = 3    # process function
    TIMEDFNC       = 5    # DoIP spec "TIMEDFUNCTION"
    MOTOR          = 6
    LOCMOOD        = 8
    TIMEDMOOD      = 9
    GENMOOD        = 10
    DIMMERGRP      = 13   # DoIP only
    FLAG           = 15
    SENSOR         = 20   # sensor zone; also the climate zone in the library protocol
    DIGITALINPUT   = 28   # DoIP only: wired digital input, HIGH/LOW
    AUDIO          = 31
    MOTORGRP       = 40   # DoIP only
    RGBGRP         = 41   # DoIP only
    TWGRP          = 42   # DoIP only
    INPUT          = 52   # library FNC_TPKEY: interface push buttons
    SERVICE        = 53
    DISPLAYMESSAGE = 54   # library FNC_MESSAGE; written with CMD_DISPLAY_MESSAGE
    ALARM          = 59   # DoIP only
    COND           = 60
    ACCESS         = 202  # DoIP only: badge reader reports (subscribe to number 1)
    RGB            = 217  # DoIP only
    TW             = 220  # DoIP only: tunable white


# config.json component type → function code.
TYPE_FUNCTIONS: dict[str, FunctionCode] = {
    "RELAY": FunctionCode.RELAY,
    "DIMMER": FunctionCode.DIMMER,
    "DIMMERGRP": FunctionCode.DIMMERGRP,
    "MOTOR": FunctionCode.MOTOR,
    "MOTORGRP": FunctionCode.MOTORGRP,
    "LOCMOOD": FunctionCode.LOCMOOD,
    "GENMOOD": FunctionCode.GENMOOD,
    "TIMEDMOOD": FunctionCode.TIMEDMOOD,
    "FLAG": FunctionCode.FLAG,
    "SENSOR": FunctionCode.SENSOR,
    "COND": FunctionCode.COND,
    "INPUT": FunctionCode.INPUT,
    "DIGITALINPUT": FunctionCode.DIGITALINPUT,
    "TIMEDFNC": FunctionCode.TIMEDFNC,
    "PROCES": FunctionCode.PROCES,
    "SERVICE": FunctionCode.SERVICE,
    "AUDIO": FunctionCode.AUDIO,
    "RGB": FunctionCode.RGB,
    "RGBGRP": FunctionCode.RGBGRP,
    "TW": FunctionCode.TW,
    "TWGRP": FunctionCode.TWGRP,
    "ALARM": FunctionCode.ALARM,
    "DISPLAYMESSAGE": FunctionCode.DISPLAYMESSAGE,
    "ACCESS": FunctionCode.ACCESS,
}

# Functions the central can't be asked about (no LOG / GET).
WRITE_ONLY_FUNCTIONS = frozenset({FunctionCode.DISPLAYMESSAGE})
# Functions that only report through their own subscription, never on GET.
REPORT_ONLY_FUNCTIONS = frozenset({FunctionCode.ACCESS})

# Function codes whose state is one ON/OFF byte.
ON_OFF_FUNCTIONS = frozenset({
    FunctionCode.RELAY, FunctionCode.PROCES, FunctionCode.TIMEDFNC,
    FunctionCode.LOCMOOD, FunctionCode.TIMEDMOOD, FunctionCode.GENMOOD,
    FunctionCode.FLAG, FunctionCode.COND, FunctionCode.SERVICE,
    FunctionCode.DIGITALINPUT,
})


CMD_LOG             = 0x03
CMD_DISPLAY_MESSAGE = 0x04
CMD_GET             = 0x06
CMD_SET             = 0x07
CMD_GROUPGET        = 0x09  # batch state request; central replies with EVENT per output
CMD_ACK             = 0x0A  # acknowledge byte sent by central after valid checksum
CMD_KEEP_ALIVE      = 0x0B  # must be sent immediately after TCP connect
CMD_EVENT           = 0x10  # command byte used in all frames sent BY the central
CMD_ACCESS_REPORT   = 0x14  # DoIP: badge access attempt
CMD_SUBSCRIBE       = 0x22  # DoIP: per-device subscription

STATE_OFF    = 0
STATE_ON     = 255
STATE_TOGGLE = 103

# Motor SET settings (library V3.7, DoIP)
MOTOR_UP             = 1
MOTOR_DOWN           = 2
MOTOR_STOP           = 3
MOTOR_GO_TO_POSITION = 11
MOTOR_SLAT_POSITION  = 12  # DoIP only
MOTOR_SUN_PROTECTION = 15

# Climate (sensor zone) SET settings (library V3.7)
TEMP_UP            = 21
TEMP_DOWN          = 22
TEMP_FROST         = 24
TEMP_NIGHT         = 25
TEMP_DAY           = 26
TEMP_SET_NIGHT     = 27
TEMP_SET_DAY       = 29
TEMP_SET_NIGHTCOOL = 56
TEMP_MANUAL_TARGET = 87
TEMP_SET_STANDBY   = 88
TEMP_STANDBY       = 93
TEMP_ONOFF         = 104

CLIMATE_PRESETS = {TEMP_DAY: "day", TEMP_NIGHT: "night", TEMP_STANDBY: "standby", TEMP_FROST: "frost"}
CLIMATE_MODES = {94: "auto", 95: "heat", 96: "cool", 105: "vent", 106: "stop", 107: "heat_plus", 108: "dry"}
CLIMATE_FAN_SPEEDS = {97: "low", 98: "medium", 99: "high", 89: "auto"}

# Audio SET settings (library V3.7 / DoIP)
AUDIO_VOLUME_UP   = 32
AUDIO_VOLUME_DOWN = 33
AUDIO_ON          = 36
AUDIO_OFF         = 37
AUDIO_MUTE        = 77
AUDIO_PRESET_NEXT = 88  # DoIP only
AUDIO_PRESET_PREV = 89  # DoIP only
# Source N (1-based) → setting; the same byte is reported as the zone's state.
AUDIO_SOURCES = {1: 38, 2: 39, 3: 40, 4: 41, 5: 42, 6: 71, 7: 72, 8: 73}

RGB_COLOR = 231  # DoIP: + R, G, B
TW_COLOR  = 230  # DoIP: + Kelvin (2 bytes) + brightness; 0xFEFE / 0xFE = unchanged
TW_UNCHANGED_KELVIN = 0xFEFE
TW_UNCHANGED_BRIGHTNESS = 0xFE

SENS_MAX = 0x3F00  # sensor values at or above this mean "sensor error"

DISPLAY_ASCII_LINE = 16    # characters per line with ascii
DISPLAY_UNICODE_LINE = 8   # characters per line without (UTF-16)
DISPLAY_LINE_BYTES = 16
_DISPLAY_BREAK_AFTER = "-–—/"  # hyphen, en dash, em dash, slash

# Motor sun (high nibble) / wind (low nibble) protection state.
_PROTECTION = {
    0: "not_defined",
    1: "on_controlling",
    2: "on_not_controlling",
    3: "on_overruled",
    4: "off",
}


@dataclass
class TeletaskEvent:
    function: int
    number: int
    state: dict[str, Any]
    raw: bytes = b""  # state bytes as received, for type-dependent decoding (sensors)


# ----------------------------------------------------------------------
# Value conversions (TDS LIBRARY V3.7 §6.8)
# ----------------------------------------------------------------------


def _short(data: bytes, offset: int) -> int | None:
    if len(data) < offset + 2:
        return None
    return (data[offset] << 8) | data[offset + 1]


def short_to_celsius(value: int | None) -> float | None:
    """Report value (tenths of Kelvin) → °C; None for a sensor error."""
    if value is None or value >= SENS_MAX:
        return None
    return round(value / 10.0 - 273.0, 1)


def celsius_to_short(celsius: float) -> int:
    return max(0, min(0xFFFF, round((celsius + 273.0) * 10)))


def celsius_to_preset_byte(celsius: float) -> int:
    """Day/night preset SET value: (°C + 40) × 2, 0.5 °C steps."""
    return max(0, min(255, round((celsius + 40.0) * 2)))


def short_to_lux(value: int) -> int:
    return max(0, round(10 ** (value / 40.0) - 1))


# Raw ranges of the analog inputs: (raw offset, raw span).
_ANALOG_RANGES = {
    "4-20ma": (180, 720),
    "0-20ma": (0, 900),
    "0-10v": (0, 1023),
    "5-10v": (0, 1023),
}


def decode_sensor(sensor_type: str, data: bytes, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Decode a SENSOR report according to the sensor type in config.json.

    The central reports every sensor zone in the same layout; only the
    conversion of the 2-byte values depends on the kind of sensor.
    """
    config = config or {}
    sensor_type = (sensor_type or "TEMPERATURE").upper()
    raw = _short(data, 0)
    if raw is None:
        return None
    error = raw >= SENS_MAX
    result: dict[str, Any]

    if sensor_type in ("TEMPERATURE", "TEMPERATURECONTROL"):
        value = short_to_celsius(raw)
        result = {"state": value, "value": value}
        if sensor_type == "TEMPERATURECONTROL":
            result.update(decode_climate(data))
        return result
    if sensor_type == "HUMIDITY":
        value = None if error else raw
    elif sensor_type == "LIGHT":
        value = None if error else short_to_lux(raw)
    elif sensor_type == "GAS":
        value = None if error else _analog_value(raw, config)
    elif sensor_type == "PULSECOUNTER":
        value = None if error else raw
        result = {"state": value, "value": value}
        if len(data) >= 20:
            total = int.from_bytes(data[16:20], "big")
            ppu = _number(config.get("pulses_per_unit")) or 1
            result["total"] = round(total / ppu, 3)
        return result
    else:
        value = None if error else raw
    return {"state": value, "value": value}


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _analog_value(raw: int, config: dict[str, Any]) -> float:
    lo, hi = _number(config.get("gas_min")), _number(config.get("gas_max"))
    kind = str(config.get("gas_type", "")).lower()
    if lo is None or hi is None or kind not in _ANALOG_RANGES:
        return raw
    offset, span = _ANALOG_RANGES[kind]
    return round((hi - lo) / span * (raw - offset) + lo, 2)


def decode_climate(data: bytes) -> dict[str, Any]:
    """Decode the climate part of a sensor-zone report (library V3.7 §3.9).

    [0-1] value  [2-3] target  [4-5] day  [6-7] night  [8] standby offset
    [9] active preset  [10] mode  [11] fan speed  [12] power  [13] frost
    protection / window (DoIP)  [14] heating/cooling (DoIP)  [15] direction
    [16-17] night preset when cooling
    """
    result: dict[str, Any] = {
        "current_temperature": short_to_celsius(_short(data, 0)),
        "target_temperature": short_to_celsius(_short(data, 2)),
        "day_preset": short_to_celsius(_short(data, 4)),
        "night_preset": short_to_celsius(_short(data, 6)),
    }
    if len(data) > 8:
        result["standby_offset"] = data[8] / 10.0
    if len(data) > 12:
        result["preset"] = CLIMATE_PRESETS.get(data[9])
        result["mode"] = CLIMATE_MODES.get(data[10])
        result["fan_speed"] = CLIMATE_FAN_SPEEDS.get(data[11])
        result["power"] = "ON" if data[12] == STATE_ON else "OFF"
    if len(data) > 15:
        result["frost_or_window"] = data[13]
        result["output"] = data[14]  # DoIP: 128 = cooling, 8 = heating
        result["direction"] = data[15]
    if len(data) > 17:
        result["night_cool_preset"] = short_to_celsius(_short(data, 16))
    return result


def _text_fields(data: bytes, offset: int, count: int) -> list[str]:
    """Read ``count`` length-prefixed UTF-8 strings starting at ``offset``."""
    texts: list[str] = []
    for _ in range(count):
        if offset >= len(data):
            break
        length = data[offset]
        texts.append(data[offset + 1:offset + 1 + length].decode("utf-8", "replace"))
        offset += 1 + length
    return texts


# ----------------------------------------------------------------------
# Display messages (TDS LIBRARY V3.7 §3.6 / §6.6)
# ----------------------------------------------------------------------


def _number_list(value: Any) -> list[int]:
    if value is None or value == "":
        return []
    if isinstance(value, int) and not isinstance(value, bool):
        return [value]
    if isinstance(value, str):
        value = value.split(",")
    return [int(str(v).strip()) for v in value]


def display_targets(config: dict[str, Any]) -> tuple[list[int], list[int]]:
    """Bus and interface address lists of a DISPLAYMESSAGE component.

    ``bus_numbers``/``address_numbers`` are comma-separated strings or lists. Left out, the message goes to every display (0, 0).
    """
    buses = _number_list(config.get("bus_numbers"))
    addresses = _number_list(config.get("address_numbers"))
    if not buses and not addresses:
        return [0], [0]
    if len(buses) != len(addresses):
        raise ValueError("bus_numbers and address_numbers must list the same number of entries")
    return buses, addresses


def display_line_length(ascii_mode: bool) -> int:
    return DISPLAY_ASCII_LINE if ascii_mode else DISPLAY_UNICODE_LINE


def wrap_display_text(text: str, length: int) -> tuple[str, str]:
    """Spread one text over the two display lines.

    Line 1 ends at the last space (dropped), or after a hyphen, dash or slash
    (kept), that still fits; a word longer than a line is split.
    """
    text = " ".join(text.split())
    if len(text) <= length:
        return text, ""
    end = length
    while end > 0 and text[end] != " " and text[end - 1] not in _DISPLAY_BREAK_AFTER:
        end -= 1
    if end == 0:
        end = length
    return text[:end].rstrip(), text[end:].strip()


def _display_line_bytes(text: str, ascii_mode: bool) -> bytes:
    if ascii_mode:
        encoded = text.encode("ascii", "replace")[:DISPLAY_LINE_BYTES]
        return encoded.ljust(DISPLAY_LINE_BYTES, b" ")
    encoded = b""
    for char in text:
        unit = char.encode("utf-16-be")
        if len(encoded) + len(unit) > DISPLAY_LINE_BYTES:
            break
        encoded += unit
    while len(encoded) < DISPLAY_LINE_BYTES:
        encoded += " ".encode("utf-16-be")
    return encoded


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
        self.last_error: str | None = None  # reason of the last failed connect()

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
            self.last_error = None
            return True
        except (OSError, asyncio.TimeoutError) as exc:
            # The hub decides what to log: it reports the first failure of an
            # outage, not every 30-second retry.
            self.last_error = str(exc) or type(exc).__name__
            _LOGGER.debug("Failed to connect to Teletask central: %s", self.last_error)
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

    async def set_state(self, function: int, number: int, param1: int, *data: int | None) -> None:
        await self._send(self._build_set(function, number, param1, *data))

    async def display_message(
        self,
        buses: list[int],
        addresses: list[int],
        line1: str,
        line2: str,
        *,
        is_message: bool,
        ascii_mode: bool,
        beeps: int,
    ) -> None:
        await self._send(self._build_display_message(
            buses, addresses, line1, line2,
            is_message=is_message, ascii_mode=ascii_mode, beeps=beeps,
        ))

    async def subscribe_device(self, function: int, number: int) -> None:
        """DoIP per-device subscription (0x22); needed for badge access reports."""
        await self._send(self._frame(bytes([
            CMD_SUBSCRIBE, self._central_id, function,
            (number >> 8) & 0xFF, number & 0xFF, STATE_ON,
        ])))

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

    def _build_set(self, function: int, number: int, param1: int, *data: int | None) -> bytes:
        payload = bytes([CMD_SET, self._central_id, function, (number >> 8) & 0xFF, number & 0xFF, param1])
        payload += bytes(d & 0xFF for d in data if d is not None)
        return self._frame(payload)

    def _build_display_message(
        self,
        buses: list[int],
        addresses: list[int],
        line1: str,
        line2: str,
        *,
        is_message: bool,
        ascii_mode: bool,
        beeps: int,
    ) -> bytes:
        # [0x04, CEN, bus..., address..., message, ascii, line1 (16), line2 (16), beeps]
        if len(buses) != len(addresses) or not buses:
            raise ValueError("bus and address lists must have the same, non-zero length")
        payload = bytes([CMD_DISPLAY_MESSAGE, self._central_id])
        payload += bytes(b & 0xFF for b in buses) + bytes(a & 0xFF for a in addresses)
        payload += bytes([1 if is_message else 0, 1 if ascii_mode else 0])
        payload += _display_line_bytes(line1, ascii_mode) + _display_line_bytes(line2, ascii_mode)
        payload += bytes([max(0, min(255, beeps))])
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

    # ------------------------------------------------------------------
    # Human-readable log helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cmd_name(cmd: int) -> str:
        return {
            CMD_SET: "SET", CMD_GET: "GET", CMD_LOG: "LOG",
            CMD_GROUPGET: "GROUPGET", CMD_KEEP_ALIVE: "KEEP_ALIVE",
            CMD_EVENT: "EVENT", CMD_ACK: "ACK",
            CMD_DISPLAY_MESSAGE: "DISPLAYMSG", CMD_SUBSCRIBE: "SUBSCRIBE",
            CMD_ACCESS_REPORT: "ACCESS",
        }.get(cmd, f"0x{cmd:02X}")

    @staticmethod
    def _fn_name(fn: int) -> str:
        try:
            return FunctionCode(fn).name
        except ValueError:
            return f"fn={fn}"

    def _describe_tx(self, data: bytes) -> str:
        if len(data) < 3:
            return data.hex(" ")
        cmd = data[2]
        name = self._cmd_name(cmd)
        if cmd == CMD_KEEP_ALIVE:
            return f"{name}"
        if cmd in (CMD_SET, CMD_GET, CMD_GROUPGET) and len(data) >= 8:
            fn  = data[4]
            num = (data[5] << 8) | data[6]
            extra = f" state=0x{data[7]:02X}" if cmd == CMD_SET and len(data) >= 9 else ""
            return f"{name} {self._fn_name(fn)}/{num}{extra}"
        if cmd == CMD_LOG and len(data) >= 5:
            fn = data[3]
            return f"{name} {self._fn_name(fn)}"
        return f"{name} {data.hex(' ')}"

    async def _send(self, data: bytes) -> None:
        if not self._connected or self._writer is None:
            _LOGGER.warning("Cannot send: not connected")
            return
        _LOGGER.debug("TX %-10s  raw: %s", self._describe_tx(data), data.hex(" "))
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
                _LOGGER.debug("RX raw (%d bytes): %s", len(data), data.hex(" "))
                buffer.extend(data)
                while buffer:
                    if buffer[0] == CMD_ACK:
                        _LOGGER.debug("RX ACK")
                        buffer = buffer[1:]
                        continue
                    event, consumed = self._parse_frame(buffer)
                    if consumed == 0:
                        break
                    buffer = buffer[consumed:]
                    if event is not None:
                        _LOGGER.debug(
                            "RX EVENT  %-8s #%-3d  state=%s",
                            self._fn_name(event.function),
                            event.number,
                            event.state,
                        )
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
                _LOGGER.debug("Skipping %d non-STX bytes in buffer", idx)
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
            _LOGGER.warning(
                "Checksum mismatch in frame %s (expected 0x%02X got 0x%02X), skipping byte",
                frame.hex(" "), expected_cs, frame[-1],
            )
            return None, 1

        event = self._decode_frame(frame)
        if event is None and len(frame) >= 3:
            _LOGGER.debug("Ignored frame cmd=0x%02X (%s): %s",
                          frame[2], self._cmd_name(frame[2]), frame.hex(" "))
        return event, total

    def _decode_frame(self, frame: bytes) -> TeletaskEvent | None:
        if len(frame) < 4:
            return None
        command = frame[2]

        if command == CMD_ACCESS_REPORT:
            state = self._decode_access(bytes(frame[3:-1]))
            if state is None:
                return None
            return TeletaskEvent(function=FunctionCode.ACCESS, number=1, state=state)

        if len(frame) < 8:
            return None
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
            function = frame[3]
            number   = (frame[4] << 8) | frame[5]
            state_bytes = bytes(frame[6:-1])
        else:
            return None

        state = self._decode_state(function, state_bytes)
        if state is None:
            return None
        return TeletaskEvent(function=function, number=number, state=state, raw=state_bytes)

    @staticmethod
    def _decode_access(data: bytes) -> dict[str, Any] | None:
        # [result, card id (4), unix timestamp (6), len, user, len, reader]
        if len(data) < 12:
            return None
        texts = _text_fields(data, 11, 2)
        return {
            "state": "ALLOWED" if data[0] == STATE_ON else "DENIED",
            "card_id": int.from_bytes(data[1:5], "big"),
            "timestamp": int.from_bytes(data[5:11], "big"),
            "user": texts[0] if texts else "",
            "reader": texts[1] if len(texts) > 1 else "",
        }

    @staticmethod
    def _decode_state(function: int, state_bytes: bytes) -> dict[str, Any] | None:
        if not state_bytes:
            return None
        param1 = state_bytes[0]
        param2 = state_bytes[1] if len(state_bytes) > 1 else 0

        if function in ON_OFF_FUNCTIONS:
            return {"state": "ON" if param1 == STATE_ON else "OFF"}
        if function in (FunctionCode.DIMMER, FunctionCode.DIMMERGRP):
            # Some firmware versions send 0xFF (relay-style "full on") instead of 100.
            # While dimming, 3 more bytes follow (start level, time); byte 0 is the target.
            brightness = 100 if param1 == 0xFF else min(param1, 100)
            return {"state": "ON" if param1 > 0 else "OFF", "brightness": brightness}
        if function in (FunctionCode.MOTOR, FunctionCode.MOTORGRP):
            # [direction, power, protection, requested_pos, current_pos,
            #  time to finish (2, 1/100 s), correction 0 %, correction 100 %]
            direction_map = {1: "UP", 2: "DOWN", 3: "STOP", 6: "START_STOP", 7: "UP_STOP", 8: "DOWN_STOP"}
            direction = direction_map.get(param1, "STOP")
            is_on = param2 == STATE_ON if len(state_bytes) > 1 else param1 in (1, 2)
            result: dict[str, Any] = {
                "state": "ON" if is_on else "OFF",
                "last_direction": direction,
            }
            if len(state_bytes) > 2:
                protection = state_bytes[2]
                result["sun_protection"] = _PROTECTION.get(protection >> 4, "not_defined")
                result["wind_protection"] = _PROTECTION.get(protection & 0x0F, "not_defined")
            if len(state_bytes) > 3:
                result["requested_position"] = state_bytes[3]
            if len(state_bytes) > 4:
                result["current_position"] = state_bytes[4]
            if len(state_bytes) > 6:
                result["seconds_to_finish"] = _short(state_bytes, 5) / 100.0
            return result
        if function == FunctionCode.INPUT:
            # FNC_TPKEY: 1 = short press, 2 = long press (closed), 3 = end of long press
            input_map = {1: "SHORT_PRESS", 2: "CLOSED", 3: "OPEN"}
            return {"state": input_map.get(param1, "OPEN")}
        if function == FunctionCode.SENSOR:
            # Default decoding (temperature); the hub re-decodes per sensor type.
            return decode_sensor("TEMPERATURE", state_bytes)
        if function == FunctionCode.AUDIO:
            return TeletaskClient._decode_audio(state_bytes)
        if function in (FunctionCode.RGB, FunctionCode.RGBGRP):
            if len(state_bytes) < 3:
                return None
            r, g, b = state_bytes[0], state_bytes[1], state_bytes[2]
            return {"state": "ON" if (r or g or b) else "OFF", "rgb": [r, g, b]}
        if function in (FunctionCode.TW, FunctionCode.TWGRP):
            if len(state_bytes) < 7:
                return None
            brightness = min(state_bytes[6], 100)
            return {
                "state": "ON" if brightness > 0 else "OFF",
                "min_kelvin": _short(state_bytes, 0),
                "max_kelvin": _short(state_bytes, 2),
                "kelvin": _short(state_bytes, 4),
                "brightness": brightness,
            }
        if function == FunctionCode.ALARM:
            result = {"state": "ON" if param1 == STATE_ON else "OFF"}
            if param1 == STATE_ON and len(state_bytes) > 3:
                result["beeps"] = state_bytes[2]
                lines = _text_fields(state_bytes, 4, state_bytes[3])
                result["line1"] = lines[0] if lines else ""
                result["line2"] = lines[1] if len(lines) > 1 else ""
            return result
        return None

    @staticmethod
    def _decode_audio(data: bytes) -> dict[str, Any]:
        # [state/source, volume, field count, source name, track line 1, track line 2]
        code = data[0]
        source = next((n for n, c in AUDIO_SOURCES.items() if c == code), None)
        result: dict[str, Any] = {"state": "OFF" if code == AUDIO_OFF else "ON", "source": source}
        if len(data) > 1:
            result["volume"] = min(data[1], 100)
        if len(data) > 2:
            texts = _text_fields(data, 3, data[2])
            for key, text in zip(("source_name", "track_line1", "track_line2"), texts):
                result[key] = text
        return result

    # ------------------------------------------------------------------
    # Keep-alive
    # ------------------------------------------------------------------

    async def _keep_alive_loop(self) -> None:
        """Send a KEEP_ALIVE every 60s to prevent the central from timing out."""
        while self._connected:
            await asyncio.sleep(60)
            if self._connected:
                await self._send(self._build_keep_alive())
