# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""LLM flight analysis via Spark Qwen twin (OpenAI-compatible HTTP, stdlib urllib)."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List

DEFAULT_TWIN = "http://100.114.179.3:30003/v1/chat/completions"
_raw = os.environ.get("FLIGHTFORGE_TWIN_URL", DEFAULT_TWIN).rstrip("/")
if _raw.endswith("/chat/completions"):
    TWIN_URL = _raw
elif _raw.endswith("/v1"):
    TWIN_URL = _raw + "/chat/completions"
else:
    TWIN_URL = _raw + "/v1/chat/completions"
MODEL = os.environ.get("FLIGHTFORGE_TWIN_MODEL", "flight-tuning")
FALLBACK_MODEL = os.environ.get("FLIGHTFORGE_TWIN_FALLBACK_MODEL", "analytical")
LLM_HTTP_TIMEOUT = float(os.environ.get("FLIGHTFORGE_LLM_TIMEOUT", "90"))

SYSTEM_PROMPT = """You are FlightForge, an expert FPV drone tuning assistant.
You analyze flight data (FFT noise profiles, step responses, PID traces) and
recommend specific Betaflight CLI changes to improve flight performance.

Your recommendations must be:
1. Specific — exact CLI commands, not vague advice
2. Reasoned — explain WHY each change helps, referencing the data
3. Conservative — change one thing at a time, small increments
4. Safe — never recommend changes that could cause flyaways or desync

Respond with ONLY a single JSON object (no markdown fences), keys:
flight_score (0-100 number),
issues_found (array of strings),
recommendations (array of objects with cli_command and reason strings),
reasoning (string),
next_flight_focus (string).
Optionally include cli_commands as an array of strings mirroring recommendations[].cli_command."""


def _post_chat(model: str, user_text: str, timeout: float | None = None) -> str:
    if timeout is None:
        timeout = LLM_HTTP_TIMEOUT
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": 1200,
        "temperature": 0.3,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        TWIN_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("no choices in LLM response")
    msg = choices[0].get("message") or {}
    content = msg.get("content") or ""
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        content = "".join(parts)
    return str(content)


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    i = text.find("{")
    j = text.rfind("}")
    if i >= 0 and j > i:
        return json.loads(text[i : j + 1])
    raise json.JSONDecodeError("no json object", text, 0)


def analyze_flight(
    signal_data: Dict[str, Any],
    flight_history: List[Dict[str, Any]],
    current_config: Dict[str, Any],
) -> Dict[str, Any]:
    """Send structured flight summary to twin; return parsed JSON dict."""
    prompt = f"""Analyze this flight:

Signal Analysis:
{json.dumps(signal_data, indent=2)}

Current PID / config snapshot:
{json.dumps(current_config, indent=2)}

Recent flight history (most recent last, metadata only):
{json.dumps(flight_history[-5:], indent=2)}

Recommend specific tuning changes. Be conservative."""

    last_err: str | None = None
    for model in (MODEL, FALLBACK_MODEL):
        try:
            raw = _post_chat(model, prompt, LLM_HTTP_TIMEOUT)
            out = _extract_json(raw)
            out["_model"] = model
            return out
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError, KeyError) as e:
            last_err = str(e)
            continue
    return {"error": last_err or "unknown", "flight_score": 0, "recommendations": [], "issues_found": [], "reasoning": ""}
