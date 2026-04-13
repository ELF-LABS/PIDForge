# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Minimal Betaflight MSP v1 framing (no LLM / no network)."""

from __future__ import annotations

import struct
import time
from typing import Optional, Tuple

# From betaflight msp_protocol.h (subset)
MSP_API_VERSION = 1
MSP_FC_VARIANT = 2
MSP_FC_VERSION = 3
MSP_BOARD_INFO = 4
MSP_BUILD_INFO = 5
MSP_NAME = 10
MSP_BLACKBOX_CONFIG = 80
MSP_SET_BLACKBOX_CONFIG = 81
MSP_OSD_CONFIG = 84
MSP_SET_OSD_CONFIG = 85
MSP_VTX_CONFIG = 88
MSP_SET_VTX_CONFIG = 89
MSP_ADVANCED_CONFIG = 90
MSP_SET_ADVANCED_CONFIG = 91
MSP_STATUS = 101
MSP_MOTOR_CONFIG = 131
MSP_DATAFLASH_SUMMARY = 70
MSP_EEPROM_WRITE = 250


def _checksum(data: bytes) -> int:
    c = 0
    for b in data:
        c ^= b
    return c


def encode_request(cmd: int, payload: bytes = b"") -> bytes:
    if len(payload) > 255:
        raise ValueError("MSP v1 payload too large")
    body = bytes([len(payload), cmd & 0xFF]) + payload
    return b"$M<" + body + bytes([_checksum(body)])


def parse_msp_frame(frame: bytes) -> Optional[Tuple[int, bytes]]:
    """Parse a single frame that begins with ``$M>``."""
    if len(frame) < 6 or frame[:3] != b"$M>":
        return None
    size = frame[3]
    cmd = frame[4]
    if len(frame) < 5 + size + 1:
        return None
    payload = frame[5 : 5 + size]
    crc = frame[5 + size]
    expect = _checksum(bytes([size, cmd]) + payload)
    if crc != expect:
        return None
    return cmd, payload


class MSPPort:
    """Blocking MSP v1 over serial."""

    def __init__(self, ser, read_timeout: float = 0.05) -> None:
        self.ser = ser
        self.read_timeout = read_timeout

    def request(self, cmd: int, payload: bytes = b"", retries: int = 3) -> bytes:
        last_err: Optional[Exception] = None
        for _ in range(retries):
            self.ser.reset_input_buffer()
            self.ser.write(encode_request(cmd, payload))
            self.ser.flush()
            deadline = time.monotonic() + 2.0
            acc = bytearray()
            while time.monotonic() < deadline:
                chunk = self.ser.read(512)
                if not chunk:
                    time.sleep(self.read_timeout)
                    continue
                acc.extend(chunk)
                while True:
                    try:
                        i = acc.index(b"$M>")
                    except ValueError:
                        if len(acc) > 8192:
                            del acc[:-4096]
                        break
                    if len(acc) - i < 5:
                        break
                    size = acc[i + 3]
                    total = 3 + 1 + 1 + size + 1
                    if len(acc) - i < total:
                        break
                    frame = bytes(acc[i : i + total])
                    parsed = parse_msp_frame(frame)
                    del acc[: i + total]
                    if parsed is None:
                        last_err = ValueError("bad MSP frame")
                        break
                    cmd_r, body = parsed
                    if cmd_r != cmd:
                        continue
                    return body
            last_err = last_err or TimeoutError("MSP response timeout")
        if last_err:
            raise last_err
        raise TimeoutError("MSP response timeout")

    def read_u8(self, cmd: int) -> int:
        pl = self.request(cmd)
        return pl[0] if pl else 0

    def read_u16_le(self, data: bytes, off: int) -> int:
        return struct.unpack_from("<H", data, off)[0]

    def read_u32_le(self, data: bytes, off: int) -> int:
        return struct.unpack_from("<I", data, off)[0]
