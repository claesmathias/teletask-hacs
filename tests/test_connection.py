"""Integration tests against a live Teletask central unit.

Run with:
    pytest tests/test_connection.py -v
    pytest tests/test_connection.py -v --config /path/to/config.json

Requires the central to be reachable at teletask.klokkeveld:55957.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import pytest

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("client").setLevel(logging.DEBUG)

# Import client.py directly to avoid triggering __init__.py which requires homeassistant.
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "teletask"))

from client import (  # noqa: E402
    FunctionCode,
    TeletaskClient,
    TeletaskEvent,
)

HOST = "teletask.klokkeveld"
PORT = 55957


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def relay_number(teletask_config):
    return teletask_config["componentsTypes"]["RELAY"][0]["number"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(on_event=None, on_disconnect=None) -> TeletaskClient:
    return TeletaskClient(
        host=HOST,
        port=PORT,
        event_callback=on_event or (lambda _: None),
        disconnect_callback=on_disconnect,
    )


async def _wait_for_event(
    client: TeletaskClient,
    function: int,
    number: int,
    *,
    timeout: float = 5.0,
) -> TeletaskEvent:
    """Subscribe and wait until an event arrives for the given component."""
    received: asyncio.Future[TeletaskEvent] = asyncio.get_running_loop().create_future()

    def _cb(event: TeletaskEvent) -> None:
        if event.function == function and event.number == number:
            if not received.done():
                received.set_result(event)

    client._event_callback = _cb
    await client.subscribe(function, number)
    result = await asyncio.wait_for(received, timeout=timeout)
    # Let any delayed LOG-welcome events drain with this callback before the caller
    # replaces it — prevents spurious captures in subsequent _set_and_wait calls.
    await asyncio.sleep(0.15)
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect():
    """Client can establish a TCP connection to the central."""
    client = _make_client()
    try:
        ok = await client.connect()
        assert ok, "connect() returned False — cannot reach the central"
        assert client.connected
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_disconnect_sets_flag():
    """Calling disconnect() marks the client as no longer connected."""
    client = _make_client()
    await client.connect()
    await client.disconnect()
    assert not client.connected


@pytest.mark.asyncio
async def test_disconnect_callback_fires():
    """The disconnect callback is invoked when the connection closes."""
    fired = asyncio.Event()

    client = _make_client(on_disconnect=lambda: fired.set())
    await client.connect()
    # _handle_disconnect checks the flag itself — call it directly without pre-clearing.
    client._handle_disconnect()

    assert fired.is_set()
    await client.disconnect()


@pytest.mark.asyncio
async def test_subscribe_receives_event(relay_number):
    """Subscribing to a component triggers an initial state event from the central."""
    client = _make_client()
    await client.connect()
    try:
        event = await _wait_for_event(client, FunctionCode.RELAY, relay_number)
        assert event.function == FunctionCode.RELAY
        assert event.number == relay_number
        assert "state" in event.state
        assert event.state["state"] in ("ON", "OFF")
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_get_state_receives_event(relay_number):
    """A GET command causes the central to reply with the current state."""
    client = _make_client()
    await client.connect()
    try:
        await client.subscribe(FunctionCode.RELAY, relay_number)
        await asyncio.sleep(0.1)

        received: asyncio.Future[TeletaskEvent] = asyncio.get_running_loop().create_future()

        def _cb(event: TeletaskEvent) -> None:
            if event.function == FunctionCode.RELAY and event.number == relay_number:
                if not received.done():
                    received.set_result(event)

        client._event_callback = _cb
        await client.get_state(FunctionCode.RELAY, relay_number)

        event = await asyncio.wait_for(received, timeout=5.0)
        assert event.state["state"] in ("ON", "OFF")
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_set_relay_on_and_off(relay_number):
    """SET commands toggle the relay and produce corresponding state events."""
    client = _make_client()
    await client.connect()
    try:
        initial = await _wait_for_event(client, FunctionCode.RELAY, relay_number)

        async def _set_and_get(state: bool) -> TeletaskEvent:
            """SET then GET — the central doesn't echo SET back to the sender."""
            fut: asyncio.Future[TeletaskEvent] = asyncio.get_running_loop().create_future()

            def _cb(event: TeletaskEvent) -> None:
                if event.function == FunctionCode.RELAY and event.number == relay_number:
                    if not fut.done():
                        fut.set_result(event)

            client._event_callback = _cb
            await client.set_state(
                FunctionCode.RELAY, relay_number, 0xFF if state else 0x00
            )
            await client.get_state(FunctionCode.RELAY, relay_number)
            return await asyncio.wait_for(fut, timeout=5.0)

        # Toggle to the opposite of the current state, then back.
        is_on = initial.state["state"] == "ON"

        toggled = await _set_and_get(not is_on)
        assert toggled.state["state"] == ("OFF" if is_on else "ON")

        restored = await _set_and_get(is_on)
        assert restored.state["state"] == ("ON" if is_on else "OFF")
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_keep_alive_prevents_timeout(relay_number):
    """Connection stays alive for longer than the central's 30-second idle timeout."""
    client = _make_client()
    await client.connect()
    try:
        await client.subscribe(FunctionCode.RELAY, relay_number)
        # Wait 35 seconds — the keep-alive (20s interval) must fire before the
        # central's ~30s idle timeout closes the connection.
        await asyncio.sleep(35)
        assert client.connected, "Central dropped the connection despite keep-alive"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_send_while_disconnected_does_not_raise(relay_number):
    """Sending a command while not connected logs a warning but does not raise."""
    client = _make_client()
    # Never connect — just try to send.
    await client.get_state(FunctionCode.RELAY, relay_number)  # must not raise


