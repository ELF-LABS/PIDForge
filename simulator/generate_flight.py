# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Synthetic Betaflight-style CSV — quality depends on MockFC PID / filter state."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any, Dict, Tuple

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from mock_fc import MockFC


def _pid_quality(val: float, lo: float, hi: float) -> float:
    if lo <= val <= hi:
        return 1.0
    dist = min(abs(val - lo), abs(val - hi))
    return max(0.15, 1.0 - dist * 0.04)


def flight_quality(fc: "MockFC") -> float:
    """Scalar 0..1 — higher is a better-tuned quad for roll/pitch rate."""
    pr = fc.pids["roll"]["P"]
    pp = fc.pids["pitch"]["P"]
    dr = fc.pids["roll"]["D"]
    dp = fc.pids["pitch"]["D"]
    p_q = (_pid_quality(pr, 40, 50) + _pid_quality(pp, 42, 52)) / 2.0
    d_q = (_pid_quality(dr, 28, 40) + _pid_quality(dp, 30, 42)) / 2.0
    dlpf = float(fc.filters.get("dterm_lpf1", 150))
    f_q = 1.0 if 120 <= dlpf <= 220 else 0.65
    return max(0.05, min(1.0, (p_q + d_q + f_q) / 3.0))


def build_headers(fc: "MockFC") -> Dict[str, Any]:
    r, p, y = fc.pids["roll"], fc.pids["pitch"], fc.pids["yaw"]
    return {
        "Firmware revision": fc.fc_info.get("firmware", "Betaflight 4.5.0 (SIM)"),
        "rollPID": f"{int(r['P'])},{int(r['I'])},{int(r['D'])}",
        "pitchPID": f"{int(p['P'])},{int(p['I'])},{int(p['D'])}",
        "yawPID": f"{int(y['P'])},{int(y['I'])},{int(y['D'])}",
        "vbatcellcount": "4",
        "dyn_notch_count": "2",
        "dterm_lpf1_static_hz": str(int(fc.filters.get("dterm_lpf1", 150))),
    }


def _axis_targets(axis: str) -> tuple[float, float, float]:
    """Sweet-spot P, I, D per axis for scoring (approx BF 5-inch freestyle-ish)."""
    if axis == "roll":
        return 46.0, 85.0, 35.0
    if axis == "pitch":
        return 48.0, 88.0, 37.0
    return 45.0, 90.0, 0.0


def _synth_axis(
    t: np.ndarray,
    fs: float,
    axis_idx: int,
    axis: str,
    P: float,
    I: float,
    D: float,
    quality: float,
    rng: np.random.Generator,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return setpoint, gyro, axisP, axisD, debug for one axis (rate-ish units)."""
    pt, it, dtgt = _axis_targets(axis)
    mistune = abs(P - pt) * 0.55 + abs(I - it) * 0.12 + abs(D - dtgt) * 0.42
    bad = max(0.08, 1.05 - float(quality))

    stick = 120.0 * np.sin(2.0 * np.pi * 0.35 * t)
    stick += 280.0 * (np.sin(2.0 * np.pi * 0.08 * t) ** 3)
    stick += rng.normal(0.0, 3.5, size=t.shape)

    noise_amp = (18.0 + mistune * 6.0 + bad * 55.0) * (0.55 + bad)
    osc_amp = (mistune * 1.4 + bad * 38.0) * (0.4 + bad)
    f_osc = 165.0 + axis_idx * 14.0 + rng.normal(0, 5.0)
    prop = np.sin(2.0 * np.pi * (188.0 + axis_idx * 6) * t) * (12.0 + mistune * 0.35 + bad * 42.0)

    gyro = np.zeros_like(t, dtype=np.float64)
    int_e = 0.0
    prev_e = 0.0
    dt = 1.0 / fs
    for k in range(len(t)):
        sp = stick[k]
        if k == 0:
            g = sp * 0.35
        else:
            err = sp - gyro[k - 1]
            int_e = np.clip(int_e + err * dt * 0.35, -400.0, 400.0)
            dterm = (err - prev_e) / dt if k > 1 else 0.0
            prev_e = err
            gain = 0.42 + 0.55 * quality
            u = P * 0.018 * err + I * 0.006 * int_e + D * 0.0012 * dterm
            g = gyro[k - 1] + dt * gain * u + rng.normal(0.0, noise_amp * 0.011)
        gyro[k] = (
            g
            + rng.normal(0.0, noise_amp * 0.0035)
            + osc_amp * np.sin(2.0 * np.pi * f_osc * t[k]) * 0.009
            + prop[k] * 0.012
        )

    setpoint = stick
    err = setpoint - gyro
    axis_p = P * err * 0.032
    d_err = np.zeros_like(gyro)
    d_err[1:] = (gyro[1:] - gyro[:-1]) / dt
    axis_d = D * d_err * 0.0035
    debug = 0.55 * gyro + 0.45 * setpoint + rng.normal(0.0, 1.5 + bad * 4.0, size=t.shape)
    return setpoint, gyro, axis_p, axis_d, debug


def dataframe_for_fc(fc: "MockFC", duration_s: float = 4.5, fs: int = 500, seed: int | None = None) -> pd.DataFrame:
    q = flight_quality(fc)
    rng = np.random.default_rng(seed)
    n = int(duration_s * fs)
    t = np.arange(n, dtype=np.float64) / float(fs)

    cols: Dict[str, Any] = {"time_s": t}
    thr = 1000.0 + 400.0 * np.sin(2.0 * np.pi * 0.25 * t) + rng.normal(0.0, 15.0, size=t.shape)
    cols["rcCommand[3]"] = np.clip(thr, 0.0, 2000.0)
    for i, ax in enumerate(("roll", "pitch", "yaw")):
        pid = fc.pids[ax]
        sp, gy, ap, ad, db = _synth_axis(
            t, float(fs), i, ax, float(pid["P"]), float(pid["I"]), float(pid["D"]), q, rng
        )
        cols[f"rcCommand[{i}]"] = sp
        cols[f"gyroADC[{i}]"] = gy
        cols[f"axisP[{i}]"] = ap
        cols[f"axisD[{i}]"] = ad
        cols[f"debug[{i}]"] = db
    for m in range(4):
        base = 1050.0 + 120.0 * cols["rcCommand[3]"] / 2000.0
        cols[f"motor[{m}]"] = base + rng.normal(0.0, (1.0 - q) * 25.0, size=t.shape)
    cols["vbatLatest"] = 1640.0 + rng.normal(0.0, 1.5, size=t.shape)
    return pd.DataFrame(cols)


def write_csv(fc: "MockFC", path: str, **kwargs: Any) -> None:
    df = dataframe_for_fc(fc, **kwargs)
    df.to_csv(path, index=False)


def csv_bytes(fc: "MockFC", **kwargs: Any) -> bytes:
    df = dataframe_for_fc(fc, **kwargs)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")
