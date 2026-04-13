# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Flight quality score (0–100) from SignalAnalyzer-style dicts — stdlib only."""

from __future__ import annotations

from typing import Any, Dict, Optional


def _step_axis(step: Dict[str, Any]) -> Optional[Dict[str, float]]:
    if not step or not step.get("ok"):
        return None
    overshoot_frac = float(step.get("overshoot_pct", 0.0)) / 100.0
    settling_s = float(step.get("settling_time_ms", 100.0)) / 1000.0
    te = float(step.get("tracking_error_rms", 0.2))
    tracking_quality = max(0.0, min(1.0, 1.0 - min(te * 3.0, 1.0)))
    return {
        "tracking_quality": tracking_quality,
        "overshoot": overshoot_frac,
        "settling_time": settling_s,
    }


def _fft_noise(fft_roll: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not fft_roll or not fft_roll.get("ok"):
        return None
    nf_db = float(fft_roll.get("noise_floor_db", 0.0))
    # Map typical gyro noise floor dB-ish metric to 0–100 burden (higher = worse).
    noise_level = max(0.0, min(100.0, 40.0 + nf_db * 0.8))
    peaks_out = []
    for p in fft_roll.get("peaks") or []:
        peaks_out.append({"hz": p.get("hz", 0.0), "magnitude": float(p.get("db", 0.0))})
    return {"overall_noise": noise_level, "peaks": peaks_out}


def _motor_output(motor: Dict[str, Any]) -> Optional[Dict[str, float]]:
    if not motor or not motor.get("ok"):
        return None
    imb = float(motor.get("imbalance_pct", 50.0))
    balance = max(0.0, min(1.0, 1.0 - imb / 150.0))
    return {"motor_balance": balance}


def score_flight(
    step_response: Dict[str, Any],
    fft_noise: Optional[Dict[str, Any]],
    motor_output: Optional[Dict[str, Any]],
) -> float:
    """Compute 0–100 composite score from structured analysis fragments."""
    scores: Dict[str, float] = {}

    for axis in ("roll", "pitch", "yaw"):
        st = _step_axis(step_response.get(axis) or step_response.get(f"step_{axis}") or {})
        if st is None:
            continue
        scores[f"{axis}_tracking"] = st["tracking_quality"] * 100.0
        scores[f"{axis}_overshoot"] = max(0.0, 100.0 - st["overshoot"] * 200.0)
        scores[f"{axis}_settling"] = max(0.0, 100.0 - min(st["settling_time"] * 400.0, 80.0))

    if fft_noise:
        noise_level = float(fft_noise.get("overall_noise", 50.0))
        scores["noise"] = max(0.0, 100.0 - noise_level)
        peaks = fft_noise.get("peaks") or []
        resonance_penalty = len([p for p in peaks if float(p.get("magnitude", 0.0)) > 18.0]) * 10.0
        scores["resonance"] = max(0.0, 100.0 - resonance_penalty)
    if motor_output:
        scores["motor_balance"] = float(motor_output.get("motor_balance", 0.5)) * 100.0

    weights = {
        "roll_tracking": 0.12,
        "pitch_tracking": 0.12,
        "yaw_tracking": 0.08,
        "roll_overshoot": 0.10,
        "pitch_overshoot": 0.10,
        "yaw_overshoot": 0.06,
        "roll_settling": 0.06,
        "pitch_settling": 0.06,
        "yaw_settling": 0.04,
        "noise": 0.12,
        "resonance": 0.08,
        "motor_balance": 0.06,
    }
    total_w = 0.0
    acc = 0.0
    for k, w in weights.items():
        if k in scores:
            acc += scores[k] * w
            total_w += w
    if total_w <= 0.0:
        return 50.0
    return round(acc / total_w, 1)


def score_from_full_report(full_report: Dict[str, Any]) -> float:
    """Convenience: use ``full_analysis()`` output from ``SignalAnalyzer``."""
    parts = full_report.get("parts") or full_report
    step_response: Dict[str, Any] = {}
    for ax in ("roll", "pitch", "yaw"):
        key = f"step_{ax}"
        if key in parts:
            step_response[ax] = parts[key]
    fft_n = _fft_noise(parts.get("fft_roll") or {})
    mot = _motor_output(parts.get("motor") or {})
    return score_flight(step_response, fft_n, mot)


def compare_flights(current_score: float, previous_score: float) -> Dict[str, Any]:
    delta = float(current_score) - float(previous_score)
    if delta > 5.0:
        verdict = "IMPROVED"
    elif delta > -2.0:
        verdict = "STABLE"
    else:
        verdict = "REGRESSED"
    return {"delta": delta, "verdict": verdict}
