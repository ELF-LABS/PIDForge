# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
#
# FlightForge Tuning Tree — synthesized tuning order for Betaflight step tuning.

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TunePhase(Enum):
    BLACKBOX_SETUP = "blackbox_setup"
    FILTERS = "filters"
    D_TERM = "d_term"
    P_TERM = "p_term"
    I_TERM = "i_term"
    ANTI_GRAVITY = "anti_gravity"
    ITERM_RELAX = "iterm_relax"
    FEEDFORWARD = "feedforward"
    THRUST_LINEAR = "thrust_linearization"
    VBAT_COMP = "vbat_compensation"
    TPA = "tpa"
    DYNAMIC_IDLE = "dynamic_idle"
    VALIDATION = "validation"
    DONE = "done"


PHASE_ORDER = [
    TunePhase.FILTERS,
    TunePhase.D_TERM,
    TunePhase.P_TERM,
    TunePhase.I_TERM,
    TunePhase.ANTI_GRAVITY,
    TunePhase.ITERM_RELAX,
    TunePhase.FEEDFORWARD,
    TunePhase.THRUST_LINEAR,
    TunePhase.VBAT_COMP,
    TunePhase.TPA,
    TunePhase.DYNAMIC_IDLE,
    TunePhase.VALIDATION,
]


@dataclass
class TuneParam:
    name: str
    cli_key: str
    default: float
    step_initial: float
    step_fine: float
    min_val: float
    max_val: float
    per_axis: bool
    danger: str
    test_maneuver: str
    good_signal: str
    bad_signal: str


PARAMS = {
    "gyro_lpf1_hz": TuneParam(
        "Gyro LPF1",
        "gyro_lpf1_static_hz",
        150,
        25,
        10,
        0,
        500,
        False,
        "motors",
        "Gentle hover + light rolls, 30 seconds",
        "Clean FFT, motors cool to touch",
        "FFT noise spikes below cutoff, motors warm",
    ),
    "dterm_lpf1_hz": TuneParam(
        "D-term LPF",
        "dterm_lpf1_static_hz",
        100,
        20,
        10,
        50,
        300,
        False,
        "motors",
        "Same as gyro filter test",
        "Smooth D-trace, cool motors",
        "Jagged D-trace, hot motors",
    ),
    "dyn_notch_count": TuneParam(
        "Dynamic Notch Count",
        "dyn_notch_count",
        1,
        1,
        1,
        0,
        5,
        False,
        "safe",
        "General flight",
        "Notch tracks motor peak in FFT",
        "Peak visible through notch",
    ),
    "dyn_notch_q": TuneParam(
        "Dynamic Notch Q",
        "dyn_notch_q",
        500,
        100,
        50,
        100,
        1000,
        False,
        "safe",
        "General flight",
        "Narrow notch on motor peak",
        "Too wide = latency, too narrow = misses",
    ),
    "d": TuneParam(
        "D Gain",
        "d_{axis}",
        30,
        3,
        1,
        0,
        60,
        True,
        "motors",
        "Snap rolls — punch stick full then release. 5 each direction.",
        "Clean stop, 1-2 small bounces then stable",
        "Continuous bouncing (too low) or sluggish/hot motors (too high)",
    ),
    "p": TuneParam(
        "P Gain",
        "p_{axis}",
        45,
        4,
        1,
        20,
        80,
        True,
        "safe",
        "Fast continuous rolls back and forth, alternating every half second",
        "Gyro tracks setpoint tightly, <20% overshoot",
        "Mushy/slow (too low) or ringing oscillation (too high)",
    ),
    "i": TuneParam(
        "I Gain",
        "i_{axis}",
        80,
        5,
        2,
        20,
        150,
        True,
        "safe",
        "Hover 15 seconds hands-off in wind",
        "Quad holds position, smooth return to level",
        "Drifts (too low) or oscillates around level (too high)",
    ),
    "anti_gravity_gain": TuneParam(
        "Anti-Gravity Gain",
        "anti_gravity_gain",
        5000,
        500,
        200,
        1000,
        10000,
        False,
        "safe",
        "Throttle blips — punch up then cut",
        "No nose-dip on throttle changes",
        "Nose dips forward on throttle cut",
    ),
    "iterm_relax_cutoff": TuneParam(
        "iTerm Relax Cutoff",
        "iterm_relax_cutoff",
        15,
        5,
        2,
        5,
        50,
        False,
        "safe",
        "Flips and rolls — aggressive moves",
        "No bounce-back after flips",
        "Bounce-back or overshoot after aggressive moves",
    ),
    "f": TuneParam(
        "Feedforward",
        "f_{axis}",
        120,
        15,
        5,
        0,
        300,
        True,
        "safe",
        "Freestyle flow — fly naturally for 30 seconds",
        "Stick inputs feel immediate, no lag",
        "Laggy (too low) or twitchy/jittery (too high)",
    ),
    "thrust_linear": TuneParam(
        "Thrust Linearization",
        "thrust_linear",
        0,
        5,
        2,
        0,
        150,
        False,
        "safe",
        "Low throttle maneuvers + high throttle maneuvers",
        "Consistent feel across throttle range",
        "Mushy at low throttle, twitchy at high (or vice versa)",
    ),
    "vbat_sag_compensation": TuneParam(
        "Vbat Sag Comp",
        "vbat_sag_compensation",
        100,
        10,
        5,
        0,
        200,
        False,
        "safe",
        "Fly full battery then half battery",
        "Consistent feel throughout pack",
        "Gets mushy or aggressive as battery drains",
    ),
    "tpa_rate": TuneParam(
        "TPA Rate",
        "tpa_rate",
        65,
        5,
        2,
        0,
        100,
        False,
        "safe",
        "Full throttle sustained flight",
        "No oscillation at high throttle",
        "Vibration/oscillation only at high throttle",
    ),
    "tpa_breakpoint": TuneParam(
        "TPA Breakpoint",
        "tpa_breakpoint",
        1350,
        50,
        25,
        1000,
        2000,
        False,
        "safe",
        "Same",
        "Breakpoint at throttle where oscillation starts",
        "",
    ),
    "dshot_idle_value": TuneParam(
        "DShot Idle",
        "dshot_idle_value",
        550,
        25,
        10,
        300,
        1000,
        False,
        "safe",
        "Aggressive throttle chops — power loops and dives",
        "Clean recovery from dives, no prop wash wobble",
        "Prop wash oscillation on throttle recovery",
    ),
}


