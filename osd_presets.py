# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""OSD layout presets (metadata + MSP hook placeholders)."""

from __future__ import annotations

from typing import Any, Dict, List

from msp import MSP_OSD_CONFIG


PRESETS: Dict[str, Dict[str, Any]] = {
    "racing": {"desc": "Minimal — timer, battery, RSSI", "items": ["TIMER", "BATTERY", "RSSI"]},
    "freestyle": {"desc": "Battery, altitude, timer, throttle, warnings", "items": ["BATTERY", "ALT", "TIMER", "THROTTLE", "WARN"]},
    "cinematic": {"desc": "Ultra minimal — battery only", "items": ["BATTERY"]},
    "analog": {"desc": "Full stats for analog goggles", "items": ["FULL"]},
    "digital": {"desc": "HD canvas-friendly layout", "items": ["BATTERY", "TIMER", "WARN"]},
}


def list_presets() -> List[str]:
    return sorted(PRESETS.keys())


def backup_current(connection: Any) -> bytes:
    return connection.msp.request(MSP_OSD_CONFIG)


def apply_preset(name: str, connection: Any, confirmed: bool) -> bool:
    if not confirmed:
        print("[WARN] OSD apply skipped (needs confirmation).")
        return False
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name}")
    _ = backup_current(connection)
    print("[INFO] MVP: capture MSP_OSD_CONFIG and edit in Configurator; automated SET not shipped yet.")
    return False
