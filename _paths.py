# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Resolve import paths for vendored orangebox (GPL-3.0 upstream; FlightForge is Apache-2.0)."""

from __future__ import annotations

import sys
from pathlib import Path

_FLIGHTFORGE_ROOT = Path(__file__).resolve().parent
_ORANGEBOX_REPO = _FLIGHTFORGE_ROOT / "orangebox_repo"


def ensure_orangebox_path() -> None:
    """Add orangebox repository root so `import orangebox` works."""
    repo = _ORANGEBOX_REPO.resolve()
    if repo.is_dir():
        s = str(repo)
        if s not in sys.path:
            sys.path.insert(0, s)
