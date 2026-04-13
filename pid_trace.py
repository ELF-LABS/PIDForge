# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
#
# Step-response / spectrogram math adapted from PID-Analyzer (Florian Melsheimer,
# Beer-Ware License). See /home/luna/staging/PID-Analyzer/PID-Analyzer.py — ported
# for Python 3.12 + NumPy 2 (no LLM).

from __future__ import annotations

import numpy as np
from scipy.interpolate import interp1d
from scipy.ndimage import gaussian_filter1d


class Trace:
    framelen = 1.0
    resplen = 0.5
    cutfreq = 25.0
    tuk_alpha = 1.0
    superpos = 16
    threshold = 500.0
    noise_framelen = 0.3
    noise_superpos = 16

    def __init__(self, data: dict):
        self.data = data
        pidp = float(data["P"])
        self.data["input"] = self.pid_in(data["p_err"], data["gyro"], pidp)
        self.equalize_data()

        self.name = str(data["name"])
        self.time = self.data["time"]
        self.dt = float(self.time[0] - self.time[1])
        self.input = self.data["input"]
        self.gyro = self.data["gyro"]
        self.throttle = self.data["throttle"]
        self.throt_hist, self.throt_scale = np.histogram(
            self.throttle, np.linspace(0, 100, 101, dtype=np.float64), density=True
        )

        self.flen = self.stepcalc(self.time, Trace.framelen)
        self.rlen = self.stepcalc(self.time, Trace.resplen)
        self.time_resp = self.time[0 : self.rlen] - self.time[0]

        self.stacks = self.winstacker(
            {"time": [], "input": [], "gyro": [], "throttle": []}, self.flen, Trace.superpos
        )
        self.window = np.hanning(self.flen)
        self.spec_sm, self.avr_t, self.avr_in, self.max_in, self.max_thr = self.stack_response(self.stacks, self.window)
        self.low_mask, self.high_mask = self.low_high_mask(self.max_in, self.threshold)
        self.toolow_mask = self.low_high_mask(self.max_in, 20)[1]

        self.resp_sm = self.weighted_mode_avr(self.spec_sm, self.toolow_mask, [-1.5, 3.5], 1000)
        self.resp_quality = -self.to_mask((np.abs(self.spec_sm - self.resp_sm[0]).mean(axis=1)).clip(0.5 - 1e-9, 0.5)) + 1.0
        self.thr_response = self.hist2d(
            self.max_thr * (2.0 * (self.toolow_mask * self.resp_quality) - 1.0),
            self.time_resp,
            (self.spec_sm.transpose() * self.toolow_mask).transpose(),
            [101, self.rlen],
        )

        self.resp_low = self.weighted_mode_avr(self.spec_sm, self.low_mask * self.toolow_mask, [-1.5, 3.5], 1000)
        if self.high_mask.sum() > 0:
            self.resp_high = self.weighted_mode_avr(self.spec_sm, self.high_mask * self.toolow_mask, [-1.5, 3.5], 1000)
        else:
            self.resp_high = self.resp_low

        self.noise_winlen = self.stepcalc(self.time, Trace.noise_framelen)
        self.noise_stack = self.winstacker(
            {"time": [], "gyro": [], "throttle": [], "d_err": [], "debug": []},
            self.noise_winlen,
            Trace.noise_superpos,
        )
        self.noise_win = np.hanning(self.noise_winlen)

        self.noise_gyro = self.stackspectrum(
            self.noise_stack["time"], self.noise_stack["throttle"], self.noise_stack["gyro"], self.noise_win
        )
        self.noise_d = self.stackspectrum(
            self.noise_stack["time"], self.noise_stack["throttle"], self.noise_stack["d_err"], self.noise_win
        )
        self.noise_debug = self.stackspectrum(
            self.noise_stack["time"], self.noise_stack["throttle"], self.noise_stack["debug"], self.noise_win
        )
        if self.noise_debug["hist2d"].sum() > 0:
            thr_mask = self.noise_gyro["throt_hist_avr"].clip(0, 1)
            self.filter_trans = np.average(self.noise_gyro["hist2d"], axis=1, weights=thr_mask) / (
                np.average(self.noise_debug["hist2d"], axis=1, weights=thr_mask) + 1e-9
            )
        else:
            self.filter_trans = self.noise_gyro["hist2d"].mean(axis=1) * 0.0

    @staticmethod
    def low_high_mask(signal: np.ndarray, threshold: float):
        low = np.copy(signal)
        low[low <= threshold] = 1.0
        low[low > threshold] = 0.0
        high = -low + 1.0
        if high.sum() < 10:
            high *= 0.0
        return low, high

    @staticmethod
    def to_mask(clipped: np.ndarray) -> np.ndarray:
        clipped = clipped - clipped.min()
        clipped = clipped / (clipped.max() + 1e-12)
        return clipped

    @staticmethod
    def pid_in(pval: np.ndarray, gyro: np.ndarray, pidp: float) -> np.ndarray:
        return gyro + pval / (0.032029 * pidp)

    def equalize_data(self) -> None:
        time = self.data["time"]
        newtime = np.linspace(time[0], time[-1], len(time), dtype=np.float64)
        for key in self.data:
            if isinstance(self.data[key], np.ndarray) and len(self.data[key]) == len(time):
                self.data[key] = interp1d(time, self.data[key], fill_value="extrapolate")(newtime)
        self.data["time"] = newtime

    def stepcalc(self, time: np.ndarray, duration: float) -> int:
        tstep = time[1] - time[0]
        freq = 1.0 / tstep
        return int(duration * freq)

    def winstacker(self, stackdict: dict, flen: int, superpos: int) -> dict:
        tlen = len(self.data["time"])
        shift = int(flen / superpos)
        wins = int(tlen / shift) - superpos
        for i in np.arange(max(wins, 0)):
            for key in stackdict:
                stackdict[key].append(self.data[key][i * shift : i * shift + flen])
        for k in stackdict:
            stackdict[k] = np.array(stackdict[k], dtype=np.float64)
        return stackdict

    def wiener_deconvolution(self, inp: np.ndarray, output: np.ndarray, cutfreq: float) -> np.ndarray:
        pad = 1024 - (len(inp[0]) % 1024)
        inp = np.pad(inp, [[0, 0], [0, pad]], mode="constant")
        output = np.pad(output, [[0, 0], [0, pad]], mode="constant")
        H = np.fft.fft(inp, axis=-1)
        G = np.fft.fft(output, axis=-1)
        freq = np.abs(np.fft.fftfreq(len(inp[0]), self.dt))
        sn = self.to_mask(np.clip(np.abs(freq), cutfreq - 1e-9, cutfreq))
        len_lpf = int(np.sum(np.ones_like(sn) - sn))
        sn = self.to_mask(gaussian_filter1d(sn, max(len_lpf // 6, 1)))
        sn = 10.0 * (-sn + 1.0 + 1e-9)
        Hcon = np.conj(H)
        return np.real(np.fft.ifft(G * Hcon / (H * Hcon + 1.0 / sn), axis=-1))

    def stack_response(self, stacks: dict, window: np.ndarray):
        inp = stacks["input"] * window
        outp = stacks["gyro"] * window
        thr = stacks["throttle"] * window
        deconvolved_sm = self.wiener_deconvolution(inp, outp, self.cutfreq)[:, : self.rlen]
        delta_resp = deconvolved_sm.cumsum(axis=1)
        max_thr = np.abs(np.abs(thr)).max(axis=1)
        avr_in = np.abs(np.abs(inp)).mean(axis=1)
        max_in = np.max(np.abs(inp), axis=1)
        avr_t = stacks["time"].mean(axis=1)
        return delta_resp, avr_t, avr_in, max_in, max_thr

    def spectrum(self, time: np.ndarray, traces: np.ndarray):
        pad = 1024 - (len(traces[0]) % 1024)
        traces = np.pad(traces, [[0, 0], [0, pad]], mode="constant")
        trspec = np.fft.rfft(traces, axis=-1, norm="ortho")
        trfreq = np.fft.rfftfreq(len(traces[0]), time[1] - time[0])
        return trfreq, trspec

    def hist2d(self, x: np.ndarray, y: np.ndarray, weights: np.ndarray, bins):
        freqs = np.repeat(np.array([y], dtype=np.float64), len(x), axis=0)
        throts = np.repeat(np.array([x], dtype=np.float64), len(y), axis=0).transpose()
        throt_hist_avr, throt_scale_avr = np.histogram(x, 101, range=(0, 100))
        hist2d, _, _ = np.histogram2d(
            throts.flatten(),
            freqs.flatten(),
            range=[[0, 100], [y[0], y[-1]]],
            bins=bins,
            weights=weights.flatten(),
            density=False,
        )
        hist2d = np.array(np.abs(hist2d), dtype=np.float64).transpose()
        hist2d_norm = np.copy(hist2d)
        hist2d_norm /= throt_hist_avr + 1e-9
        return {"hist2d_norm": hist2d_norm, "hist2d": hist2d, "throt_hist": throt_hist_avr, "throt_scale": throt_scale_avr}

    def stackspectrum(self, time: np.ndarray, throttle: np.ndarray, trace: np.ndarray, window: np.ndarray):
        cut = int(Trace.noise_superpos * 2.0 / Trace.noise_framelen)
        gyro = trace[:-cut, :] * window if cut else trace * window
        thr = throttle[:-cut, :] * window if cut else throttle * window
        time = time[:-cut, :] if cut else time
        freq, spec = self.spectrum(time[0], gyro)
        weights = np.abs(spec.real)
        avr_thr = np.abs(thr).max(axis=1)
        hist2d = self.hist2d(avr_thr, freq, weights, [101, len(freq) // 4])
        filt_width = 3
        hist2d_sm = gaussian_filter1d(hist2d["hist2d_norm"], filt_width, axis=1, mode="constant")
        thresh = 100.0
        mask = self.to_mask(freq[:-1:4].clip(thresh - 1e-9, thresh))
        maxval = np.max(hist2d_sm.transpose() * mask) if mask.size else 0.0
        return {
            "throt_hist_avr": hist2d["throt_hist"],
            "throt_axis": hist2d["throt_scale"],
            "freq_axis": freq[::4],
            "hist2d_norm": hist2d["hist2d_norm"],
            "hist2d_sm": hist2d_sm,
            "hist2d": hist2d["hist2d"],
            "max": maxval,
        }

    def weighted_mode_avr(self, values: np.ndarray, weights: np.ndarray, vertrange: list, vertbins: int):
        threshold = 0.5
        filt_width = 7
        resp_y = np.linspace(vertrange[0], vertrange[-1], vertbins, dtype=np.float64)
        times = np.repeat(np.array([self.time_resp], dtype=np.float64), len(values), axis=0)
        weights = np.repeat(weights, len(values[0]))
        hist2d, _, _ = np.histogram2d(
            times.flatten(),
            values.flatten(),
            range=[[self.time_resp[0], self.time_resp[-1]], vertrange],
            bins=[len(times[0]), vertbins],
            weights=weights.flatten(),
            density=False,
        )
        hist2d = hist2d.transpose()
        if hist2d.sum():
            hist2d_sm = gaussian_filter1d(hist2d, filt_width, axis=0, mode="constant")
            hist2d_sm /= np.max(hist2d_sm, 0) + 1e-12
            pixelpos = np.repeat(resp_y.reshape(len(resp_y), 1), len(times[0]), axis=1)
            avr = np.average(pixelpos, 0, weights=hist2d_sm * hist2d_sm)
        else:
            hist2d_sm = hist2d
            avr = np.zeros_like(self.time_resp)
        hist2d[hist2d <= threshold] = 0.0
        hist2d[hist2d > threshold] = 0.5 / (vertbins / (vertrange[-1] - vertrange[0]))
        std = np.sum(hist2d, 0)
        return avr, std, [self.time_resp, resp_y, hist2d_sm]


def build_trace_dict(
    name: str,
    time_s: np.ndarray,
    gyro: np.ndarray,
    p_err: np.ndarray,
    p_gain: float,
    throttle_pct: np.ndarray,
    d_err: np.ndarray,
    debug: np.ndarray,
) -> dict:
    return {
        "name": name,
        "time": time_s.astype(np.float64),
        "gyro": gyro.astype(np.float64),
        "p_err": p_err.astype(np.float64),
        "P": float(p_gain),
        "throttle": throttle_pct.astype(np.float64),
        "d_err": d_err.astype(np.float64),
        "debug": debug.astype(np.float64),
    }
