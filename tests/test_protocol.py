"""Unit tests for the Teletask protocol layer — no live central required.

Run with:
    pytest tests/test_protocol.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Import client.py directly — avoids homeassistant imports from __init__.py.
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "teletask"))

from client import (  # noqa: E402
    FunctionCode,
    TeletaskClient,
    TeletaskEvent,
    TELETASK_STX,
    CMD_SET, CMD_GET, CMD_LOG, CMD_GROUPGET, CMD_KEEP_ALIVE, CMD_EVENT, CMD_ACK,
    STATE_ON, STATE_OFF,
    MOTOR_STOP, MOTOR_GO_TO_POSITION,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client() -> TeletaskClient:
    """Return a TeletaskClient that is never actually connected (for framing tests)."""
    return TeletaskClient("localhost", 55957, lambda _: None)


def _checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def _make_event_frame(fn: int, number: int, *state_bytes: int) -> bytes:
    """Build a CMD_EVENT (0x10) frame as the central would send it."""
    body = bytes([
        TELETASK_STX, 0,            # STX + LENGTH placeholder
        CMD_EVENT,                   # 0x10
        1,                           # CID
        fn,                          # function
        (number >> 8) & 0xFF,        # NUM_HI
        number & 0xFF,               # NUM_LO
        0,                           # ERROR byte
        *state_bytes,
    ])
    length = len(body) - 1          # LENGTH counts STX + LENGTH itself
    body = bytes([body[0], length]) + body[2:]
    return body + bytes([_checksum(body)])


def _make_push_frame(fn: int, number: int, *state_bytes: int) -> bytes:
    """Build a CMD_GET (0x06) push frame as PICOS sends it (no CID)."""
    body = bytes([
        TELETASK_STX, 0,
        CMD_GET,                     # 0x06
        fn,
        (number >> 8) & 0xFF,
        number & 0xFF,
        *state_bytes,
    ])
    length = len(body) - 1
    body = bytes([body[0], length]) + body[2:]
    return body + bytes([_checksum(body)])


# ---------------------------------------------------------------------------
# 1. Frame building
# ---------------------------------------------------------------------------

class TestFrameBuilding:
    def test_keep_alive_frame(self):
        c = _client()
        frame = c._build_keep_alive()
        # Expected: [0x02, 0x03, 0x0B, CS]
        assert frame[0] == TELETASK_STX
        assert frame[2] == CMD_KEEP_ALIVE
        assert frame[-1] == _checksum(frame[:-1])
        assert len(frame) == 4

    def test_keep_alive_known_bytes(self):
        """Verified against live central: keep-alive = 02 03 0b 10."""
        frame = _client()._build_keep_alive()
        assert frame == bytes([0x02, 0x03, 0x0B, 0x10])

    def test_set_relay_on(self):
        c = _client()
        frame = c._build_set(FunctionCode.RELAY, 5, STATE_ON)
        assert frame[2] == CMD_SET
        assert frame[3] == 1           # CID
        assert frame[4] == FunctionCode.RELAY
        assert frame[5] == 0x00        # NUM_HI
        assert frame[6] == 0x05        # NUM_LO
        assert frame[7] == STATE_ON
        assert frame[-1] == _checksum(frame[:-1])

    def test_set_relay_off(self):
        frame = _client()._build_set(FunctionCode.RELAY, 5, STATE_OFF)
        assert frame[7] == STATE_OFF
        assert frame[-1] == _checksum(frame[:-1])

    def test_set_dimmer_brightness_50(self):
        frame = _client()._build_set(FunctionCode.DIMMER, 2, 50)
        assert frame[4] == FunctionCode.DIMMER
        assert frame[6] == 0x02        # NUM_LO
        assert frame[7] == 50
        assert len(frame) == 9

    def test_set_with_param2_appended(self):
        """Motor GOTO_POSITION sends two state bytes: [cmd=11, position]."""
        frame = _client()._build_set(FunctionCode.MOTOR, 1, MOTOR_GO_TO_POSITION, 75)
        assert frame[7] == MOTOR_GO_TO_POSITION   # param1 = 11
        assert frame[8] == 75                     # param2 = position
        assert len(frame) == 10
        assert frame[-1] == _checksum(frame[:-1])

    def test_set_motor_stop(self):
        frame = _client()._build_set(FunctionCode.MOTOR, 1, MOTOR_STOP)
        assert frame[7] == 3           # MOTOR_STOP = 3
        assert len(frame) == 9

    def test_get_frame(self):
        frame = _client()._build_get(FunctionCode.RELAY, 5)
        assert frame[2] == CMD_GET
        assert frame[3] == 1           # CID
        assert frame[4] == FunctionCode.RELAY
        assert frame[5] == 0x00
        assert frame[6] == 0x05
        assert frame[-1] == _checksum(frame[:-1])

    def test_log_frame_no_component_number(self):
        """LOG must contain only [CMD_LOG, FN, 0xFF] — no component number."""
        frame = _client()._build_log(FunctionCode.RELAY)
        assert frame[2] == CMD_LOG
        assert frame[3] == FunctionCode.RELAY
        assert frame[4] == 0xFF        # subscribe flag
        assert len(frame) == 6         # STX + LEN + CMD + FN + 0xFF + CS
        assert frame[-1] == _checksum(frame[:-1])

    def test_log_known_bytes_relay(self):
        """Spot-check against hand-calculated value for RELAY log subscribe."""
        frame = _client()._build_log(FunctionCode.RELAY)
        # payload = [0x03, 0x01, 0xFF], length=5
        # msg = [0x02, 0x05, 0x03, 0x01, 0xFF], cs=(2+5+3+1+255)&0xFF=10
        assert frame == bytes([0x02, 0x05, 0x03, 0x01, 0xFF, 0x0A])

    def test_groupget_frame(self):
        frame = _client()._build_groupget(FunctionCode.RELAY, [5])
        assert frame[2] == CMD_GROUPGET
        assert frame[3] == 1           # CID
        assert frame[4] == FunctionCode.RELAY
        assert frame[5] == 0x00
        assert frame[6] == 0x05
        assert frame[-1] == _checksum(frame[:-1])

    def test_checksum_all_frames(self):
        """Every built frame must have a valid checksum."""
        c = _client()
        frames = [
            c._build_keep_alive(),
            c._build_set(FunctionCode.RELAY, 1, STATE_ON),
            c._build_set(FunctionCode.DIMMER, 2, 75),
            c._build_set(FunctionCode.MOTOR, 1, MOTOR_STOP),
            c._build_set(FunctionCode.MOTOR, 1, MOTOR_GO_TO_POSITION, 50),
            c._build_get(FunctionCode.RELAY, 1),
            c._build_log(FunctionCode.RELAY),
            c._build_log(FunctionCode.DIMMER),
            c._build_groupget(FunctionCode.RELAY, [1, 2, 3]),
        ]
        for frame in frames:
            assert frame[-1] == _checksum(frame[:-1]), f"Bad CS in {frame.hex(' ')}"


# ---------------------------------------------------------------------------
# 2. Frame parsing — CMD_EVENT (0x10)
# ---------------------------------------------------------------------------

class TestParseEventFrame:
    def _parse(self, frame: bytes) -> TeletaskEvent | None:
        c = _client()
        buf = bytearray(frame)
        event, consumed = c._parse_frame(buf)
        assert consumed == len(frame)
        return event

    def test_relay_on(self):
        frame = _make_event_frame(FunctionCode.RELAY, 5, STATE_ON)
        evt = self._parse(frame)
        assert evt is not None
        assert evt.function == FunctionCode.RELAY
        assert evt.number == 5
        assert evt.state == {"state": "ON"}

    def test_relay_off(self):
        frame = _make_event_frame(FunctionCode.RELAY, 5, STATE_OFF)
        evt = self._parse(frame)
        assert evt.state == {"state": "OFF"}

    def test_dimmer_brightness_50(self):
        frame = _make_event_frame(FunctionCode.DIMMER, 2, 50)
        evt = self._parse(frame)
        assert evt.function == FunctionCode.DIMMER
        assert evt.number == 2
        assert evt.state["state"] == "ON"
        assert evt.state["brightness"] == 50

    def test_dimmer_off(self):
        frame = _make_event_frame(FunctionCode.DIMMER, 3, 0)
        evt = self._parse(frame)
        assert evt.state["state"] == "OFF"
        assert evt.state["brightness"] == 0

    def test_dimmer_0xff_mapped_to_100(self):
        """PICOS firmware quirk: 0xFF in dimmer event means 100% (not 255%)."""
        frame = _make_event_frame(FunctionCode.DIMMER, 2, 0xFF)
        evt = self._parse(frame)
        assert evt.state["brightness"] == 100
        assert evt.state["state"] == "ON"

    def test_sensor_temperature(self):
        """Temperature: 2-byte big-endian tenths of Kelvin → Celsius.
        0x0B86 = 2950 → 2950/10 - 273 = 22.0°C  (from live jeletask log)."""
        frame = _make_event_frame(FunctionCode.SENSOR, 19, 0x0B, 0x86)
        evt = self._parse(frame)
        assert evt.function == FunctionCode.SENSOR
        assert evt.state["value"] == pytest.approx(22.0)

    def test_motor_moving_up(self):
        """MOTOR: byte[0]=direction, byte[1]=power, byte[4]=position."""
        frame = _make_event_frame(FunctionCode.MOTOR, 1, 1, STATE_ON, 0, 0, 80)
        evt = self._parse(frame)
        assert evt.state["last_direction"] == "UP"
        assert evt.state["state"] == "ON"
        assert evt.state["current_position"] == 80

    def test_motor_stopped(self):
        """MOTOR STOP: direction=3, power=OFF."""
        frame = _make_event_frame(FunctionCode.MOTOR, 1, 3, STATE_OFF, 0, 0, 50)
        evt = self._parse(frame)
        assert evt.state["last_direction"] == "STOP"
        assert evt.state["state"] == "OFF"
        assert evt.state["current_position"] == 50

    def test_flag_on(self):
        frame = _make_event_frame(FunctionCode.FLAG, 4, STATE_ON)
        evt = self._parse(frame)
        assert evt.state == {"state": "ON"}

    def test_genmood_off(self):
        frame = _make_event_frame(FunctionCode.GENMOOD, 2, STATE_OFF)
        evt = self._parse(frame)
        assert evt.state == {"state": "OFF"}

    def test_bad_checksum_returns_none(self):
        frame = bytearray(_make_event_frame(FunctionCode.RELAY, 5, STATE_ON))
        frame[-1] ^= 0xFF              # corrupt checksum
        c = _client()
        event, consumed = c._parse_frame(frame)
        assert event is None
        assert consumed == 1           # skip one byte

    def test_too_short_frame_waits(self):
        frame = _make_event_frame(FunctionCode.RELAY, 5, STATE_ON)
        truncated = bytearray(frame[:-2])  # missing last 2 bytes
        c = _client()
        event, consumed = c._parse_frame(truncated)
        assert event is None
        assert consumed == 0           # wait for more data

    def test_leading_garbage_skipped(self):
        frame = _make_event_frame(FunctionCode.RELAY, 5, STATE_ON)
        garbage = bytes([0xDE, 0xAD]) + frame
        c = _client()
        event, consumed = c._parse_frame(bytearray(garbage))
        assert event is None
        assert consumed == 2           # skip garbage, stop at STX


# ---------------------------------------------------------------------------
# 3. Frame parsing — CMD_GET (0x06) LOG push (PICOS, no CID)
# ---------------------------------------------------------------------------

class TestParsePushFrame:
    def _parse(self, frame: bytes) -> TeletaskEvent | None:
        c = _client()
        buf = bytearray(frame)
        event, consumed = c._parse_frame(buf)
        assert consumed == len(frame)
        return event

    def test_relay_push_on(self):
        frame = _make_push_frame(FunctionCode.RELAY, 5, STATE_ON)
        evt = self._parse(frame)
        assert evt is not None
        assert evt.function == FunctionCode.RELAY
        assert evt.number == 5
        assert evt.state == {"state": "ON"}

    def test_relay_push_off(self):
        frame = _make_push_frame(FunctionCode.RELAY, 5, STATE_OFF)
        evt = self._parse(frame)
        assert evt.state == {"state": "OFF"}

    def test_dimmer_push_with_multi_state_bytes(self):
        """PICOS dimmer push includes extra trailing bytes — parser must not crash."""
        # From live log: State: 32 01 00 1E 00 01 00 FF  (brightness=50, power=ON, ...)
        frame = _make_push_frame(FunctionCode.DIMMER, 2, 0x32, 0x01, 0x00, 0x1E, 0x00, 0x01, 0x00, 0xFF)
        evt = self._parse(frame)
        assert evt.state["state"] == "ON"
        assert evt.state["brightness"] == 50

    def test_high_component_number(self):
        """Numbers above 255 use both NUM_HI and NUM_LO correctly."""
        frame = _make_push_frame(FunctionCode.RELAY, 300, STATE_ON)
        evt = self._parse(frame)
        assert evt.number == 300


# ---------------------------------------------------------------------------
# 4. State decoding — _decode_state
# ---------------------------------------------------------------------------

class TestDecodeState:
    def _decode(self, fn: int, *bytes_: int):
        return TeletaskClient._decode_state(fn, bytes(*bytes_))

    def test_relay_on(self):
        assert self._decode(FunctionCode.RELAY, STATE_ON) == {"state": "ON"}

    def test_relay_off(self):
        assert self._decode(FunctionCode.RELAY, STATE_OFF) == {"state": "OFF"}

    def test_relay_non_255_is_off(self):
        assert self._decode(FunctionCode.RELAY, 1)["state"] == "OFF"

    def test_dimmer_brightness(self):
        s = self._decode(FunctionCode.DIMMER, 75)
        assert s["state"] == "ON"
        assert s["brightness"] == 75

    def test_dimmer_0xff(self):
        s = self._decode(FunctionCode.DIMMER, 0xFF)
        assert s["brightness"] == 100
        assert s["state"] == "ON"

    def test_dimmer_zero(self):
        s = self._decode(FunctionCode.DIMMER, 0)
        assert s["state"] == "OFF"
        assert s["brightness"] == 0

    def test_dimmer_clamps_above_100(self):
        # Values 101-254 should be clamped to 100
        s = self._decode(FunctionCode.DIMMER, 120)
        assert s["brightness"] == 100

    def test_sensor_temperature_22(self):
        # 0x0B86 = 2950 → 295.0 - 273 = 22.0°C
        s = self._decode(FunctionCode.SENSOR, 0x0B, 0x86)
        assert s["value"] == pytest.approx(22.0)

    def test_sensor_temperature_0(self):
        # 0x0AAE = 2734 → 273.4 - 273 = 0.4°C (not exactly 0 but close)
        s = self._decode(FunctionCode.SENSOR, 0x0A, 0xAE)
        assert abs(s["value"] - 0.4) < 0.1

    def test_locmood_on(self):
        assert self._decode(FunctionCode.LOCMOOD, STATE_ON) == {"state": "ON"}

    def test_genmood_off(self):
        assert self._decode(FunctionCode.GENMOOD, STATE_OFF) == {"state": "OFF"}

    def test_flag_on(self):
        assert self._decode(FunctionCode.FLAG, STATE_ON) == {"state": "ON"}

    def test_cond_off(self):
        assert self._decode(FunctionCode.COND, STATE_OFF) == {"state": "OFF"}

    def test_input_closed(self):
        # Value 2 = CLOSED per protocol docs
        assert self._decode(FunctionCode.INPUT, 2) == {"state": "CLOSED"}

    def test_input_open(self):
        # Value 3 = OPEN
        assert self._decode(FunctionCode.INPUT, 3) == {"state": "OPEN"}

    def test_input_short_press(self):
        assert self._decode(FunctionCode.INPUT, 1) == {"state": "SHORT_PRESS"}

    def test_motor_up_power_on(self):
        # direction=1(UP), power=255(ON), skip protection, req_pos, cur_pos=80
        s = self._decode(FunctionCode.MOTOR, 1, STATE_ON, 0, 0, 80)
        assert s["last_direction"] == "UP"
        assert s["state"] == "ON"
        assert s["current_position"] == 80

    def test_motor_stop_power_off(self):
        s = self._decode(FunctionCode.MOTOR, MOTOR_STOP, STATE_OFF, 0, 0, 0)
        assert s["last_direction"] == "STOP"
        assert s["state"] == "OFF"

    def test_motor_no_position_bytes(self):
        """When central sends only direction+power, position key is absent."""
        s = self._decode(FunctionCode.MOTOR, 1, STATE_ON)
        assert "current_position" not in s

    def test_unknown_function_returns_none(self):
        assert TeletaskClient._decode_state(99, bytes([0xFF])) is None

    def test_empty_state_bytes_returns_none(self):
        assert TeletaskClient._decode_state(FunctionCode.RELAY, b"") is None


# ---------------------------------------------------------------------------
# 5. Protocol constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_motor_stop_is_3(self):
        assert MOTOR_STOP == 3

    def test_motor_goto_position_is_11(self):
        assert MOTOR_GO_TO_POSITION == 11

    def test_state_on_is_255(self):
        assert STATE_ON == 255

    def test_state_off_is_0(self):
        assert STATE_OFF == 0

    def test_function_codes(self):
        assert FunctionCode.RELAY    == 1
        assert FunctionCode.DIMMER   == 2
        assert FunctionCode.MOTOR    == 6
        assert FunctionCode.LOCMOOD  == 8
        assert FunctionCode.TIMEDMOOD == 9
        assert FunctionCode.GENMOOD  == 10
        assert FunctionCode.FLAG     == 15
        assert FunctionCode.SENSOR   == 20
        assert FunctionCode.COND     == 60


# ---------------------------------------------------------------------------
# 6. Buffer parsing — multiple frames and edge cases
# ---------------------------------------------------------------------------

class TestBufferParsing:
    def test_ack_byte_not_parsed_as_frame(self):
        """CMD_ACK (0x0A) must be handled in the receive loop, not _parse_frame."""
        buf = bytearray([CMD_ACK])
        c = _client()
        event, consumed = c._parse_frame(buf)
        # ACK byte is not STX, so it should be skipped
        assert event is None

    def test_two_consecutive_frames(self):
        """Parser processes first frame, leaves second in buffer."""
        f1 = _make_event_frame(FunctionCode.RELAY, 1, STATE_ON)
        f2 = _make_event_frame(FunctionCode.RELAY, 2, STATE_OFF)
        buf = bytearray(f1 + f2)
        c = _client()

        event1, consumed1 = c._parse_frame(buf)
        assert event1 is not None
        assert consumed1 == len(f1)

        event2, consumed2 = c._parse_frame(buf[consumed1:])
        assert event2 is not None
        assert event2.number == 2

    def test_partial_frame_waits(self):
        frame = _make_event_frame(FunctionCode.RELAY, 5, STATE_ON)
        c = _client()
        for cut in range(1, len(frame)):
            event, consumed = c._parse_frame(bytearray(frame[:cut]))
            assert consumed == 0, f"Should wait at cut={cut}"

    def test_full_frame_after_ack(self):
        """ACK followed by a real frame: the receive loop skips ACK first."""
        frame = _make_event_frame(FunctionCode.RELAY, 5, STATE_ON)
        # Simulate receive loop: ACK is stripped before _parse_frame is called.
        buf = bytearray(frame)
        c = _client()
        event, consumed = c._parse_frame(buf)
        assert event is not None
        assert consumed == len(frame)
