# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""ESC / motor protocol hints from MSP (first-connection helper)."""

from __future__ import annotations

from typing import Any, Dict

from msp import MSP_ADVANCED_CONFIG


def detect(connection: Any) -> Dict[str, Any]:
    """Read motor protocol from MSP_ADVANCED_CONFIG (byte 3 = motorProtocol)."""
    adv = connection.msp.request(MSP_ADVANCED_CONFIG)
    protocol = int(adv[3]) if len(adv) > 3 else 0
    # betaflight motorProtocol_e: see serial_msp (DSHOT150=5 ... DSHOT1200=11)
    proto_name = {
        0: "PWM",
        1: "ONESHOT125",
        2: "ONESHOT42",
        3: "MULTISHOT",
        4: "BRUSHED",
        5: "DSHOT150",
        6: "DSHOT300",
        7: "DSHOT600",
        8: "PROSHOT1000",
        9: "DISABLED",
    }.get(protocol, f"UNKNOWN({protocol})")
    dshot = "DSHOT" in proto_name
    return {
        "motor_protocol": proto_name,
        "bidirectional_capable": dshot,
        "firmware_guess": "Betaflight",
    }


def needs_calibration(esc_info: Dict[str, Any]) -> bool:
    return not esc_info.get("bidirectional_capable", False)


def verify_bidirectional(esc_info: Dict[str, Any]) -> bool:
    return bool(esc_info.get("bidirectional_capable"))


def verify_motor_poles(connection: Any, expected_poles: int = 14) -> Dict[str, Any]:
    _ = connection
    return {"expected": expected_poles, "warning": "Confirm motor pole count in ESC config matches your motors."}
