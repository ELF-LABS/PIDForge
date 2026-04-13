#!/usr/bin/env python3
# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Mock Betaflight FC — MSP v1 over WebSocket (:5051), PID/filter state, optional blackbox CSV."""

from __future__ import annotations

import asyncio
import struct
from typing import Any, Dict, Optional

import websockets

from generate_flight import build_headers, csv_bytes, flight_quality

# MSP v1 (subset) — align with msp.py / bt_msp_bridge.js
MSP_FC_VARIANT = 2
MSP_STATUS = 101
MSP_PID = 112
MSP_SET_PID = 202
MSP_FILTER_CONFIG = 92
MSP_SET_FILTER_CONFIG = 93
MSP_PID_ADVANCED = 94
MSP_DATAFLASH_SUMMARY = 70
MSP_DATAFLASH_READ = 71
MSP_EEPROM_WRITE = 250


def _crc_xor(body: bytes) -> int:
    c = 0
    for b in body:
        c ^= b
    return c & 0xFF


def encode_msp_response(cmd: int, payload: bytes = b"") -> bytes:
    pl = payload[:255]
    body = bytes([len(pl) & 0xFF, cmd & 0xFF]) + pl
    return b"$M>" + body + bytes([_crc_xor(body)])


def parse_msp_request(frame: bytes) -> Optional[tuple[int, bytes]]:
    if len(frame) < 6 or frame[:3] != b"$M<":
        return None
    size = frame[3]
    cmd = frame[4]
    if len(frame) < 5 + size + 1:
        return None
    payload = frame[5 : 5 + size]
    crc = frame[5 + size]
    body = frame[3 : 5 + size]
    if _crc_xor(body) != crc:
        return None
    return cmd, payload


class MockFC:
    def __init__(self) -> None:
        self.pids: Dict[str, Dict[str, int]] = {
            "roll": {"P": 38, "I": 82, "D": 26, "F": 120},
            "pitch": {"P": 58, "I": 92, "D": 48, "F": 130},
            "yaw": {"P": 45, "I": 90, "D": 0, "F": 120},
        }
        self.filters: Dict[str, int] = {
            "gyro_lpf1": 250,
            "gyro_lpf2": 500,
            "dterm_lpf1": 100,
            "dterm_lpf2": 150,
            "gyro_notch1_hz": 0,
            "gyro_notch2_hz": 0,
        }
        self.fc_info: Dict[str, str] = {
            "name": "SIMULATOR",
            "firmware": "Betaflight 4.5.0 (SIM)",
            "board": "VIRTUAL_F7",
            "uid": "DEADBEEF",
        }
        self.flight_count = 0
        self._bb: bytes = b""
        self._bb_name = "sim_log.csv"

    def encode_pids(self) -> bytes:
        out = []
        for ax in ("roll", "pitch", "yaw"):
            p = self.pids[ax]
            out.extend([int(p["P"]), int(p["I"]), int(p["D"])])
        return struct.pack("<9H", *out)

    def apply_pids(self, payload: bytes) -> None:
        if len(payload) < 18:
            return
        vals = struct.unpack("<9H", payload[:18])
        axes = ("roll", "pitch", "yaw")
        for i, ax in enumerate(axes):
            self.pids[ax]["P"] = int(vals[i * 3])
            self.pids[ax]["I"] = int(vals[i * 3 + 1])
            self.pids[ax]["D"] = int(vals[i * 3 + 2])

    def encode_pid_advanced(self) -> bytes:
        # Minimal payload — many fields; keep zeros for unused
        return b"\x00" * 34

    def encode_filters(self) -> bytes:
        # Simplified: pack a few u16 values BF would expect (not full struct)
        return struct.pack(
            "<8H",
            int(self.filters["gyro_lpf1"]),
            int(self.filters["gyro_lpf2"]),
            int(self.filters["dterm_lpf1"]),
            int(self.filters["dterm_lpf2"]),
            int(self.filters["gyro_notch1_hz"]),
            int(self.filters["gyro_notch2_hz"]),
            0,
            0,
        )

    def apply_filters(self, payload: bytes) -> None:
        if len(payload) < 6:
            return
        g1, g2, d1, d2 = struct.unpack_from("<4H", payload, 0)
        self.filters["gyro_lpf1"] = int(g1)
        self.filters["gyro_lpf2"] = int(g2)
        self.filters["dterm_lpf1"] = int(d1)
        self.filters["dterm_lpf2"] = int(d2)

    def dataflash_summary(self) -> bytes:
        total = len(self._bb)
        used = total
        # BF-ish: supported, flags, sectors, total, used (u8 + 4xu32)
        return struct.pack("<BIIII", 1, 0, 4096, total & 0xFFFFFFFF, used & 0xFFFFFFFF)

    def dataflash_read(self, payload: bytes) -> bytes:
        if len(payload) < 6:
            return b""
        addr = struct.unpack_from("<I", payload, 0)[0]
        size = struct.unpack_from("<H", payload, 4)[0]
        end = min(len(self._bb), addr + size)
        if addr >= len(self._bb):
            return b""
        return self._bb[addr:end]

    def regenerate_blackbox(self, seed: Optional[int] = None) -> None:
        self.flight_count += 1
        self._bb = csv_bytes(self, seed=seed)
        q = flight_quality(self)
        print(f"[SIM] flight #{self.flight_count} generated, quality={q:.3f}, bytes={len(self._bb)}")

    def handle_msp(self, cmd: int, payload: bytes) -> bytes:
        if cmd == MSP_PID:
            return self.encode_pids()
        if cmd == MSP_SET_PID:
            self.apply_pids(payload)
            return b""
        if cmd == MSP_PID_ADVANCED:
            return self.encode_pid_advanced()
        if cmd == MSP_FILTER_CONFIG:
            return self.encode_filters()
        if cmd == MSP_SET_FILTER_CONFIG:
            self.apply_filters(payload)
            return b""
        if cmd == MSP_EEPROM_WRITE:
            self.regenerate_blackbox()
            return b""
        if cmd == MSP_DATAFLASH_SUMMARY:
            return self.dataflash_summary()
        if cmd == MSP_DATAFLASH_READ:
            return self.dataflash_read(payload)
        if cmd == MSP_STATUS:
            return struct.pack("<HHH", 0, 0, 0)
        if cmd == MSP_FC_VARIANT:
            return b"BTFL"
        return b""


