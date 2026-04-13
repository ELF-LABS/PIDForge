#!/usr/bin/env python3
# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Synthetic decoded-style CSV for pipeline tests (no real BFL required)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent / "synthetic_tune_test.csv"


def main() -> None:
    fs = 500.0
    n = int(fs * 45)
    t_us = (np.arange(n) * (1e6 / fs)).astype(np.int64)
    t_s = t_us.astype(np.float64) * 1e-6

    # Roll: reasonable; Pitch: add high-frequency oscillation (P too high caricature)
    roll_gyro = 400 * np.sin(2 * math.pi * 0.8 * t_s) * np.exp(-0.02 * (t_s % 3))
    pitch_gyro = roll_gyro * 0.8 + 250 * np.sin(2 * math.pi * 35 * t_s)
    yaw_gyro = 80 * np.sin(2 * math.pi * 0.3 * t_s)

    p_err_roll = 120 * np.sin(2 * math.pi * 0.8 * t_s)
    p_err_pitch = 180 * np.sin(2 * math.pi * 0.7 * t_s)
    p_err_yaw = 40 * np.sin(2 * math.pi * 0.25 * t_s)

    thr = 40 + 30 * np.sin(2 * math.pi * 0.05 * t_s) + np.random.randn(n) * 2
    thr = np.clip(thr, 0, 100)

    # Motor imbalance + 280 Hz component on motor[2]
    base = 1200 + 400 * (thr / 100.0)
    m0 = base + 10 * np.sin(2 * math.pi * 280 * t_s)
    m1 = base * 1.02
    m2 = base * 1.08 + 40 * np.sin(2 * math.pi * 280 * t_s)
    m3 = base * 0.98

    # Battery sag after ~2 minutes (linear fade in mV)
    vbat = 16800 - np.clip((t_s - 90) * 8, 0, 2500) + np.random.randn(n) * 30

    d_err_roll = np.gradient(roll_gyro) * fs * 0.0001
    d_err_pitch = np.gradient(pitch_gyro) * fs * 0.0001
    debug0 = roll_gyro * 0.95 + np.random.randn(n) * 2

    df = pd.DataFrame(
        {
            "time (us)": t_us,
            "gyroADC[0]": roll_gyro,
            "gyroADC[1]": pitch_gyro,
            "gyroADC[2]": yaw_gyro,
            "axisP[0]": p_err_roll,
            "axisP[1]": p_err_pitch,
            "axisP[2]": p_err_yaw,
            "axisD[0]": d_err_roll,
            "axisD[1]": d_err_pitch,
            "axisD[2]": d_err_pitch * 0.5,
            "debug[0]": debug0,
            "debug[1]": pitch_gyro * 0.94,
            "debug[2]": yaw_gyro * 0.94,
            "rcCommand[3]": thr,
            "motor[0]": m0,
            "motor[1]": m1,
            "motor[2]": m2,
            "motor[3]": m3,
            "vbatLatest": vbat,
        }
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print("[INFO] wrote", OUT)


if __name__ == "__main__":
    main()
