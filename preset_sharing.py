# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Community preset export/import using the same local Chroma store (no cloud LLM)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

import chromadb

from flight_store import CHROMA_DIR, _HashEmbedding
from wizard import WizardState


class PresetSharing:
    def __init__(self) -> None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self._col = self._client.get_or_create_collection(
            name="presets",
            embedding_function=_HashEmbedding(),
        )

    def export_preset(self, wizard_state: WizardState, quad_profile: Dict[str, Any]) -> Dict[str, Any]:
        pid = hashlib.sha256(json.dumps(quad_profile, sort_keys=True).encode()).hexdigest()[:16]
        doc = {
            "wizard": wizard_state.to_dict(),
            "quad": quad_profile,
            "style": quad_profile.get("style", "freestyle"),
        }
        self._col.add(
            ids=[pid],
            documents=[json.dumps(doc)],
            metadatas=[
                {
                    "frame": str(quad_profile.get("frame", "")),
                    "kv": str(quad_profile.get("motor_kv", "")),
                    "cells": str(quad_profile.get("cells", "")),
                    "style": str(quad_profile.get("style", "")),
                }
            ],
        )
        return {"preset_id": pid, "stored": True}

    def import_preset(self, preset_id: str) -> Dict[str, Any]:
        g = self._col.get(ids=[preset_id], include=["documents"])
        if not g["ids"]:
            raise KeyError(preset_id)
        return json.loads(g["documents"][0])

    def search_presets(self, quad_specs: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Structured match on metadata (no neural embedding)."""
        hits: List[Dict[str, Any]] = []
        allp = self._col.get(include=["metadatas", "documents"], limit=500)
        for i, mid in enumerate(allp["ids"]):
            md = allp["metadatas"][i] or {}
            score = 0
            if quad_specs.get("cells") and str(md.get("cells")) == str(quad_specs.get("cells")):
                score += 2
            if quad_specs.get("motor_kv") and str(md.get("kv")) == str(quad_specs.get("motor_kv")):
                score += 2
            if quad_specs.get("frame") and str(md.get("frame")) == str(quad_specs.get("frame")):
                score += 1
            if score:
                hits.append({"preset_id": mid, "score": score, "meta": md})
        hits.sort(key=lambda x: -x["score"])
        return hits[:20]

    def rate_preset(self, preset_id: str, score: float, notes: str) -> None:
        cur = self._col.get(ids=[preset_id], include=["metadatas"])
        if not cur["ids"]:
            raise KeyError(preset_id)
        md = dict(cur["metadatas"][0] or {})
        md["rating"] = float(score)
        md["notes"] = notes[:500]
        self._col.update(ids=[preset_id], metadatas=[md])
