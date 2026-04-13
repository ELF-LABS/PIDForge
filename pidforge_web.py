#!/usr/bin/env python3
# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""FlightForge Web UI — Flask wrapper around the same pipeline as flightforge.py CLI."""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

FF_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FF_DIR))

import _paths

_paths.ensure_orangebox_path()

from config_parser import extract_pid_from_headers, parse_cli_text
from flight_scorer import compare_flights, score_from_full_report
from flight_store import FlightStore
from ingestor import FlightLog
from llm_tuner import analyze_flight
from recommender import Recommender
from signal_analysis import SignalAnalyzer
from wizard import load_state, maneuver_for_state, save_state

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__)

UPLOAD_DIR = FF_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
STATIC_DIR = FF_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
CLAW_STATE_PATH = FF_DIR / "claw_state.json"
PENDING_CLI_PATH = FF_DIR / "pending_cli_diff.txt"


def _read_claw_state() -> dict:
    if not CLAW_STATE_PATH.is_file():
        return {}
    try:
        return json.loads(CLAW_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_claw_state(obj: dict) -> None:
    CLAW_STATE_PATH.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def _slim_parts_for_llm(parts: dict) -> dict:
    slim: dict = {}
    for k, v in (parts or {}).items():
        if not isinstance(v, dict):
            continue
        drop = {"curve", "time_resp", "frequencies", "magnitudes_db", "balance"}
        slim[k] = {kk: vv for kk, vv in v.items() if kk not in drop}
    return slim


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


@app.route("/")
def index():
    p = STATIC_DIR / "index.html"
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return (FF_DIR / "static_index.html").read_text(encoding="utf-8")


@app.route("/manifest.json")
def manifest():
    mp = STATIC_DIR / "manifest.json"
    if not mp.is_file():
        return jsonify({"error": "manifest missing"}), 404
    return send_from_directory(STATIC_DIR, "manifest.json", mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    sp = STATIC_DIR / "sw.js"
    if not sp.is_file():
        return jsonify({"error": "sw missing"}), 404
    return send_from_directory(STATIC_DIR, "sw.js", mimetype="application/javascript")


@app.route("/static/<path:fname>")
def static_files(fname: str):
    return send_from_directory(STATIC_DIR, fname)


@app.route("/api/upload", methods=["POST"])
def upload_bfl():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    save_path = UPLOAD_DIR / f.filename
    f.save(str(save_path))

    quad = request.form.get("quad") or "web_quad"
    advance = request.form.get("advance", "1") not in ("0", "false", "no")

    try:
        fl = _load_log(str(save_path))
        st = load_state()
        st.quad_name = quad
        if FlightStore.config_changed(fl.config_hash, st.last_config_hash) and st.last_config_hash:
            pass

        an = SignalAnalyzer.from_flight_log(fl)
        report = an.full_analysis()
        st.last_config_hash = fl.config_hash

        rec = Recommender(an, st)
        recs = rec.build()
        cli_text = rec.cli_diff(recs)
        st.last_cli_diff = cli_text

        store = FlightStore(st.quad_name)
        meta = store.cache_flight(str(save_path), st.quad_name, st.session)
        obj_score = float(score_from_full_report(report))
        store.record_metric(meta["flight_id"], "score", float(report["overall_score"]))
        store.record_metric(meta["flight_id"], "objective_score", obj_score)

        if advance and recs:
            st.advance()

        save_state(st)

        return jsonify(
            {
                "flight_id": meta.get("flight_id"),
                "filename": f.filename,
                "quad": st.quad_name,
                "overall_score": round(float(report["overall_score"]), 2),
                "objective_score": round(obj_score, 2),
                "recommendations": recs,
                "cli_diff": cli_text,
                "full_report": report,
                "maneuver": maneuver_for_state(st),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/api/score", methods=["POST"])
def api_score():
    data = request.get_json(silent=True) or {}
    report = data.get("full_report") or {}
    if not report:
        return jsonify({"error": "full_report required"}), 400
    score = float(score_from_full_report(report))
    out: dict = {"flight_score": score}
    prev = data.get("previous_score")
    if prev is not None:
        try:
            out["comparison"] = compare_flights(score, float(prev))
        except (TypeError, ValueError):
            out["comparison"] = None
    return jsonify(out)


@app.route("/api/bt-analyze", methods=["POST"])
def bt_analyze():
    """Phone / bridge posts ``full_report`` (+ optional config); returns objective + LLM JSON."""
    data = request.get_json(silent=True) or {}
    full_report = data.get("full_report")
    if not full_report:
        return jsonify({"error": "full_report required"}), 400
    st = load_state()
    quad = data.get("quad") or st.quad_name
    st.quad_name = quad
    score = float(score_from_full_report(full_report))
    store = FlightStore(quad)
    history = store.recent_flights(quad, limit=12)
    cfg = data.get("current_config") or {}
    if not cfg and data.get("headers"):
        cfg = extract_pid_from_headers(data["headers"])
    if not cfg:
        cfg = {}
    parts = full_report.get("parts") or {}
    signal_data = data.get("signal_data") or {
        "parts": _slim_parts_for_llm(parts),
        "overall_score": full_report.get("overall_score"),
    }
    llm_out = analyze_flight(signal_data, history, cfg)
    body = {
        "objective_score": round(score, 2),
        "llm": llm_out,
        "quad": quad,
    }
    _write_claw_state({"last_bt_analyze": body, "ts": __import__("time").time()})
    return jsonify(body)


@app.route("/api/bt-apply", methods=["POST"])
def bt_apply():
    """Store CLI diff for the BLE bridge; returns line list for MSP/CLI push."""
    data = request.get_json(silent=True) or {}
    cli = data.get("cli_diff")
    if cli is None and isinstance(data.get("cli_commands"), list):
        cli = "\n".join(str(x) for x in data["cli_commands"])
    if not cli:
        return jsonify({"error": "cli_diff or cli_commands required"}), 400
    PENDING_CLI_PATH.write_text(str(cli), encoding="utf-8")
    lines = [ln.strip() for ln in str(cli).splitlines() if ln.strip() and not ln.strip().startswith("#")]
    _write_claw_state({"pending_apply_lines": lines, "ts": __import__("time").time()})
    return jsonify({"ok": True, "lines": lines, "line_count": len(lines)})


@app.route("/api/claw-status", methods=["GET"])
def claw_status():
    return jsonify(_read_claw_state())


@app.route("/api/paste-config", methods=["POST"])
def paste_config():
    data = request.get_json(silent=True) or {}
    if "config" not in data:
        return jsonify({"error": "No config provided"}), 400
    try:
        parsed = parse_cli_text(data["config"])
        return jsonify({"parsed": parsed, "count": len(parsed)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/wizard/state", methods=["GET"])
def get_wizard_state():
    st = load_state()
    return jsonify(st.to_dict())


@app.route("/api/wizard/advance", methods=["POST"])
def advance_wizard():
    st = load_state()
    m = maneuver_for_state(st)
    return jsonify({"state": st.to_dict(), "maneuver": m})


@app.route("/api/history", methods=["GET"])
def flight_history():
    st = load_state()
    store = FlightStore(st.quad_name)
    prev = store.get_previous_flight(st.quad_name)
    try:
        col = store._flights
        res = col.get(where={"quad": st.quad_name}, include=["metadatas", "documents"], limit=30)
        flights = []
        for i, fid in enumerate(res.get("ids") or []):
            md = (res.get("metadatas") or [None])[i] or {}
            flights.append({"id": fid, **md})
        flights.reverse()
    except Exception as e:
        flights = []
        return jsonify({"flights": flights, "previous": prev or {}, "error": str(e)})
    return jsonify({"flights": flights, "previous": prev or {}})


if __name__ == "__main__":
    port = int(os.environ.get("FLIGHTFORGE_PORT", "5050"))
    print(f"[INFO] FlightForge Web UI http://0.0.0.0:{port}", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
