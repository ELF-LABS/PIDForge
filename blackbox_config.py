# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Blackbox logging targets and MSP field masks (Betaflight)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

# blackbox.h
BLACKBOX_DEVICE_NONE = 0
BLACKBOX_DEVICE_FLASH = 1
BLACKBOX_DEVICE_SDCARD = 2
BLACKBOX_DEVICE_SERIAL = 3

# blackbox.h rate enum
BLACKBOX_RATE_ONE = 0
BLACKBOX_RATE_HALF = 1
BLACKBOX_RATE_QUARTER = 2
BLACKBOX_RATE_8TH = 3
BLACKBOX_RATE_16TH = 4

# debug.h — DEBUG_MULTI_GYRO_SCALED (noise / scaled gyro for analysis)
DEBUG_MULTI_GYRO_SCALED = 50

OPTIMAL_BLACKBOX: Dict[str, Any] = {
    "blackbox_sample_rate": "1/4",
    "blackbox_device": "SDCARD",
    "debug_mode": "GYRO_SCALED",
    "blackbox_disable_pids": "OFF",
    "blackbox_disable_setpoint": "OFF",
    "blackbox_disable_gyro": "OFF",
    "blackbox_disable_motors": "OFF",
    "blackbox_disable_bat": "OFF",
}


def fields_enabled_mask() -> int:
    """Return ``fields_disabled_mask`` value: 0 means log PID, RC, setpoint, gyro, motors, battery, debug."""
    return 0


def optimal_msp_blackbox_payload(p_ratio: int = 16, sample_rate: int = BLACKBOX_RATE_QUARTER) -> bytes:
    """Build MSP_SET_BLACKBOX_CONFIG payload (device, rate_num, rate_denom, p_ratio le, sample_rate, fields_mask)."""
    import struct

    device = BLACKBOX_DEVICE_SDCARD
    rate_num = 1
    rate_denom = 4
    fields = fields_enabled_mask()
    return struct.pack("<BBBHBI", device, rate_num, rate_denom, p_ratio, sample_rate, fields)


@dataclass
class BlackboxMspState:
    supported: bool
    device: int
    rate_num: int
    rate_denom: int
    p_ratio: int
    sample_rate: int
    fields_disabled_mask: int


def parse_blackbox_msp_payload(payload: bytes) -> BlackboxMspState:
    import struct

    if len(payload) < 4:
        return BlackboxMspState(False, 0, 0, 0, 0, 0, 0xFFFFFFFF)
    supported = payload[0] != 0
    device = payload[1]
    rate_num = payload[2]
    rate_denom = payload[3]
    p_ratio = 0
    sample_rate = BLACKBOX_RATE_QUARTER
    mask = 0
    if len(payload) >= 6:
        p_ratio = struct.unpack_from("<H", payload, 4)[0]
    if len(payload) >= 7:
        sample_rate = payload[6]
    if len(payload) >= 11:
        mask = struct.unpack_from("<I", payload, 7)[0]
    return BlackboxMspState(supported, device, rate_num, rate_denom, p_ratio, sample_rate, mask)


def human_device(dev: int) -> str:
    return {BLACKBOX_DEVICE_NONE: "NONE", BLACKBOX_DEVICE_FLASH: "FLASH", BLACKBOX_DEVICE_SDCARD: "SDCARD"}.get(
        dev, f"UNKNOWN({dev})"
    )


def human_sample_rate(sr: int) -> str:
    m = {
        BLACKBOX_RATE_ONE: "1/1",
        BLACKBOX_RATE_HALF: "1/2",
        BLACKBOX_RATE_QUARTER: "1/4",
        BLACKBOX_RATE_8TH: "1/8",
        BLACKBOX_RATE_16TH: "1/16",
    }
    return m.get(sr, f"enum({sr})")


def compare_to_optimal(state: BlackboxMspState) -> Dict[str, Any]:
    """Return dict of mismatches vs OPTIMAL_BLACKBOX (best-effort; debug checked separately)."""
    issues = []
    if state.device != BLACKBOX_DEVICE_SDCARD:
        issues.append(f"device is {human_device(state.device)}, want SDCARD")
    if state.sample_rate != BLACKBOX_RATE_QUARTER:
        issues.append(f"sample_rate is {human_sample_rate(state.sample_rate)}, want 1/4")
    if state.fields_disabled_mask != 0:
        issues.append(f"fields_disabled_mask is 0x{state.fields_disabled_mask:08x}, want 0 (all fields on)")
    return {"ok": len(issues) == 0, "issues": issues, "state": state}
