#!/usr/bin/env python3
# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""FlightForge — Betaflight tuning wizard CLI (local signal analysis, no LLM)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _paths

_paths.ensure_orangebox_path()

from connection import FCConnection
from esc_detection import detect as esc_detect
from flight_store import FlightStore
from ingestor import FlightLog
from plotter import write_analysis_bundle
from recommender import Recommender
from signal_analysis import SignalAnalyzer
from wizard import WizardState, load_state, maneuver_for_state, save_state


def cmd_connect(args: argparse.Namespace) -> int:
    fc = FCConnection(port=args.port)
    info = fc.detect(args.port)
    print("[INFO] FC detected:", json.dumps(info, indent=2))
    esc = esc_detect(fc)
    print("[INFO] ESC / motor protocol:", json.dumps(esc, indent=2))
    bb = fc.read_blackbox_config()
    print("[INFO] Blackbox MSP:", bb)
    print(
        "\n[WARN] To apply optimal blackbox + debug settings, FlightForge must write MSP settings.\n"
        "         Flash logging to onboard flash can ERASE logs. SD card side is safer.\n"
        "         Type YES ERASE if you accept: ",
        end="",
    )
    if sys.stdin.isatty():
        line = input().strip()
        ok = line == "YES ERASE"
    else:
        ok = False
        print("(non-interactive) skip flash")
    if ok:
        fc.flash_blackbox_config(True)
        fc.flash_debug_mode_gyro_scaled(True)
        print("[INFO] Blackbox + debug_mode write attempted.")
    fc.close()
    return 0


def _load_log(path: str, index: int) -> FlightLog:
    if path.lower().endswith(".csv"):
        hdr = {
            "Firmware revision": "Betaflight 4.5.0",
            "rollPID": "45,80,30",
            "pitchPID": "50,85,35",
            "yawPID": "45,80,0",
            "vbatcellcount": "4",
        }
        return FlightLog.from_csv(path, headers=hdr)
    return FlightLog.load(path, log_index=index)


def cmd_analyze(args: argparse.Namespace) -> int:
    path = args.log
    fl = _load_log(path, args.index)
    st = load_state()
    if args.quad:
        st.quad_name = args.quad
    an = SignalAnalyzer.from_flight_log(fl)
    report = an.full_analysis()
    if FlightStore.config_changed(fl.config_hash, st.last_config_hash) and st.last_config_hash:
        print("[WARN] Config hash changed vs last flight — pilot may have edited tune manually; rebaseline.")
    st.last_config_hash = fl.config_hash
    rec = Recommender(an, st)
    recs = rec.build()
    print("[INFO] Overall score:", round(report["overall_score"], 1))
    print("[INFO] Recommendations:")
    for r in recs:
        print(json.dumps(r, indent=2))
    cli_text = rec.cli_diff(recs)
    print("\n--- CLI diff ---\n")
    print(cli_text)
    st.last_cli_diff = cli_text
    store = FlightStore(st.quad_name)
    meta = store.cache_flight(path, st.quad_name, st.session)
    store.record_metric(meta["flight_id"], "score", float(report["overall_score"]))
    if args.plots:
        write_analysis_bundle(report, fl.df, Path(args.plots))
    if getattr(args, "advance", True) and recs:
        st.advance()
        print("[INFO] Wizard advanced to next step (one change per flight). Use --no-advance to keep phase.")
    elif getattr(args, "advance", True) and not recs:
        print("[INFO] No automatic recommendations; wizard phase unchanged. Tune log or use a fresher maneuver.")
    save_state(st)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    st = load_state()
    print(json.dumps(st.to_dict(), indent=2))
    m = maneuver_for_state(st)
    print("[INFO] Next maneuver:", m.get("name"))
    for line in m.get("detail", []):
        print("   •", line)
    if m.get("warning"):
        print("[WARN]", m["warning"])
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    st = load_state()
    store = FlightStore(st.quad_name)
    prev = store.get_previous_flight(st.quad_name)
    print(json.dumps(prev or {}, indent=2))
    return 0


def cmd_trend(args: argparse.Namespace) -> int:
    st = load_state()
    store = FlightStore(st.quad_name)
    vals = store.get_trend(st.quad_name, args.metric)
    print("[INFO]", args.metric, vals)
    if args.plot:
        from plotter import plot_score_trend

        plot_score_trend(vals, Path(args.plot))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    st = load_state()
    if st.last_cli_diff.strip():
        print("# Last paste-ready CLI diff from analyze:\n")
        print(st.last_cli_diff.rstrip() + "\n")
    print(json.dumps(st.to_dict(), indent=2))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    a = SignalAnalyzer.from_flight_log(_load_log(args.a, 1))
    b = SignalAnalyzer.from_flight_log(_load_log(args.b, 1))
    print(json.dumps(a.compare(b), indent=2))
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    st = WizardState(quad_name=args.quad or "default_quad")
    save_state(st)
    print("[INFO] Wizard reset.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="flightforge", description="FlightForge Betaflight tuning wizard")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("connect", help="USB MSP: detect FC, show blackbox + ESC info")
    pc.add_argument("--port", "-p", default=None)
    pc.set_defaults(func=cmd_connect)

    pa = sub.add_parser("analyze", help="Analyze .BFL/.BBL or decoded .CSV")
    pa.add_argument("log")
    pa.add_argument("--index", type=int, default=1, help="Log index inside merged BBL")
    pa.add_argument("--quad", default=None)
    pa.add_argument("--plots", default=None, help="Directory to write PNGs")
    adv = pa.add_mutually_exclusive_group()
    adv.add_argument("--advance", dest="advance", action="store_true", help="Advance wizard after recommendations (default)")
    adv.add_argument("--no-advance", dest="advance", action="store_false", help="Keep wizard phase after analyze")
    pa.set_defaults(advance=True, func=cmd_analyze)

    ps = sub.add_parser("status", help="Wizard progress + next maneuver")
    ps.set_defaults(func=cmd_status)

    ph = sub.add_parser("history", help="Last cached flight metadata")
    ph.set_defaults(func=cmd_history)

    pt = sub.add_parser("trend", help="Metric trend from Chroma history")
    pt.add_argument("metric", nargs="?", default="score")
    pt.add_argument("--plot", default=None)
    pt.set_defaults(func=cmd_trend)

    pe = sub.add_parser("export", help="Print wizard state JSON")
    pe.set_defaults(func=cmd_export)

    pc2 = sub.add_parser("compare", help="Compare two logs (step deltas)")
    pc2.add_argument("a")
    pc2.add_argument("b")
    pc2.set_defaults(func=cmd_compare)

    pr = sub.add_parser("reset", help="Reset wizard state")
    pr.add_argument("--quad", default=None)
    pr.set_defaults(func=cmd_reset)

    args = p.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