MANEUVER_INSTRUCTIONS = {
    TunePhase.FILTERS: {
        "name": "Gentle Hover + Light Rolls",
        "detail": [
            "Take off and hover at mid-throttle for 5 seconds",
            "Do 3 gentle rolls (about 30 degrees each way)",
            "Do 3 gentle pitch moves",
            "Keep it SMOOTH — we're reading the noise floor",
            "Land and check motor temperatures immediately",
        ],
        "duration": 30,
        "warning": "If motors are hot to touch, DO NOT fly again until cooled",
    },
    TunePhase.D_TERM: {
        "name": "Snap Rolls — Punch and Release",
        "detail": [
            "Full stick roll RIGHT then immediately release to center",
            "Wait 1 second",
            "Full stick roll LEFT then release",
            "Repeat 5 times each direction",
            "We're measuring bounce-back after sharp stops",
        ],
        "duration": 30,
        "warning": "Check motor temps after landing. Hot = D is too high",
    },
    TunePhase.P_TERM: {
        "name": "Fast Tracking — Continuous Rolls",
        "detail": [
            "Fast continuous rolls back and forth",
            "Alternate direction every half second",
            "Then same for pitch axis",
            "We're measuring how tightly gyro follows your stick",
        ],
        "duration": 30,
        "warning": None,
    },
    TunePhase.I_TERM: {
        "name": "Hover Hands-Off",
        "detail": [
            "Hover in place for 15 seconds",
            "Do NOT touch the sticks",
            "Let the wind push it if there is any",
            "We're measuring attitude hold — does it drift or stay put?",
        ],
        "duration": 20,
        "warning": "Do this in a safe open area — quad may drift",
    },
    TunePhase.ANTI_GRAVITY: {
        "name": "Throttle Blips",
        "detail": [
            "Hover, then quick throttle punch UP",
            "Immediately cut throttle back to hover",
            "Watch if nose dips forward on the cut",
            "Repeat 5 times",
        ],
        "duration": 20,
        "warning": None,
    },
    TunePhase.ITERM_RELAX: {
        "name": "Aggressive Flips",
        "detail": [
            "Do a full flip (roll or pitch)",
            "Watch for bounce-back after completing the flip",
            "Repeat 5 times",
            "If quad bounces or overshoots after the flip, iterm_relax needs adjusting",
        ],
        "duration": 30,
        "warning": None,
    },
    TunePhase.FEEDFORWARD: {
        "name": "Freestyle Flow",
        "detail": [
            "Fly however you naturally fly for 30 seconds",
            "Rolls, flips, split-S, whatever feels good",
            "Focus on how the quad FEELS — does it anticipate your moves?",
            "We're measuring stick feel and response latency",
        ],
        "duration": 30,
        "warning": None,
    },
    TunePhase.THRUST_LINEAR: {
        "name": "Throttle Range Test",
        "detail": [
            "Hover at 20% throttle — do some gentle moves",
            "Then hover at 50% — same moves",
            "Then 80% — same moves",
            "Does the quad feel the same at all throttle positions?",
        ],
        "duration": 30,
        "warning": None,
    },
    TunePhase.VBAT_COMP: {
        "name": "Full Pack to Half Pack",
        "detail": [
            "Fly normally for 1 minute (start of pack)",
            "Note how it feels",
            "Fly another 2 minutes (mid pack)",
            "Does it feel the same? Mushier? More aggressive?",
        ],
        "duration": 180,
        "warning": "Use a timer — don't drain the battery below 3.3V/cell",
    },
    TunePhase.TPA: {
        "name": "Full Throttle Sustained",
        "detail": [
            "Do a long straight punch-out at full throttle",
            "Hold for 2-3 seconds",
            "Any vibration or oscillation at full throttle?",
            "If yes, that's where TPA kicks in",
        ],
        "duration": 20,
        "warning": "Full throttle = fast quad. Do this in a big open area",
    },
    TunePhase.DYNAMIC_IDLE: {
        "name": "Throttle Chops — Power Loops",
        "detail": [
            "Full throttle punch UP",
            "Cut throttle completely and dive",
            "Recover with throttle at the bottom",
            "Watch for wobble/oscillation during the recovery",
            "That's prop wash — dynamic idle helps",
            "Repeat 5 times",
        ],
        "duration": 45,
        "warning": "Altitude required — minimum 30 feet for safe recovery",
    },
    TunePhase.VALIDATION: {
        "name": "Full Flight — Everything",
        "detail": [
            "Fly a full session — mix of everything",
            "Hover, rolls, flips, dives, freestyle, racing lines",
            "Full pack if possible",
            "This is the final check — does it feel GOOD?",
        ],
        "duration": 180,
        "warning": None,
    },
}


PHASE_PARAMS = {
    TunePhase.FILTERS: ["gyro_lpf1_hz", "dterm_lpf1_hz", "dyn_notch_count", "dyn_notch_q"],
    TunePhase.D_TERM: ["d"],
    TunePhase.P_TERM: ["p"],
    TunePhase.I_TERM: ["i"],
    TunePhase.ANTI_GRAVITY: ["anti_gravity_gain"],
    TunePhase.ITERM_RELAX: ["iterm_relax_cutoff"],
    TunePhase.FEEDFORWARD: ["f"],
    TunePhase.THRUST_LINEAR: ["thrust_linear"],
    TunePhase.VBAT_COMP: ["vbat_sag_compensation"],
    TunePhase.TPA: ["tpa_rate", "tpa_breakpoint"],
    TunePhase.DYNAMIC_IDLE: ["dshot_idle_value"],
    TunePhase.VALIDATION: [],
}
