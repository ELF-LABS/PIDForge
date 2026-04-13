# Copyright (c) 2026 ELF Labs (Emmelina Luna Fugler)
#
# SPDX-License-Identifier: Apache-2.0
"""Local BFL cache + ChromaDB-backed flight history (no cloud LLM)."""

from __future__ import annotations

import hashlib
import json
import uuid
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings

CACHE_DIR = Path("~/flightforge/logs").expanduser()
CHROMA_DIR = Path("~/flightforge/chroma_db").expanduser()
MAX_CACHED_FLIGHTS = 50


class _HashEmbedding(EmbeddingFunction[Documents]):
    """Deterministic 8-D embedding from document text (no external models)."""

    def __call__(self, input: Documents) -> Embeddings:
        out: Embeddings = []
        for t in input:
            h = hashlib.sha256(t.encode("utf-8", errors="replace")).digest()
            out.append([x / 255.0 for x in h[:8]])
        return out


class FlightStore:
    """Local cache + ChromaDB history."""

    def __init__(self, quad_name: str = "default_quad") -> None:
        self.quad_name = quad_name
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self._flights = self._client.get_or_create_collection(
            name="flights",
            embedding_function=_HashEmbedding(),
        )

    def _quad_dir(self) -> Path:
        d = CACHE_DIR / self.quad_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def detect_new_logs(self, fc_connection: Any) -> List[Path]:
        """Placeholder: without MSCP log listing, return empty; USB copy workflow uses cache scan."""
        _ = fc_connection
        return []

    def cache_flight(self, bfl_path: str, quad_name: str, session: int) -> Dict[str, Any]:
        self.quad_name = quad_name
        src = Path(bfl_path)
        if not src.is_file():
            raise FileNotFoundError(bfl_path)
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dest_dir = self._quad_dir() / day
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        flight_id = str(uuid.uuid4())[:12]
        meta = {
            "flight_id": flight_id,
            "quad": quad_name,
            "date": day,
            "session": session,
            "path": str(dest),
            "analysis_complete": False,
        }
        sidecar = dest.with_suffix(dest.suffix + ".meta.json")
        sidecar.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        self._flights.add(
            ids=[flight_id],
            documents=[json.dumps({"quad": quad_name, "path": str(dest), "day": day})],
            metadatas=[{"quad": quad_name, "day": day, "session": session}],
        )
        return meta

    def get_previous_flight(self, quad_name: str) -> Optional[Dict[str, Any]]:
        res = self._flights.get(where={"quad": quad_name}, include=["metadatas", "documents"], limit=120)
        if not res["ids"]:
            return None
        last = res["metadatas"][-1]
        last["document"] = res["documents"][-1]
        return last

    def recent_flights(self, quad_name: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Most recent first (best-effort ordering from Chroma get)."""
        lim = max(1, min(int(limit), 500))
        res = self._flights.get(where={"quad": quad_name}, include=["metadatas", "documents"], limit=lim)
        ids_ = res.get("ids") or []
        mds = res.get("metadatas") or []
        docs = res.get("documents") or []
        out: List[Dict[str, Any]] = []
        for i, fid in enumerate(ids_):
            row: Dict[str, Any] = {"id": fid, "flight_id": fid}
            if i < len(mds) and mds[i]:
                row.update(dict(mds[i]))
            if i < len(docs) and docs[i]:
                row["document"] = docs[i]
            out.append(row)
        out.reverse()
        return out

    def merge_flight_metadata(self, flight_id: str, extra: Dict[str, Any]) -> None:
        """Merge keys into Chroma metadata (nested values JSON-serialized)."""
        cur = self._flights.get(ids=[flight_id], include=["metadatas"])
        if not cur["ids"]:
            return
        md = dict(cur["metadatas"][0] or {})
        for k, v in extra.items():
            ks = str(k)
            if isinstance(v, (dict, list)):
                md[ks] = json.dumps(v, separators=(",", ":"), default=str)
            elif v is None:
                continue
            elif isinstance(v, bool):
                md[ks] = "true" if v else "false"
            elif isinstance(v, (int, float)):
                md[ks] = float(v) if isinstance(v, float) else int(v)
            else:
                md[ks] = str(v)
        self._flights.update(ids=[flight_id], metadatas=[md])

    def get_trend(self, quad_name: str, metric: str) -> List[float]:
        res = self._flights.get(where={"quad": quad_name}, include=["metadatas"], limit=200)
        vals = []
        for m in res.get("metadatas") or []:
            if m and metric in m:
                try:
                    vals.append(float(m[metric]))
                except (TypeError, ValueError):
                    pass
        return vals

    def record_metric(self, flight_id: str, metric: str, value: float) -> None:
        cur = self._flights.get(ids=[flight_id], include=["metadatas"])
        if not cur["ids"]:
            return
        md = dict(cur["metadatas"][0] or {})
        md[metric] = value
        self._flights.update(ids=[flight_id], metadatas=[md])

    def cleanup(self, quad_name: str) -> None:
        root = CACHE_DIR / quad_name
        if not root.is_dir():
            return
        bfls = sorted(root.rglob("*.BFL")) + sorted(root.rglob("*.bfl")) + sorted(root.rglob("*.BBL")) + sorted(
            root.rglob("*.bbl")
        )
        if len(bfls) <= MAX_CACHED_FLIGHTS:
            return
        old = bfls[: -MAX_CACHED_FLIGHTS]
        zpath = root / "archive_old_logs.zip"
        with zipfile.ZipFile(zpath, "a", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in old:
                zf.write(p, arcname=str(p.relative_to(root)))
                p.unlink(missing_ok=True)
                meta = p.with_suffix(p.suffix + ".meta.json")
                meta.unlink(missing_ok=True)

    @staticmethod
    def config_changed(current_hash: str, previous_hash: str) -> bool:
        return bool(current_hash and previous_hash and current_hash != previous_hash)
