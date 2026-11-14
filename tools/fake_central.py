"""Minimal fake Teletask central for local integration testing.

Lets you run the integration in the dev Home Assistant (docker-compose.dev.yml)
without touching your real installation, and simulate outages by stopping it.

TCP (default 55957): plain TDS framing. ACKs every valid frame, answers GET and
GROUPGET with EVENT frames, applies SET to its state table and pushes the new
state to the *other* connected clients (like the real central).
HTTP (default 80): /cgi-bin/serial.cgi and /cgi-bin/time.cgi like a PICOS.

Usage:  python3 tools/fake_central.py [tcp_port] [http_port]
In the integration setup use host  host.docker.internal  and port 55957.
Stop it with Ctrl+C to simulate the central going offline.
"""
from __future__ import annotations

import asyncio
import sys
import time

STX, ACK = 0x02, 0x0A
CMD_SET, CMD_GET, CMD_LOG, CMD_GROUPGET, CMD_KEEP_ALIVE, CMD_EVENT = 0x07, 0x06, 0x03, 0x09, 0x0B, 0x10
RELAY, DIMMER, LOCMOOD, GENMOOD, FLAG, SENSOR = 1, 2, 8, 10, 15, 20

# (function, number) -> state bytes. Unknown components report 0.
STATE: dict[tuple[int, int], bytes] = {
    (RELAY, 22): b"\xff", (RELAY, 25): b"\xff", (RELAY, 26): b"\xff",
    (SENSOR, 19): bytes([0x0B, 0x8E]),          # 2958 → 22.8 °C
}
CLIENTS: set[asyncio.StreamWriter] = set()


def frame(payload: bytes) -> bytes:
    msg = bytes([STX, len(payload) + 2]) + payload
    return msg + bytes([sum(msg) & 0xFF])


def event(fn: int, num: int) -> bytes:
    default = b"\x00\x00" if fn == SENSOR else b"\x00"
    state = STATE.get((fn, num), default)
    # [CMD, CID, FN, NUM_HI, NUM_LO, ERROR, STATE...]
    return frame(bytes([CMD_EVENT, 1, fn, num >> 8, num & 0xFF, 0]) + state)


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    CLIENTS.add(writer)
    log(f"client connected {peer}")
    buf = b""
    try:
        while data := await reader.read(1024):
            buf += data
            while len(buf) >= 2:
                if buf[0] != STX:
                    buf = buf[1:]
                    continue
                total = buf[1] + 1
                if len(buf) < total:
                    break
                fr, buf = buf[:total], buf[total:]
                if sum(fr[:-1]) & 0xFF != fr[-1]:
                    log(f"bad checksum {fr.hex(' ')}")
                    continue
                writer.write(bytes([ACK]))
                cmd, body = fr[2], fr[3:-1]
                if cmd == CMD_GET:                       # CID FN NUM_HI NUM_LO
                    writer.write(event(body[1], (body[2] << 8) | body[3]))
                elif cmd == CMD_GROUPGET:                # CID FN (NUM_HI NUM_LO)*
                    fn = body[1]
                    for i in range(2, len(body) - 1, 2):
                        writer.write(event(fn, (body[i] << 8) | body[i + 1]))
                elif cmd == CMD_SET:                     # CID FN NUM_HI NUM_LO VALUE...
                    fn, num = body[1], (body[2] << 8) | body[3]
                    STATE[(fn, num)] = bytes(body[4:])
                    log(f"SET fn={fn} num={num} -> {body[4:].hex(' ')}")
                    for other in CLIENTS - {writer}:
                        other.write(event(fn, num))
                elif cmd == CMD_LOG:
                    log(f"LOG subscribe fn={body[0]}")
                elif cmd == CMD_KEEP_ALIVE:
                    pass
                elif cmd == 0x04:                        # display message
                    log(f"DISPLAY MESSAGE {body.hex(' ')}")
                elif cmd == 0x22:                        # DoIP per-device subscribe
                    log(f"SUBSCRIBE fn={body[1]} num={(body[2] << 8) | body[3]}")
                else:
                    log(f"unhandled cmd 0x{cmd:02x} {body.hex(' ')}")
            await writer.drain()
    except ConnectionError:
        pass
    finally:
        CLIENTS.discard(writer)
        writer.close()
        log(f"client disconnected {peer}")


def _utf16(text: str) -> str:
    return "".join("\x00" + ch for ch in text)


# Same structure as a real PICOS serial.cgi (from tests/test_webinfo.py).
SERIAL_HTML = (
    "<HTML>\n<BODY bgcolor=white>\n<h3>\ntype=000010009\nType = PICOS</h3>\n"
    "<h3>Serial Number = \n555000001\n</h3>\n"
    "<h3>Mac Address = \nE4:1E:0A:00:00:01\n</h3>\n"
    "<h3>Installed PROSOFT = \nVersion:4.1.2.0\n"
    "<h3>Disk version = \n 1.14\n</h3>\n"
    "OS date = \nWed Dec 9\n 2009\n</h3>\n"
    "<h3>Filename = \n"
    + _utf16("C:\\Users\\Dev\\Documents\\FAKE CENTRAL 07112026.nbt;Dev Tester\r")
    + "\x00\n</h3>\n</BODY>\n</HTML>\n"
)


async def http(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    request = (await reader.readline()).decode(errors="replace")
    while (await reader.readline()) not in (b"\r\n", b"\n", b""):
        pass
    path = request.split(" ")[1] if " " in request else "/"
    if path == "/cgi-bin/serial.cgi":
        body = SERIAL_HTML
    elif path == "/cgi-bin/time.cgi":
        body = f"<HTML>\n<h3>Current Time = \n{time.strftime('%a %b %e %H:%M:%S CET %Y')}\n</h3>\n</BODY>\n</HTML>\n"
    else:
        body = "<html><body>fake central</body></html>"
    payload = body.encode()
    writer.write(
        b"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
        + str(len(payload)).encode() + b"\r\n\r\n" + payload
    )
    await writer.drain()
    writer.close()


async def main() -> None:
    tcp_port = int(sys.argv[1]) if len(sys.argv) > 1 else 55957
    http_port = int(sys.argv[2]) if len(sys.argv) > 2 else 80
    tcp = await asyncio.start_server(handle, "0.0.0.0", tcp_port)
    web = await asyncio.start_server(http, "0.0.0.0", http_port)
    log(f"fake central listening: tcp {tcp_port}, http {http_port}")
    async with tcp, web:
        await asyncio.gather(tcp.serve_forever(), web.serve_forever())


if __name__ == "__main__":
    asyncio.run(main())
