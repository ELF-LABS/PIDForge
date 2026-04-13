# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Rule-based tuning recommendations from signal metrics."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from config_parser import cli_diff, extract_pid_from_headers
from signal_analysis import SignalAnalyzer
from tuning_tree import PARAMS, PHASE_PARAMS, TunePhase
from wizard import WizardState


class Recommender:
    def __init__(self, analyzer: SignalAnalyzer, wizard: WizardState):
        self.analyzer = analyzer
        self.wizard = wizard

    def build(self) -> List[Dict[str, Any]]:
        recs: List[Dict[str, Any]] = []
        phase = self.wizard.current_phase()
        if phase == TunePhase.DONE:
            return recs
        keys = PHASE_PARAMS.get(phase, [])
        pid = extract_pid_from_headers(self.analyzer.headers)
        axes = self.wizard.axes_for_state()
        axis = axes[min(self.wizard.axis_index, len(axes) - 1)]

        for key in keys:
            tp = PARAMS.get(key)
            if not tp:
                continue
            if tp.per_axis and axis in ("roll", "pitch", "yaw"):
                sr = self.analyzer.step_response(axis)
                if not sr.get("ok"):
                    continue
                overshoot = float(sr["overshoot_pct"])
                settle = float(sr.get("settling_time_ms", 0))
                terr = float(sr.get("tracking_error_rms", 0))
                pcur, icur, dcur = pid.get(axis, (45, 80, 30))
                raw_f = self.analyzer.headers.get(f"{axis}F", self.analyzer.headers.get("feedforward_weight", 120))
                try:
                    fcur = int(float(raw_f))
                except (TypeError, ValueError):
                    fcur = 120
                cli_base = tp.cli_key.replace("{axis}", axis)  # e.g. d_roll, p_pitch
                if phase == TunePhase.P_TERM and overshoot > 20:
                    new_p = max(tp.min_val, int(pcur - tp.step_initial))
                    recs.append(
                        {
                            "priority": 2,
                            "phase": phase.name,
                            "axis": axis,
                            "param": cli_base,
                            "current": int(pcur),
                            "recommended": int(new_p),
                            "reason": (
                                f"Your {axis} axis overshoots by about {overshoot:.0f}% — the quad snaps past where "
                                f"you want it. Dropping P from {int(pcur)} to {int(new_p)} tightens the stop."
                            ),
                            "confidence": 0.82,
                            "source": "step_response_analysis",
                        }
                    )
                if phase == TunePhase.D_TERM:
                    if settle > 220 or overshoot > 25:
                        new_d = min(tp.max_val, int(dcur + tp.step_initial))
                        recs.append(
                            {
                                "priority": 2,
                                "phase": phase.name,
                                "axis": axis,
                                "param": cli_base,
                                "current": int(dcur),
                                "recommended": int(new_d),
                                "reason": (
                                    f"The {axis} stop looks sloppy or rings a long time. A bit more D ({int(dcur)}→{int(new_d)}) "
                                    "helps braking without chasing P first."
                                ),
                                "confidence": 0.7,
                                "source": "step_response_analysis",
                            }
                        )
                if phase == TunePhase.I_TERM:
                    if terr > 0.16 and overshoot < 18:
                        new_i = min(tp.max_val, int(icur + tp.step_initial))
                        recs.append(
                            {
                                "priority": 3,
                                "phase": phase.name,
                                "axis": axis,
                                "param": cli_base,
                                "current": int(icur),
                                "recommended": int(new_i),
                                "reason": (
                                    f"{axis.title()} holds attitude a little loose after moves — nudging I from {int(icur)} to "
                                    f"{int(new_i)} helps the quad remember where level is without chasing P/D."
                                ),
                                "confidence": 0.62,
                                "source": "step_response_analysis",
                            }
                        )
                    elif overshoot > 18 and terr < 0.08:
                        new_i = max(tp.min_val, int(icur - tp.step_fine))
                        recs.append(
                            {
                                "priority": 3,
                                "phase": phase.name,
                                "axis": axis,
                                "param": cli_base,
                                "current": int(icur),
                                "recommended": int(new_i),
                                "reason": (
                                    f"{axis.title()} is bouncing around level — I may be fighting itself. Try {int(icur)}→{int(new_i)} "
                                    "after confirming no wind-up from P."
                                ),
                                "confidence": 0.55,
                                "source": "step_response_analysis",
                            }
                        )
                if phase == TunePhase.FEEDFORWARD:
                    rise = float(sr.get("rise_time_ms", 0))
                    if rise > 95 and overshoot < 15:
                        new_f = min(tp.max_val, int(fcur + tp.step_initial))
                        recs.append(
                            {
                                "priority": 3,
                                "phase": phase.name,
                                "axis": axis,
                                "param": cli_base,
                                "current": int(fcur),
                                "recommended": int(new_f),
                                "reason": (
                                    f"{axis.title()} feels lazy off the sticks (slow rise). Feedforward {int(fcur)}→{int(new_f)} "
                                    "adds predictive kick without cranking P."
                                ),
                                "confidence": 0.58,
                                "source": "step_response_analysis",
                            }
                        )
            else:
                if phase == TunePhase.FILTERS:
                    fft = self.analyzer.noise_fft("roll")
                    if fft.get("ok"):
                        peaks = fft.get("peaks") or []
                        big = [p for p in peaks if p.get("db", -999) > 6]
                        if big and not any(r.get("param") == "dyn_notch_count" for r in recs):
                            recs.append(
                                {
                                    "priority": 3,
                                    "phase": phase.name,
                                    "axis": "all",
                                    "param": "dyn_notch_count",
                                    "current": 1,
                                    "recommended": 2,
                                    "reason": "Noise peaks stand out in the gyro spectrum — a second dynamic notch can track resonances.",
                                    "confidence": 0.55,
                                    "source": "noise_fft",
                                }
                            )
                    break
                if phase == TunePhase.ANTI_GRAVITY:
                    ag = int(float(self.analyzer.headers.get("anti_gravity_gain", 5000)))
                    pw = self.analyzer.propwash_analysis()
                    if pw.get("ok") and float(pw.get("propwash_magnitude", 0)) > 1e-6:
                        new_ag = min(10000, ag + 500)
                        recs.append(
                            {
                                "priority": 3,
                                "phase": phase.name,
                                "axis": "all",
                                "param": "anti_gravity_gain",
                                "current": ag,
                                "recommended": new_ag,
                                "reason": (
                                    "Throttle chops show pitch energy during recoveries — a touch more anti_gravity_gain "
                                    f"keeps the nose level when you cut power ({ag}→{new_ag})."
                                ),
                                "confidence": 0.52,
                                "source": "propwash_heuristic",
                            }
                        )
                if phase == TunePhase.THRUST_LINEAR:
                    tl = int(float(self.analyzer.headers.get("thrust_linear", 0)))
                    motors = self.analyzer.motor_analysis()
                    if motors.get("ok") and float(motors.get("imbalance_pct", 0)) < 12 and tl < 80:
                        new_tl = min(150, tl + int(tp.step_initial))
                        recs.append(
                            {
                                "priority": 4,
                                "phase": phase.name,
                                "axis": "all",
                                "param": "thrust_linear",
                                "current": tl,
                                "recommended": new_tl,
                                "reason": (
                                    "Motors look balanced — if throttle feels mushy at the bottom but sharp up high, "
                                    f"thrust_linear {tl}→{new_tl} evens out the curve."
                                ),
                                "confidence": 0.45,
                                "source": "motor_balance_heuristic",
                            }
                        )
                if phase == TunePhase.VBAT_COMP:
                    bat = self.analyzer.battery_analysis()
                    if bat.get("ok"):
                        sag = float(bat.get("sag_volts_per_cell", 0))
                        vb = int(float(self.analyzer.headers.get("vbat_sag_compensation", 100)))
                        if sag > 0.45 and vb < 180:
                            new_v = min(200, vb + 15)
                            recs.append(
                                {
                                    "priority": 3,
                                    "phase": phase.name,
                                    "axis": "all",
                                    "param": "vbat_sag_compensation",
                                    "current": vb,
                                    "recommended": new_v,
                                    "reason": (
                                        f"Pack sags about {sag:.2f} V per cell under load — bumping vbat_sag_compensation "
                                        f"{vb}→{new_v} keeps PID feel steadier as voltage drops."
                                    ),
                                    "confidence": 0.6,
                                    "source": "battery_analysis",
                                }
                            )
                if phase == TunePhase.TPA:
                    sat = self.analyzer.motor_analysis()
                    fft = self.analyzer.noise_fft("roll")
                    tpa = int(float(self.analyzer.headers.get("tpa_rate", 65)))
                    added = False
                    if sat.get("ok") and float(sat.get("saturation_pct", 0)) > 4 and tpa < 85:
                        new_tpa = min(100, tpa + int(tp.step_initial))
                        recs.append(
                            {
                                "priority": 3,
                                "phase": phase.name,
                                "axis": "all",
                                "param": "tpa_rate",
                                "current": tpa,
                                "recommended": new_tpa,
                                "reason": (
                                    "Motors are brushing the ceiling while gyro noise stays hot — a little more TPA "
                                    f"softens high-throttle P without touching hover tune ({tpa}→{new_tpa})."
                                ),
                                "confidence": 0.5,
                                "source": "motor_saturation_heuristic",
                            }
                        )
                        added = True
                    if not added and fft.get("ok"):
                        peaks = fft.get("peaks") or []
                        if peaks and tpa < 80:
                            hi = [p for p in peaks if p.get("hz", 0) > 180]
                            if hi:
                                new_tpa = min(100, tpa + int(tp.step_fine))
                                recs.append(
                                    {
                                        "priority": 4,
                                        "phase": phase.name,
                                        "axis": "all",
                                        "param": "tpa_rate",
                                        "current": tpa,
                                        "recommended": new_tpa,
                                        "reason": (
                                            "High-band noise spikes line up with wide-open throttle — nudging TPA "
                                            f"{tpa}→{new_tpa} targets oscillation only up top."
                                        ),
                                        "confidence": 0.48,
                                        "source": "noise_fft",
                                    }
                                )
                if phase == TunePhase.ITERM_RELAX:
                    bounce = False
                    for ax in ("roll", "pitch"):
                        sr_ax = self.analyzer.step_response(ax)
                        if sr_ax.get("ok"):
                            if float(sr_ax["overshoot_pct"]) > 16 and float(sr_ax.get("settling_time_ms", 0)) > 210:
                                bounce = True
                    if bounce and not any(r.get("param") == "iterm_relax_cutoff" for r in recs):
                        cur_rel = int(float(self.analyzer.headers.get("iterm_relax_cutoff", 15)))
                        new_rel = min(50, cur_rel + 5)
                        recs.append(
                            {
                                "priority": 3,
                                "phase": phase.name,
                                "axis": "all",
                                "param": "iterm_relax_cutoff",
                                "current": cur_rel,
                                "recommended": new_rel,
                                "reason": (
                                    "After hard stops the quad still wants to bounce — raising iterm_relax_cutoff lets I unwind "
                                    f"faster during quick reversals ({cur_rel}→{new_rel})."
                                ),
                                "confidence": 0.54,
                                "source": "step_response_analysis",
                            }
                        )
                if phase == TunePhase.DYNAMIC_IDLE:
                    idle = int(float(self.analyzer.headers.get("dshot_idle_value", 550)))
                    pw = self.analyzer.propwash_analysis()
                    if pw.get("ok") and float(pw.get("propwash_magnitude", 0)) > 5e-7:
                        new_idle = min(1000, idle + int(tp.step_initial))
                        recs.append(
                            {
                                "priority": 3,
                                "phase": phase.name,
                                "axis": "all",
                                "param": "dshot_idle_value",
                                "current": idle,
                                "recommended": new_idle,
                                "reason": (
                                    "Low-throttle recoveries still wobble — dynamic idle (dshot_idle_value) "
                                    f"{idle}→{new_idle} keeps props authoritative when you chop throttle."
                                ),
                                "confidence": 0.55,
                                "source": "propwash_heuristic",
                            }
                        )
        return sorted(recs, key=lambda r: r["priority"])

    def explain(self, rec: Dict[str, Any]) -> str:
        return str(rec.get("reason", ""))

    def cli_diff(self, recs: Optional[List[Dict[str, Any]]] = None) -> str:
        recs = recs or self.build()
        updates = {r["param"]: r["recommended"] for r in recs if "param" in r}
        if not updates:
            return "# No automatic CLI changes — log may be missing gyro/P traces.\n"
        return cli_diff(updates, comment="FlightForge recommendation")
