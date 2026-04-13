# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""VTX table helpers (CLI text; MSP read for detection)."""

from __future__ import annotations

from typing import Any, Dict

from msp import MSP_VTX_CONFIG


class VTxConfig:
    REGION_TABLES = {
        "US_FCC": {"bands": ["A", "B", "E", "F", "R"], "max_power_mw": 600},
        "EU_CE": {"bands": ["A", "B", "E"], "max_power_mw": 25},
        "AU_ACMA": {"bands": ["A", "B", "E", "F", "R"], "max_power_mw": 25},
    }

    def detect_vtx(self, connection: Any) -> Dict[str, Any]:
        pl = connection.msp.request(MSP_VTX_CONFIG)
        return {"raw_len": len(pl), "note": "Decode per BF MSP_VTX_CONFIG layout for your API level."}

    def detect_region(self, manual: str = "US_FCC") -> str:
        return manual

    def generate_vtxtable(self, vtx_type: str, region: str) -> str:
        tab = self.REGION_TABLES.get(region, self.REGION_TABLES["US_FCC"])
        lines = [
            f"# VTX preset for {vtx_type} / {region}",
            "# Review legal limits before pasting.",
            f"# bands={tab['bands']} max_mw={tab['max_power_mw']}",
            "vtxtable bands 5",
            "vtxtable channels 8",
            "# ... populate channels for your hardware — template only",
        ]
        return "\n".join(lines) + "\n"

    def apply(self, connection: Any) -> bool:
        _ = connection
        print("[WARN] VTx MSP apply not implemented in MVP; use generated CLI in Betaflight Configurator.")
        return False
