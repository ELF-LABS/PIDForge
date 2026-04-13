# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Blackbox signal analysis: step response (PID-Analyzer), FFT, motors, battery."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import signal as scipy_signal

from config_parser import extract_pid_from_headers
from ingestor import FlightLog
from pid_trace import Trace, build_trace_dict


def _series(df: pd.DataFrame, col: str, fallback: float = 0.0) -> np.ndarray:
    if not col or col not in df.columns:
        return np.full(len(df), fallback, dtype=np.float64)
    return pd.to_numeric(df[col], errors="coerce").fillna(fallback).to_numpy(dtype=np.float64)


class SignalAnalyzer:
    def __init__(self, df: pd.DataFrame, sample_rate: int = 500, headers: Optional[Dict[str, Any]] = None):
        self.df = df
        self.fs = sample_rate
        self.headers = headers or {}

    @classmethod
    def from_flight_log(cls, fl: FlightLog) -> "SignalAnalyzer":
        fs = _guess_fs(fl.df)
        return cls(fl.df, fs, fl.headers)

    def _axis_trace(self, axis: str) -> Optional[Trace]:
        """Build PID-Analyzer Trace for roll/pitch/yaw if columns exist."""
        al = self._aliases_for_df(self.df)
        time_col = "time_s" if "time_s" in self.df.columns else None
        if time_col is None:
            return None
        t = _series(self.df, time_col)
        if len(t) < 256:
            return None
        idx = {"roll": 0, "pitch": 1, "yaw": 2}[axis]
        gyro_c = al.get(f"gyro_{axis}", "")
        perr_c = al.get(f"p_err_{axis}", "")
        if not gyro_c or not perr_c:
            return None
        g = _series(self.df, gyro_c)
        pe = _series(self.df, perr_c)
        thr_c = al.get("throttle", "")
        th = _series(self.df, thr_c, 0.0) if thr_c else np.zeros_like(t)
        d_c = al.get(f"d_err_{axis}", "")
        d_err = _series(self.df, d_c) if d_c else np.zeros_like(t)
        db_c = al.get(f"debug_{axis}", "")
        dbg = _series(self.df, db_c) if db_c else np.zeros_like(t)
        pid = extract_pid_from_headers(self.headers).get(axis, (45.0, 80.0, 30.0))
        p_gain = float(pid[0])
        data = build_trace_dict(axis, t, g, pe, p_gain, th, d_err, dbg)
        try:
            return Trace(data)
        except Exception:
            return None

    @staticmethod
    def _aliases_for_df(df: pd.DataFrame) -> Dict[str, str]:
        cols = set(df.columns)
        m: Dict[str, str] = {}

        def pick(*cands: str) -> str:
            for c in cands:
                if c in cols:
                    return c
            return ""

        for i, axis in enumerate(("roll", "pitch", "yaw")):
            m[f"gyro_{axis}"] = pick(f"gyroADC[{i}]", f"gyro[{i}]")
            m[f"p_err_{axis}"] = pick(f"axisP[{i}]")
            m[f"d_err_{axis}"] = pick(f"axisD[{i}]")
            m[f"debug_{axis}"] = pick(f"debug[{i}]")
        m["throttle"] = pick("rcCommand[3]", "rcCommand[2]")
        m["vbat"] = pick("vbatLatest", "vbat", "VBat")
        for j in range(8):
            k = f"motor[{j}]"
            if k in cols:
                m[f"motor_{j}"] = k
        return m

    def step_response(self, axis: str = "roll") -> Dict[str, Any]:
        tr = self._axis_trace(axis)
        if tr is None:
            return {"ok": False, "reason": "insufficient_data"}
        curve = tr.resp_low[0]
        peak = float(np.max(curve)) if curve.size else 0.0
        overshoot_pct = max(0.0, (peak - 1.0) * 100.0) if peak > 1.0 else 0.0
        # rise: first crossing 90% of peak
        target = peak * 0.9 if peak > 0 else 1.0
        rise_idx = int(np.argmax(curve >= target)) if curve.size else 0
        rise_time_ms = float(tr.time_resp[min(rise_idx, len(tr.time_resp) - 1)] * 1000.0)
        settle_thresh = 0.05
        settle_idx = len(curve) - 1
        for i in range(len(curve) - 1, -1, -1):
            if abs(curve[i] - 1.0) > settle_thresh:
                settle_idx = min(i + 1, len(curve) - 1)
                break
        settling_time_ms = float(tr.time_resp[settle_idx] * 1000.0)
        err = curve - 1.0
        tracking_error_rms = float(np.sqrt(np.mean(err**2)))
        return {
            "ok": True,
            "rise_time_ms": rise_time_ms,
            "overshoot_pct": overshoot_pct,
            "settling_time_ms": settling_time_ms,
            "tracking_error_rms": tracking_error_rms,
            "time_resp": tr.time_resp.tolist(),
            "curve": curve.tolist(),
        }

    def noise_fft(self, axis: str = "roll") -> Dict[str, Any]:
        tr = self._axis_trace(axis)
        if tr is None:
            return {"ok": False}
        fa = np.asarray(tr.noise_gyro["freq_axis"], dtype=np.float64)
        meanspec = np.asarray(tr.noise_gyro["hist2d_sm"].mean(axis=1), dtype=np.float64)
        nbin = min(fa.size, meanspec.size) - 1
        if nbin < 2:
            return {"ok": False}
        fa_u = fa[:nbin]
        mags = np.abs(meanspec[:nbin]) + 1e-12
        mags_db = 20.0 * np.log10(mags / (np.median(mags) + 1e-12))
        noise_floor_db = float(np.percentile(mags_db, 10))
        peaks: List[Dict[str, Any]] = []
        for lo, hi, label in (
            (30, 80, "frame_flex"),
            (80, 200, "prop_resonance"),
            (100, 400, "motor_noise"),
        ):
            mask = (fa_u >= lo) & (fa_u < hi)
            if mask.any():
                sub = mags_db[mask]
                fi = int(np.arange(len(mags_db))[mask][int(np.argmax(sub))])
                peaks.append({"hz": float(fa_u[fi]), "db": float(mags_db[fi]), "label": label})
        return {
            "ok": True,
            "frequencies": fa_u.tolist(),
            "magnitudes_db": mags_db.tolist(),
            "noise_floor_db": noise_floor_db,
            "peaks": peaks,
        }

    def filter_effectiveness(self, df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        d = df if df is not None else self.df
        tr = self._axis_trace("roll")
        if tr is None or tr.filter_trans.size < 4:
            return {"ok": False, "attenuation_db": 0.0, "phase_note": "need debug + gyro traces"}
        att = float(np.clip(np.nanmean(tr.filter_trans) * 20.0, 0.0, 40.0))
        return {"ok": True, "attenuation_db": att, "phase_note": "approximate from gyro/debug spectrogram ratio"}

    def motor_analysis(self) -> Dict[str, Any]:
        motors = []
        for j in range(8):
            c = f"motor[{j}]"
            if c in self.df.columns:
                motors.append(_series(self.df, c))
        if len(motors) < 2:
            return {"ok": False, "reason": "no motor columns"}
        M = np.stack(motors, axis=1)
        mx = np.max(np.abs(M), axis=1) + 1e-6
        sat = float(np.mean(mx >= 1999))
        mean_per = M.mean(axis=0)
        bal = (mean_per / (np.mean(mean_per) + 1e-6)).tolist()
        imbalance_pct = float((np.max(mean_per) - np.min(mean_per)) / (np.mean(mean_per) + 1e-6) * 100.0)
        al = self._aliases_for_df(self.df)
        gyro = _series(self.df, al.get("gyro_roll", ""))
        desync = int(np.sum((mx >= 1900) & (np.abs(gyro) > 200))) if gyro.size == mx.size else 0
        return {"ok": True, "saturation_pct": sat * 100.0, "balance": bal, "imbalance_pct": imbalance_pct, "desync_events": desync}

    def battery_analysis(self) -> Dict[str, Any]:
        al = self._aliases_for_df(self.df)
        vb = al.get("vbat") or ""
        if not vb or vb not in self.df.columns:
            return {"ok": False}
        v = _series(self.df, vb)
        if v.size < 10:
            return {"ok": False}
        cells = float(self.headers.get("vbatcellcount", self.headers.get("vbatCellCount", 4)) or 4)
        if cells <= 0:
            cells = 4.0
        per_cell = v / cells
        sag = float((np.percentile(v, 95) - np.percentile(v, 5)) / max(cells, 1.0))
        low_cell = float(np.min(per_cell) / 1000.0) if np.max(v) > 200 else float(np.min(per_cell))
        tune_risk = low_cell < 3.5
        return {
            "ok": True,
            "sag_volts_per_cell": sag / 1000.0 if np.max(v) > 200 else sag,
            "min_cell_v": low_cell,
            "tune_degraded_below_3p5v_per_cell": tune_risk,
        }

    def propwash_analysis(self) -> Dict[str, Any]:
        al = self._aliases_for_df(self.df)
        thr_c, gy_c = al.get("throttle", ""), al.get("gyro_pitch", "")
        if not thr_c or not gy_c:
            return {"ok": False}
        thr = _series(self.df, thr_c)
        gy = _series(self.df, gy_c)
        dthr = np.abs(np.diff(thr, prepend=thr[0]))
        chop = dthr > np.percentile(dthr, 95)
        if chop.sum() < 5:
            return {"ok": True, "propwash_magnitude": 0.0, "recovery_time_ms": 0.0}
        seg = gy[chop]
        f, psd = scipy_signal.welch(seg, fs=float(self.fs), nperseg=min(256, len(seg)))
        band = (f >= 50) & (f <= 150)
        mag = float(np.sum(psd[band])) if band.any() else 0.0
        return {"ok": True, "propwash_magnitude": mag, "recovery_time_ms": 0.0}

    def compare(self, previous: "SignalAnalyzer") -> Dict[str, Any]:
        out: Dict[str, Any] = {"improved": [], "degraded": [], "delta": {}}
        for ax in ("roll", "pitch"):
            a = self.step_response(ax)
            b = previous.step_response(ax)
            if not a.get("ok") or not b.get("ok"):
                continue
            do = a["overshoot_pct"] - b["overshoot_pct"]
            out["delta"][f"overshoot_{ax}"] = do
            if do < -1:
                out["improved"].append(f"{ax} overshoot down by {-do:.1f}%")
            elif do > 1:
                out["degraded"].append(f"{ax} overshoot up by {do:.1f}%")
        return out

    def full_analysis(self) -> Dict[str, Any]:
        scores = []
        parts = {}
        for ax in ("roll", "pitch", "yaw"):
            sr = self.step_response(ax)
            parts[f"step_{ax}"] = sr
            if sr.get("ok"):
                s = 100.0
                if sr["overshoot_pct"] > 25:
                    s -= 25
                elif sr["overshoot_pct"] > 20:
                    s -= 15
                if sr["settling_time_ms"] > 250:
                    s -= 15
                scores.append(max(s, 0.0))
        fft_r = self.noise_fft("roll")
        parts["fft_roll"] = fft_r
        parts["motor"] = self.motor_analysis()
        parts["battery"] = self.battery_analysis()
        parts["propwash"] = self.propwash_analysis()
        overall = float(np.mean(scores)) if scores else 50.0
        return {"overall_score": overall, "parts": parts}


def _guess_fs(df: pd.DataFrame) -> int:
    if "time_s" not in df.columns or len(df) < 8:
        return 500
    dt = float(df["time_s"].diff().median())
    if dt <= 0:
        return 500
    return int(round(1.0 / dt))
