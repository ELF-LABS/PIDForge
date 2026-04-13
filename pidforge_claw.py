#!/usr/bin/env python3
# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""FlightForge autonomous agent — watches Chroma for new flights, scores, LLM recommends (no auto-apply)."""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

FF_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FF_DIR))

import _paths

_paths.ensure_orangebox_path()

from config_parser import extract_pid_from_headers
from flight_scorer import compare_flights, score_from_full_report
from flight_store import FlightStore
from ingestor import FlightLog
from llm_tuner import analyze_flight
from signal_analysis import SignalAnalyzer
from wizard import load_state


def _load_log(path: str) -> FlightLog:
    p = path.lower()
    if p.endswith(".csv"):
        hdr = {
            "Firmware revision": "Betaflight 4.5.0",
            "rollPID": "45,80,30",
            "pitchPID": "50,85,35",
            "yawPID": "45,80,0",
            "vbatcellcount": "4",
        }
        return FlightLog.from_csv(path, headers=hdr)
    return FlightLog.load(path, log_index=1)


def _slim_parts(parts: dict) -> dict:
    slim: dict = {}
    for k, v in (parts or {}).items():
        if not isinstance(v, dict):
            continue
        drop = {"curve", "time_resp", "frequencies", "magnitudes_db", "balance"}
        slim[k] = {kk: vv for kk, vv in v.items() if kk not in drop}
    return slim


class FlightForgeClaw:
    def __init__(self) -> None:
        self._checkpoint_path = FF_DIR / "claw_checkpoint.txt"
        self._last_id = self._checkpoint_path.read_text(encoding="utf-8").strip() if self._checkpoint_path.is_file() else ""

    def process_flight(self, store: FlightStore, flight: dict, quad: str) -> dict:
        fid = flight.get("id") or flight.get("flight_id")
        path = flight.get("path")
        print(f"[CLAW] New flight detected: {fid} path={path}")
        if not path or not Path(path).is_file():
            print("[CLAW] skip — missing path or file")
            return {"error": "missing_path"}

        fl = _load_log(str(path))
        an = SignalAnalyzer.from_flight_log(fl)
        report = an.full_analysis()
        score = float(score_from_full_report(report))
        print(f"[CLAW] Objective score: {score}/100")

        history = store.recent_flights(quad, limit=8)
        prev_score = None
        if len(history) > 1:
            prev_meta = history[1]
            for key in ("objective_score", "score"):
                if key in prev_meta:
                    try:
                        prev_score = float(prev_meta[key])
                        break
                    except (TypeError, ValueError):
                        pass
        if prev_score is not None:
            cmp = compare_flights(score, prev_score)
            print(f"[CLAW] {cmp['verdict']} (delta {cmp['delta']:+.1f})")

        cfg = extract_pid_from_headers(fl.headers)
        signal_data = {"parts": _slim_parts(report.get("parts") or {}), "overall_score": report.get("overall_score")}
        print("[CLAW] Requesting LLM analysis...")
        recommendation = analyze_flight(signal_data, history, cfg)

        if fid:
            store.merge_flight_metadata(
                str(fid),
                {
                    "objective_score": score,
                    "recommendation_json": recommendation,
                    "claw_status": "pending_approval",
                },
            )

        out = {
            "flight_id": fid,
            "objective_score": score,
            "llm": recommendation,
            "quad": quad,
        }
        (FF_DIR / "claw_state.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        print("[CLAW] Recommendation ready — waiting for pilot approval")
        return out

    def watch(self, interval: int = 5) -> None:
        print("[CLAW] FlightForge agent watching Chroma for new flights...")
        while True:
            try:
                st = load_state()
                quad = st.quad_name
                store = FlightStore(quad)
                recent = store.recent_flights(quad, limit=5)
                if not recent:
                    time.sleep(interval)
                    continue
                latest = recent[0]
                fid = str(latest.get("id") or latest.get("flight_id") or "")
                if fid and fid != self._last_id:
                    self._last_id = fid
                    self._checkpoint_path.write_text(self._last_id, encoding="utf-8")
                    self.process_flight(store, latest, quad)
            except KeyboardInterrupt:
                print("[CLAW] stopped")
                raise
            except Exception as e:
                print("[CLAW] error:", e)
                print(traceback.format_exc())
            time.sleep(interval)


if __name__ == "__main__":
    FlightForgeClaw().watch()
