# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Dark-theme plots (Venostic-inspired palette)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BG = "#0E0F11"
AMBER = "#F5A623"
CYAN = "#00D4E8"
GREEN = "#34D058"


def apply_dark_style() -> None:
    plt.style.use("dark_background")
    plt.rcParams.update(
        {
            "figure.facecolor": BG,
            "axes.facecolor": BG,
            "axes.edgecolor": "#333",
            "text.color": "#EAEAEA",
            "axes.labelcolor": "#EAEAEA",
            "xtick.color": "#AAA",
            "ytick.color": "#AAA",
            "grid.color": "#333333",
        }
    )


def plot_step_response(time_resp: List[float], curve: List[float], axis: str, out_path: Path) -> None:
    apply_dark_style()
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(time_resp, curve, color=CYAN, label="step")
    ax.axhline(1.0, color=AMBER, ls="--", lw=1, label="target")
    ax.set_title(f"Step response — {axis}")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Gain")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_fft(freq: List[float], mag_db: List[float], out_path: Path) -> None:
    apply_dark_style()
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(freq, mag_db, color=GREEN, lw=1)
    ax.set_xlabel("Hz")
    ax.set_ylabel("dB (relative)")
    ax.set_title("Gyro noise spectrum (roll)")
    ax.set_xlim(0, min(1000, max(freq) if freq else 1000))
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_motors(df: pd.DataFrame, out_path: Path) -> None:
    apply_dark_style()
    cols = [c for c in df.columns if c.startswith("motor[")]
    if not cols:
        return
    fig, ax = plt.subplots(figsize=(9, 4))
    for i, c in enumerate(sorted(cols)[:8]):
        ax.plot(df[c].values[:8000], label=c, alpha=0.85)
    ax.set_title("Motor outputs (first 8000 samples)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_battery(v: np.ndarray, out_path: Path) -> None:
    apply_dark_style()
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.plot(v, color=AMBER, lw=1)
    ax.set_title("Battery voltage trace")
    ax.set_xlabel("Sample")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_score_trend(scores: List[float], out_path: Path) -> None:
    apply_dark_style()
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.plot(range(len(scores)), scores, marker="o", color=CYAN)
    ax.set_title("Tune score per flight")
    ax.set_xlabel("Flight index")
    ax.set_ylabel("Score")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def write_analysis_bundle(analysis: Dict[str, Any], df: pd.DataFrame, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = analysis.get("parts", {})
    for ax in ("roll", "pitch"):
        sr = parts.get(f"step_{ax}", {})
        if sr.get("ok"):
            plot_step_response(sr["time_resp"], sr["curve"], ax, out_dir / f"step_{ax}.png")
    fft = parts.get("fft_roll", {})
    if fft.get("ok"):
        plot_fft(fft["frequencies"], fft["magnitudes_db"], out_dir / "fft_roll.png")
    plot_motors(df, out_dir / "motors.png")
    vb = None
    for c in ("vbatLatest", "vbat"):
        if c in df.columns:
            vb = df[c].to_numpy()
            break
    if vb is not None:
        plot_battery(vb[:20000], out_dir / "battery.png")
