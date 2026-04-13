# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Blackbox (.BFL / .BBL) ingest via orangebox."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

import _paths

_paths.ensure_orangebox_path()

from orangebox import Parser  # type: ignore  # noqa: E402

from config_parser import config_hash_from_headers
from firmware_compat import detect_version, validate_log


def _norm_time_series(df: pd.DataFrame) -> pd.DataFrame:
    if "time (us)" in df.columns:
        df = df.copy()
        df["time_s"] = df["time (us)"].astype(float) * 1e-6
    elif "time" in df.columns:
        df = df.copy()
        t = df["time"].astype(float)
        if t.max() > 1e6:
            df["time_s"] = t * 1e-6
        else:
            df["time_s"] = t
    return df


def _guess_sample_rate_hz(df: pd.DataFrame) -> int:
    if "time_s" not in df.columns or len(df) < 8:
        return 500
    dt = df["time_s"].diff().median()
    if dt <= 0:
        return 500
    return int(round(1.0 / dt))


@dataclass
class FlightLog:
    """Parse BFL via orangebox, expose headers + DataFrame."""

    path: str
    log_index: int = 1
    df: pd.DataFrame = field(default_factory=pd.DataFrame)
    headers: Dict[str, Any] = field(default_factory=dict)
    field_names: List[str] = field(default_factory=list)
    config_hash: str = ""
    firmware_label: str = ""

    @classmethod
    def from_csv(cls, path: str, headers: Optional[Dict[str, Any]] = None) -> "FlightLog":
        """Load a decoded-style CSV (columns match Betaflight blackbox export names)."""
        p = Path(path)
        df = pd.read_csv(str(p))
        df = _norm_time_series(df)
        hdr = dict(headers or {})
        ch = config_hash_from_headers(hdr)
        fw = detect_version(hdr)
        return cls(
            path=str(p),
            log_index=1,
            df=df,
            headers=hdr,
            field_names=list(df.columns),
            config_hash=ch,
            firmware_label=fw,
        )

    @classmethod
    def load(cls, path: str, log_index: int = 1) -> "FlightLog":
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(path)
        parser = Parser.load(str(p), log_index=log_index)
        names = list(parser.field_names)
        rows: List[Dict[str, Any]] = []
        for fr in parser.frames():
            if len(fr.data) != len(names):
                continue
            rows.append({names[i]: fr.data[i] for i in range(len(names))})
        df = pd.DataFrame(rows)
        df = _norm_time_series(df)
        hdr = dict(parser.headers)
        ch = config_hash_from_headers(hdr)
        fw = detect_version(hdr)
        ok, warns = validate_log(hdr)
        if not ok:
            for w in warns:
                print(f"[WARN] {w}")
        return cls(path=str(p), log_index=log_index, df=df, headers=hdr, field_names=names, config_hash=ch, firmware_label=fw)

    def column_aliases(self) -> Dict[str, str]:
        """Map canonical names used by SignalAnalyzer to actual dataframe columns."""
        cols = set(self.df.columns)
        m: Dict[str, str] = {}

        def pick(*cands: str) -> Optional[str]:
            for c in cands:
                if c in cols:
                    return c
            return None

        m["time_s"] = pick("time_s") or "time_s"
        for i, axis in enumerate(("roll", "pitch", "yaw")):
            m[f"gyro_{axis}"] = pick(f"gyroADC[{i}]", f"gyro[{i}]") or ""
            m[f"setpoint_{axis}"] = pick(f"setpoint[{i}]", f"rcCommand[{i}]") or ""
            m[f"p_err_{axis}"] = pick(f"axisP[{i}]") or ""
            m[f"pid_p_{axis}"] = pick(f"axisP[{i}]") or ""
            m[f"d_err_{axis}"] = pick(f"axisD[{i}]") or ""
            m[f"debug_{axis}"] = pick(f"debug[{i}]") or ""
        m["throttle"] = pick("rcCommand[3]", "rcCommand[2]") or ""
        for j in range(8):
            k = f"motor[{j}]"
            if k in cols:
                m[f"motor_{j}"] = k
        m["vbat"] = pick("vbatLatest", "vbat", "VBat", "vbatCellVoltage") or ""
        return m