@pytest.mark.asyncio
async def test_all_config_relays_subscribe(teletask_config):
    """Every RELAY in config.json can be subscribed without error."""
    relays = teletask_config["componentsTypes"].get("RELAY", [])
    events: list[TeletaskEvent] = []

    client = _make_client(on_event=events.append)
    await client.connect()
    try:
        for comp in relays:
            await client.subscribe(FunctionCode.RELAY, comp["number"])
            await asyncio.sleep(0.05)

        # Give the central time to reply to all subscriptions.
        await asyncio.sleep(2.0)

        subscribed_numbers = {comp["number"] for comp in relays}
        received_numbers = {
            e.number for e in events if e.function == FunctionCode.RELAY
        }
        assert subscribed_numbers == received_numbers, (
            f"Missing responses for relay(s): {subscribed_numbers - received_numbers}"
        )
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_raw_protocol_dump():
    """Diagnostic: send GROUPGET + LOG for relay 5, print every received frame decoded."""

    CMD_NAMES = {0x02: "GROUPGET", 0x03: "LOG", 0x06: "GET", 0x07: "SET",
                 0x0B: "KEEP_ALIVE", 0x10: "EVENT"}
    FN_NAMES  = {1: "RELAY", 2: "DIMMER", 6: "MOTOR", 8: "LOCMOOD", 10: "GENMOOD",
                 15: "FLAG", 20: "SENSOR"}

    def p(msg: str) -> None:
        print(f"\n[PROTO] {msg}", flush=True)

    def decode_frames(data: bytes) -> str:
        buf = bytearray(data)
        results = []
        while len(buf) >= 2:
            if buf[0] != 0x02:
                buf = buf[1:]
                continue
            length = buf[1]
            total = length + 2
            if len(buf) < total:
                break
            frame = buf[:total]
            cs_ok = (sum(frame[:-1]) & 0xFF) == frame[-1]
            cmd = frame[2] if len(frame) > 2 else 0
            fn  = frame[3] if len(frame) > 3 else 0
            num = ((frame[4] << 8) | frame[5]) if len(frame) > 5 else 0
            p1  = frame[6] if len(frame) > 6 else 0
            p2  = frame[7] if len(frame) > 7 else 0
            cmd_name = CMD_NAMES.get(cmd, f"0x{cmd:02X}")
            fn_name  = FN_NAMES.get(fn,  f"fn={fn}")
            results.append(
                f"  frame={frame.hex(' ')} cs={'OK' if cs_ok else 'BAD'} "
                f"cmd={cmd_name} fn={fn_name} num={num} p1=0x{p1:02X} p2=0x{p2:02X}"
            )
            buf = buf[total:]
        return "\n".join(results) if results else "  (no decodable frames)"

    def make_frame(payload: bytes) -> bytes:
        length = len(payload) + 1
        msg = bytes([0x02, length]) + payload
        return msg + bytes([sum(msg) & 0xFF])

    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(HOST, PORT), timeout=10
    )
    p(f"Connected to {HOST}:{PORT}")

    async def tx(label: str, frame: bytes) -> None:
        p(f"TX {label}: {frame.hex(' ')}")
        try:
            writer.write(frame)
            await writer.drain()
        except (OSError, ConnectionResetError) as exc:
            p(f"  Send failed: {exc}")

    async def read_for(seconds: float, label: str = "") -> None:
        deadline = asyncio.get_running_loop().time() + seconds
        buf = bytearray()
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                data = await asyncio.wait_for(reader.read(1024), timeout=remaining)
                if data:
                    buf.extend(data)
                else:
                    p("  Central closed")
                    break
            except asyncio.TimeoutError:
                break
            except (OSError, ConnectionResetError) as exc:
                p(f"  RST: {exc}")
                break
        if buf:
            p(f"RX{(' '+label) if label else ''} ({len(buf)} bytes): {bytes(buf).hex(' ')}\n{decode_frames(bytes(buf))}")
        else:
            p(f"RX{(' '+label) if label else ''}: nothing received")

    # Step 1 — KEEP_ALIVE handshake (mandatory before central accepts any command).
    await tx("KEEP_ALIVE", make_frame(bytes([0x0B, 0x01])))
    await read_for(2.0, "after KEEP_ALIVE")

    # Try every plausible variant of GROUPGET and SET to find which one the central responds to.
    # Two axes of variation:
    #   1. Whether a CENTRAL_ID byte (0x01) is included after CMD
    #   2. Whether payload includes trailing P2=0x00 or not

    variants = [
        # Label,  payload bytes (without STX/LENGTH/CS)
        # ---- GROUPGET variants ----
        ("GROUPGET no-CID 4B",        bytes([0x02, 0x01, 0x00, 0x05])),
        ("GROUPGET CID-after-CMD 5B", bytes([0x02, 0x01, 0x01, 0x00, 0x05])),

        # ---- LOG variants (subscribe relay 5) ----
        ("LOG no-CID 4B",             bytes([0x03, 0x01, 0x00, 0x05])),
        ("LOG no-CID+P1 5B",          bytes([0x03, 0x01, 0x00, 0x05, 0xFF])),
        ("LOG no-CID+P1P2 6B",        bytes([0x03, 0x01, 0x00, 0x05, 0xFF, 0x00])),
        ("LOG CID 5B",                bytes([0x03, 0x01, 0x01, 0x00, 0x05])),
        ("LOG CID+P1 6B",             bytes([0x03, 0x01, 0x01, 0x00, 0x05, 0xFF])),
        ("LOG CID+P1P2 7B",           bytes([0x03, 0x01, 0x01, 0x00, 0x05, 0xFF, 0x00])),

        # ---- GET variants ----
        ("GET no-CID 4B",             bytes([0x06, 0x01, 0x00, 0x05])),
        ("GET no-CID+PP 6B",          bytes([0x06, 0x01, 0x00, 0x05, 0x00, 0x00])),
        ("GET CID 5B",                bytes([0x06, 0x01, 0x01, 0x00, 0x05])),
        ("GET CID+PP 7B",             bytes([0x06, 0x01, 0x01, 0x00, 0x05, 0x00, 0x00])),

        # ---- SET ON variants (watch the Eettafel light!) ----
        ("SET-ON no-CID 5B",          bytes([0x07, 0x01, 0x00, 0x05, 0xFF])),
        ("SET-ON no-CID+P2 6B",       bytes([0x07, 0x01, 0x00, 0x05, 0xFF, 0x00])),
        ("SET-ON CID 6B",             bytes([0x07, 0x01, 0x01, 0x00, 0x05, 0xFF])),
        ("SET-ON CID+P2 7B",          bytes([0x07, 0x01, 0x01, 0x00, 0x05, 0xFF, 0x00])),

        # ---- SET OFF variants ----
        ("SET-OFF no-CID 5B",         bytes([0x07, 0x01, 0x00, 0x05, 0x00])),
        ("SET-OFF no-CID+P2 6B",      bytes([0x07, 0x01, 0x00, 0x05, 0x00, 0x00])),
        ("SET-OFF CID 6B",            bytes([0x07, 0x01, 0x01, 0x00, 0x05, 0x00])),
        ("SET-OFF CID+P2 7B",         bytes([0x07, 0x01, 0x01, 0x00, 0x05, 0x00, 0x00])),
    ]

    for label, payload in variants:
        frame = make_frame(payload)
        await tx(label, frame)
        await read_for(1.5, f"after {label}")

    p("Done")

    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass
