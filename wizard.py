# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Tuning wizard state machine (one primary change per flight)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from tuning_tree import PHASE_ORDER, PHASE_PARAMS, PARAMS, TunePhase


STATE_PATH = Path("~/flightforge/wizard_state.json").expanduser()


@dataclass
class WizardState:
    quad_name: str = "default_quad"
    phase_index: int = 0
    axis_index: int = 0  # 0 roll 1 pitch 2 yaw
    session: int = 1
    last_config_hash: str = ""
    tune_phase: str = TunePhase.FILTERS.value
    per_axis_param: str = ""
    last_cli_diff: str = ""

    def current_phase(self) -> TunePhase:
        if self.phase_index >= len(PHASE_ORDER):
            return TunePhase.DONE
        return PHASE_ORDER[self.phase_index]

    def axes_for_phase(self) -> List[str]:
        ph = self.current_phase()
        keys = PHASE_PARAMS.get(ph, [])
        if not keys:
            return ["all"]
        p0 = PARAMS.get(keys[0])
        if p0 and p0.per_axis:
            return ["roll", "pitch", "yaw"]
        return ["all"]

    def axes_for_state(self) -> List[str]:
        return self.axes_for_phase()

    def current_param_key(self) -> Optional[str]:
        ph = self.current_phase()
        keys = PHASE_PARAMS.get(ph, [])
        if not keys:
            return None
        return keys[0]

    def advance(self) -> None:
        axes = self.axes_for_phase()
        if axes[0] != "all" and self.axis_index + 1 < len(axes):
            self.axis_index += 1
            return
        self.axis_index = 0
        self.phase_index += 1
        if self.phase_index < len(PHASE_ORDER):
            self.tune_phase = PHASE_ORDER[self.phase_index].value
        else:
            self.tune_phase = TunePhase.DONE.value

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WizardState":
        return cls(
            quad_name=str(d.get("quad_name", "default_quad")),
            phase_index=int(d.get("phase_index", 0)),
            axis_index=int(d.get("axis_index", 0)),
            session=int(d.get("session", 1)),
            last_config_hash=str(d.get("last_config_hash", "")),
            tune_phase=str(d.get("tune_phase", TunePhase.FILTERS.value)),
            per_axis_param=str(d.get("per_axis_param", "")),
            last_cli_diff=str(d.get("last_cli_diff", "")),
        )


def load_state() -> WizardState:
    if STATE_PATH.is_file():
        return WizardState.from_dict(json.loads(STATE_PATH.read_text(encoding="utf-8")))
    return WizardState()


def save_state(st: WizardState) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st.to_dict(), indent=2), encoding="utf-8")


def maneuver_for_state(st: WizardState) -> Dict[str, Any]:
    from tuning_tree import MANEUVER_INSTRUCTIONS

    ph = st.current_phase()
    return dict(MANEUVER_INSTRUCTIONS.get(ph, {"name": "Fly", "detail": [], "duration": 30, "warning": None}))
