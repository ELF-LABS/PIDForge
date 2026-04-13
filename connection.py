# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""MSP serial connection and flight controller detection."""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional

import serial
import serial.tools.list_ports

from blackbox_config import (
    BlackboxMspState,
    DEBUG_MULTI_GYRO_SCALED,
    optimal_msp_blackbox_payload,
    parse_blackbox_msp_payload,
)
from msp import (
    MSP_ADVANCED_CONFIG,
    MSP_API_VERSION,
    MSP_BLACKBOX_CONFIG,
    MSP_BOARD_INFO,
    MSP_FC_VARIANT,
    MSP_FC_VERSION,
    MSP_MOTOR_CONFIG,
    MSP_NAME,
    MSP_SET_ADVANCED_CONFIG,
    MSP_SET_BLACKBOX_CONFIG,
    MSP_STATUS,
    MSPPort,
)


class FCConnection:
    """MSP serial connection to Betaflight FC."""

    def __init__(self, port: Optional[str] = None, baudrate: int = 115200) -> None:
        self.port_path = port
        self.baudrate = baudrate
        self._ser: Optional[serial.Serial] = None
        self._msp: Optional[MSPPort] = None

    def open(self, port: Optional[str] = None) -> None:
        p = port or self.port_path
        if not p:
            raise ValueError("serial port required")
        self._ser = serial.Serial(p, self.baudrate, timeout=0.05, write_timeout=1.0)
        self._msp = MSPPort(self._ser)
        self.port_path = p

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None
        self._msp = None

    @property
    def msp(self) -> MSPPort:
        if not self._msp:
            raise RuntimeError("connection not open")
        return self._msp

    def detect(self, port: Optional[str] = None) -> Dict[str, Any]:
        """Auto-detect FC: try MSP on given port or first Betaflight-looking USB serial."""
        candidates: List[str] = []
        if port:
            candidates.append(port)
        else:
            for p in serial.tools.list_ports.comports():
                desc = (p.description or "").lower()
                hwid = (p.hwid or "").lower()
                if any(x in desc for x in ("betaflight", "stm", "cp210", "ch340", "blackbox", "flight")):
                    candidates.append(p.device)
                elif "usb" in hwid:
                    candidates.append(p.device)
            if not candidates:
                candidates = [p.device for p in serial.tools.list_ports.comports()]
        last_err: Optional[Exception] = None
        for dev in candidates:
            try:
                self.close()
                self.open(dev)
                api = self.msp.request(MSP_API_VERSION)
                if len(api) < 3:
                    continue
                stat = self.msp.request(MSP_STATUS)
                variant = self.msp.request(MSP_FC_VARIANT)
                version = self.msp.request(MSP_FC_VERSION)
                board = self.msp.request(MSP_BOARD_INFO)
                name_pl = self.msp.request(MSP_NAME)
                return {
                    "port": dev,
                    "api": {"major": api[0], "minor": api[1], "protocol": api[2]},
                    "status": stat.hex() if stat else "",
                    "fc_variant": variant.decode("utf-8", "replace").rstrip("\0"),
                    "fc_version": version.decode("utf-8", "replace").rstrip("\0"),
                    "board": board[:20].hex() if board else "",
                    "craft_name": name_pl.decode("utf-8", "replace").rstrip("\0") if name_pl else "",
                }
            except (serial.SerialException, OSError, TimeoutError, ValueError) as e:
                last_err = e
                continue
        raise RuntimeError(f"No Betaflight MSP FC found: {last_err}")

    def read_blackbox_config(self) -> Dict[str, Any]:
        pl = self.msp.request(MSP_BLACKBOX_CONFIG)
        st = parse_blackbox_msp_payload(pl)
        adv = self.msp.request(MSP_ADVANCED_CONFIG)
        # MSP_ADVANCED_CONFIG: debug_mode at byte 18 (after checkOverflow), DEBUG_COUNT at 19
        debug_mode = adv[18] if len(adv) > 18 else 0
        return {
            "msp": st,
            "debug_mode": debug_mode,
            "debug_mode_name": "GYRO_SCALED" if debug_mode == DEBUG_MULTI_GYRO_SCALED else f"mode_{debug_mode}",
        }

    def flash_blackbox_config(self, confirmed: bool) -> bool:
        """Write blackbox MSP settings. ``confirmed`` must be True (caller shows erase warning)."""
        if not confirmed:
            print("[WARN] flash_blackbox_config: user did not confirm; skipping.")
            return False
        payload = optimal_msp_blackbox_payload()
        self.msp.request(MSP_SET_BLACKBOX_CONFIG, payload)
        return True

    def flash_debug_mode_gyro_scaled(self, confirmed: bool) -> bool:
        """Set debug mode via MSP_SET_ADVANCED_CONFIG (requires full payload echo)."""
        if not confirmed:
            return False
        adv = self.msp.request(MSP_ADVANCED_CONFIG)
        if len(adv) < 20:
            print("[ERROR] MSP_ADVANCED_CONFIG payload too short for this firmware.")
            return False
        lst = bytearray(adv)
        lst[18] = DEBUG_MULTI_GYRO_SCALED
        self.msp.request(MSP_SET_ADVANCED_CONFIG, bytes(lst))
        return True

    def read_motor_config_snippet(self) -> Dict[str, Any]:
        pl = self.msp.request(MSP_MOTOR_CONFIG)
        if len(pl) < 6:
            return {}
        min_throttle, max_throttle, min_command, motor_count = struct.unpack_from("<HHHB", pl, 0)
        return {
            "min_throttle": min_throttle,
            "max_throttle": max_throttle,
            "motor_count": motor_count,
        }
