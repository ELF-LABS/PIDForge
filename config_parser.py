# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Parse CLI snippets from BFL headers and emit paste-ready diffs."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


def config_hash_from_headers(headers: Mapping[str, Any]) -> str:
    """Stable hash of tune-relevant header keys for change detection."""
    keys = sorted(headers.keys())
    blob = json.dumps({k: headers.get(k) for k in keys}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def extract_cli_kv(headers: Mapping[str, Any]) -> Dict[str, str]:
    """Best-effort map of CLI-like keys from blackbox headers (strings)."""
    out: Dict[str, str] = {}
    for k, v in headers.items():
        if isinstance(v, (list, tuple)):
            out[str(k)] = ",".join(str(x) for x in v)
        else:
            out[str(k)] = str(v)
    return out


def parse_cli_text(text: str) -> Dict[str, str]:
    """Parse ``set name value`` / ``name value`` lines from pasted CLI."""
    cfg: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("set "):
            line = line[4:].strip()
        m = re.match(r"^([A-Za-z0-9_]+)\s+(.+)$", line)
        if m:
            cfg[m.group(1)] = m.group(2).strip()
    return cfg


def cli_diff(updates: Mapping[str, Any], comment: str = "FlightForge") -> str:
    """Generate paste-ready ``set`` lines."""
    lines = [f"# {comment}"]
    for k, v in updates.items():
        lines.append(f"set {k} {v}")
    lines.append("save")
    return "\n".join(lines) + "\n"


def extract_pid_from_headers(headers: Mapping[str, Any]) -> Dict[str, Tuple[int, int, int]]:
    """Read roll/pitch/yaw PID triples from headers if present (Betaflight CSV header style)."""
    res: Dict[str, Tuple[int, int, int]] = {}
    for axis in ("roll", "pitch", "yaw"):
        key = f"{axis}PID"
        if key not in headers:
            continue
        val = headers[key]
        if isinstance(val, str):
            sep = "/" if "/" in val else ","
            parts = [int(float(x)) for x in val.split(sep) if x.strip()]
        elif isinstance(val, (list, tuple)):
            parts = [int(float(x)) for x in val]
        else:
            continue
        if len(parts) >= 3:
            res[axis] = (parts[0], parts[1], parts[2])
    return res
