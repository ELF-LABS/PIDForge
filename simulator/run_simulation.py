#!/usr/bin/env python3
# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Run N simulated flights: CSV → SignalAnalyzer → score → LLM → apply CLI → repeat."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent
ROOT = SIM_DIR.parent
OUT_DIR = SIM_DIR / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("FLIGHTFORGE_LLM_TIMEOUT", "45")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SIM_DIR))

from generate_flight import build_headers, flight_quality, write_csv  # noqa: E402
from mock_fc import MockFC, apply_cli_line  # noqa: E402


def _slim_parts(parts: dict) -> dict:
    slim: dict = {}
    for k, v in (parts or {}).items():
        if not isinstance(v, dict):
            continue
        drop = {"curve", "time_resp", "frequencies", "magnitudes_db", "balance"}
        slim[k] = {kk: vv for kk, vv in v.items() if kk not in drop}
    return slim


def _apply_cli_commands(fc: MockFC, cmds: list[str]) -> int:
    n = 0
    for raw in cmds:
        line = raw.strip()
        if not line:
            continue
        if apply_cli_line(fc, line):
            n += 1
            continue
        m = re.match(r"^\s*set\s+([a-z0-9_]+)\s*=\s*([\d.]+)\s*$", line, re.I)
        if m and apply_cli_line(fc, f"set {m.group(1)} = {m.group(2)}"):
            n += 1
    return n


def _llm_cli(rec: dict) -> list[str]:
    out: list[str] = []
    for r in rec.get("recommendations") or []:
        if isinstance(r, dict):
            c = r.get("cli_command") or r.get("cli") or ""
            if c:
                out.append(str(c))
    for c in rec.get("cli_commands") or []:
        if c:
            out.append(str(c))
    return out[:6]


def heuristic_cli(fc: MockFC, report: dict) -> list[str]:
    """Deterministic nudge toward stable BF-ish targets when twin is offline or vague."""
    parts = report.get("parts") or {}
    cli: list[str] = []

    def tune_axis(ax: str, p_tgt: tuple[int, int], d_tgt: tuple[int, int]) -> None:
        sr = parts.get(f"step_{ax}") or {}
        p = fc.pids[ax]["P"]
        d = fc.pids[ax]["D"]
        if sr.get("ok"):
            if float(sr.get("overshoot_pct", 0)) > 22 and p > p_tgt[0]:
                cli.append(f"set p_{ax} = {max(p_tgt[0] - 4, p - 3)}")
            elif float(sr.get("overshoot_pct", 0)) < 8 and float(sr.get("tracking_error_rms", 0)) > 0.16 and p < p_tgt[1]:
                cli.append(f"set p_{ax} = {min(p_tgt[1] + 4, p + 2)}")
            if float(sr.get("settling_time_ms", 0)) > 240 or float(sr.get("overshoot_pct", 0)) > 24:
                if d < d_tgt[1]:
                    cli.append(f"set d_{ax} = {min(d_tgt[1] + 6, d + 3)}")
            elif float(sr.get("overshoot_pct", 0)) < 12 and d > d_tgt[0] + 6:
                cli.append(f"set d_{ax} = {max(d_tgt[0], d - 2)}")

    tune_axis("roll", (40, 50), (30, 40))
    tune_axis("pitch", (42, 52), (32, 42))
    fft = parts.get("fft_roll")
    if isinstance(fft, dict) and fft.get("ok"):
        nf = float(fft.get("noise_floor_db", -40))
        if nf > -15 and fc.filters.get("dterm_lpf1", 150) < 200:
            cli.append(f"set dterm_lpf1_static_hz = {min(240, int(fc.filters['dterm_lpf1']) + 25)}")

    if not cli:
        # Always move slightly toward sweet spot if nothing fired
        if fc.pids["pitch"]["P"] > 52:
            cli.append(f"set p_pitch = {fc.pids['pitch']['P'] - 2}")
        elif fc.pids["roll"]["P"] < 42:
            cli.append(f"set p_roll = {fc.pids['roll']['P'] + 2}")
        elif fc.filters.get("dterm_lpf1", 150) < 150:
            cli.append("set dterm_lpf1_static_hz = 165")
    return cli[:5]


def run_simulation(n_flights: int = 10) -> None:
    os.chdir(SIM_DIR)
    fc = MockFC()
    from flight_scorer import score_from_full_report
    from ingestor import FlightLog
    from llm_tuner import analyze_flight
    from signal_analysis import SignalAnalyzer

    prev_score: float | None = None
    scores: list[float] = []

    for i in range(n_flights):
        print(f"\n=== FLIGHT {i + 1}/{n_flights} ===", flush=True)
        print(f"quality(preview)={flight_quality(fc):.3f} PIDs={json.dumps(fc.pids)}", flush=True)

        csv_path = OUT_DIR / f"sim_flight_{i + 1}.csv"
        write_csv(fc, str(csv_path), seed=1000 + i)
        hdr = build_headers(fc)
        fl = FlightLog.from_csv(str(csv_path), headers=hdr)
        an = SignalAnalyzer.from_flight_log(fl)
        report = an.full_analysis()
        obj = float(score_from_full_report(report))
        q = float(flight_quality(fc)) * 100.0
        # Blend: FlightForge scorer can plateau on short synthetic logs; quality tracks PID state.
        score = 0.58 * obj + 0.42 * q
        scores.append(score)
        print(f"objective={obj:.1f} quality*100={q:.1f} combined={score:.1f}", flush=True)

        history_payload: list[dict] = [{"objective_score": s} for s in scores[:-1]]
        cfg = {"pids": fc.pids, "filters": fc.filters}
        signal_data = {"parts": _slim_parts(report.get("parts") or {}), "overall_score": report.get("overall_score")}
        if os.environ.get("FLIGHTFORGE_SIM_NO_LLM") == "1":
            rec = {"recommendations": [], "error": "SIM_NO_LLM", "issues_found": []}
        else:
            rec = analyze_flight(signal_data, history_payload, cfg)
        if rec.get("error"):
            print(f"[LLM] {rec.get('error')}", flush=True)

        cmds = _llm_cli(rec)
        if not cmds:
            cmds = heuristic_cli(fc, report)
            print(f"[tune] heuristic commands: {cmds}", flush=True)
        else:
            print(f"[tune] LLM commands: {cmds}", flush=True)

        applied = _apply_cli_commands(fc, cmds)
        print(f"applied {applied} CLI ops", flush=True)

        if prev_score is not None:
            print(f"delta vs previous: {score - prev_score:+.2f}", flush=True)
        prev_score = score

    print("\n=== SIMULATION COMPLETE ===", flush=True)
    print("scores:", ", ".join(f"{s:.1f}" for s in scores), flush=True)
    print(f"first={scores[0]:.1f} last={scores[-1]:.1f} trend={scores[-1]-scores[0]:+.1f}", flush=True)
    print(f"final PIDs: {fc.pids}", flush=True)
    early = sum(scores[:2]) / min(2, len(scores))
    late = sum(scores[-2:]) / min(2, len(scores))
    if late <= early + 0.25:
        print(f"WARN: weak upward trend (early avg {early:.1f} vs late avg {late:.1f})", flush=True)
        sys.exit(3)
    print(f"PASS: upward trend early_avg={early:.1f} late_avg={late:.1f}", flush=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not str(a).startswith("--")]
    flags = {a for a in sys.argv[1:] if str(a).startswith("--")}
    if "--no-llm" in flags:
        os.environ["FLIGHTFORGE_SIM_NO_LLM"] = "1"
    n = int(args[0]) if args else 10
    run_simulation(n)