def apply_cli_line(fc: MockFC, line: str) -> bool:
    """Parse `set name = val` / `set name val` and update fc state."""
    s = line.strip().lower()
    if not s or s.startswith("#"):
        return False
    if not s.startswith("set "):
        return False
    s = s[4:].strip()
    if "=" in s:
        k, v = s.split("=", 1)
    else:
        parts = s.split()
        if len(parts) < 2:
            return False
        k, v = parts[0], parts[1]
    k = k.strip()
    try:
        val = int(float(v.strip()))
    except ValueError:
        return False
    mapping = {
        "p_roll": ("pids", "roll", "P"),
        "i_roll": ("pids", "roll", "I"),
        "d_roll": ("pids", "roll", "D"),
        "p_pitch": ("pids", "pitch", "P"),
        "i_pitch": ("pids", "pitch", "I"),
        "d_pitch": ("pids", "pitch", "D"),
        "p_yaw": ("pids", "yaw", "P"),
        "i_yaw": ("pids", "yaw", "I"),
        "d_yaw": ("pids", "yaw", "D"),
        "dterm_lpf1_static_hz": ("filters", "dterm_lpf1", None),
        "dterm_lpf1_dyn_min_hz": ("filters", "dterm_lpf1", None),
        "dterm_lpf2_static_hz": ("filters", "dterm_lpf2", None),
    }
    if k not in mapping:
        return False
    grp, key, sub = mapping[k]
    bucket: Any = fc.filters if grp == "filters" else fc.pids
    if sub:
        bucket[key][sub] = val
    else:
        bucket[key] = val
    return True


_GLOBAL_FC = MockFC()


def drain_msp_requests(buf: bytearray, fc: MockFC) -> list[bytes]:
    """Parse one or more $M< frames from buffer; return list of response frames."""
    out: list[bytes] = []
    while True:
        try:
            i = buf.index(0x24)  # '$'
        except ValueError:
            buf.clear()
            break
        if i > 0:
            del buf[:i]
        if len(buf) < 6:
            break
        if buf[0:3] != b"$M<":
            del buf[0:1]
            continue
        size = buf[3]
        total = 3 + 1 + 1 + size + 1
        if len(buf) < total:
            break
        frame = bytes(buf[:total])
        del buf[:total]
        parsed = parse_msp_request(frame)
        if not parsed:
            continue
        cmd, payload = parsed
        resp_pl = fc.handle_msp(cmd, payload)
        out.append(encode_msp_response(cmd, resp_pl))
    return out


async def ws_handler(websocket: Any) -> None:
    fc = _GLOBAL_FC
    buf = bytearray()
    print("[SIM] client connected", websocket.remote_address)
    try:
        async for message in websocket:
            if isinstance(message, str):
                if message.startswith("SIM:GENERATE"):
                    fc.regenerate_blackbox()
                    await websocket.send("SIM:OK")
                elif message.startswith("SIM:CLI\n"):
                    body = message.split("\n", 1)[1] if "\n" in message else ""
                    n = 0
                    for ln in body.splitlines():
                        if apply_cli_line(fc, ln):
                            n += 1
                    await websocket.send(f"SIM:CLI_OK lines={n}")
                continue
            buf.extend(message)
            for resp in drain_msp_requests(buf, fc):
                await websocket.send(resp)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        print("[SIM] client disconnected")


async def main() -> None:
    host = "0.0.0.0"
    port = 5051
    print(f"[SIM] Mock FC WebSocket ws://{host}:{port}  (MSP v1 / SIM: text commands)")
    print(f"[SIM] PIDs: {_GLOBAL_FC.pids}")
    async with websockets.serve(ws_handler, host, port, max_size=2**22):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
