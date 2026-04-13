# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Betaflight version strings from BFL headers + CLI name mapping."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

SUPPORTED_FAMILIES = ("4.3", "4.4", "4.5", "2025.12")

# CLI renames (minimal set for wizard)
PARAM_ALIASES: Dict[str, Dict[str, str]] = {
    "4.3": {},
    "4.4": {},
    "4.5": {},
    "2025.12": {},
}


def detect_version(headers: Dict[str, Any]) -> str:
    """Return a coarse firmware label from blackbox headers."""
    raw = str(headers.get("Firmware revision", headers.get(" firmware revision", ""))).strip()
    if not raw:
        return "unknown"
    low = raw.lower()
    for tag in ("2025.12", "4.5", "4.4", "4.3"):
        if tag in low:
            return tag
    m = re.search(r"(\d+\.\d+\.\d+)", raw)
    if m:
        ver = m.group(1)
        if ver.startswith("4.3"):
            return "4.3"
        if ver.startswith("4.4"):
            return "4.4"
        if ver.startswith("4.5"):
            return "4.5"
    if "betaflight" in low:
        return "unknown_bf"
    return "unknown"


def validate_log(headers: Dict[str, Any]) -> Tuple[bool, List[str]]:
    ver = detect_version(headers)
    warns = []
    if ver == "unknown":
        warns.append("Could not detect Betaflight version from log header; defaults may not match your FC.")
    elif ver not in SUPPORTED_FAMILIES:
        warns.append(f"Version label {ver!r} is outside tested set {SUPPORTED_FAMILIES}; proceeding with generic defaults.")
    return len(warns) == 0, warns


def get_defaults(version: str) -> Dict[str, Any]:
    """Baseline PID/filter defaults per generation (approximate for wizard starting points)."""
    _ = version
    return {
        "gyro_lpf1_static_hz": 150,
        "dterm_lpf1_static_hz": 100,
        "dyn_notch_count": 1,
        "dyn_notch_q": 500,
        "roll_pid": (45, 80, 30),
        "pitch_pid": (47, 84, 32),
        "yaw_pid": (45, 80, 0),
        "anti_gravity_gain": 5000,
        "iterm_relax_cutoff": 15,
        "feedforward_roll": 120,
        "feedforward_pitch": 120,
        "feedforward_yaw": 100,
        "thrust_linear": 0,
        "vbat_sag_compensation": 100,
        "tpa_rate": 65,
        "tpa_breakpoint": 1350,
        "dshot_idle_value": 550,
    }


def get_param_mapping(version: str) -> Dict[str, str]:
    """Map logical keys to CLI keys for a firmware generation."""
    base = {
        "gyro_lpf1_hz": "gyro_lpf1_static_hz",
        "dterm_lpf1_hz": "dterm_lpf1_static_hz",
        "dyn_notch_count": "dyn_notch_count",
        "dyn_notch_q": "dyn_notch_q",
        "anti_gravity_gain": "anti_gravity_gain",
        "iterm_relax_cutoff": "iterm_relax_cutoff",
        "thrust_linear": "thrust_linear",
        "vbat_sag_compensation": "vbat_sag_compensation",
        "tpa_rate": "tpa_rate",
        "tpa_breakpoint": "tpa_breakpoint",
        "dshot_idle_value": "dshot_idle_value",
    }
    aliases = PARAM_ALIASES.get(version, {})
    return {k: aliases.get(v, v) for k, v in base.items()}


def migration_notes(from_ver: str, to_ver: str) -> str:
    if from_ver == to_ver:
        return "Same generation; no migration summary."
    return (
        f"Upgrading from {from_ver} to {to_ver}: review Betaflight release notes for renamed CLI keys, "
        "RPM filter defaults, and feedforward / DMIN changes. Re-run a validation flight after flashing."
    )
