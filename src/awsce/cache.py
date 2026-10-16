"""A small JSON file cache, so repeated queries do not call AWS again.

Cost Explorer charges per request, so caching saves money as well as time.
Files are readable only by the current user because they contain account IDs
and cost data.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def default_cache_dir() -> Path:
    if env := os.environ.get("AWSCE_CACHE_DIR"):
        return Path(env)
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "awsce"


@dataclass
class CacheEntry:
    key: str
    kind: str
    created: float
    size: int


class FileCache:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or default_cache_dir()

    @staticmethod
    def make_key(kind: str, **params: Any) -> str:
        raw = json.dumps(params, sort_keys=True, default=str)
        return f"{kind}-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str, max_age_hours: float) -> Any | None:
        path = self._path(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if time.time() - float(payload.get("created", 0)) > max_age_hours * 3600:
            return None
        return payload.get("data")

    def set(self, key: str, data: Any) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self._path(key)
        payload = json.dumps({"created": time.time(), "data": data}, default=str)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)

    def entries(self) -> list[CacheEntry]:
        if not self.directory.exists():
            return []
        result = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                created = float(json.loads(path.read_text(encoding="utf-8")).get("created", 0))
            except (OSError, ValueError):
                created = path.stat().st_mtime
            result.append(
                CacheEntry(
                    key=path.stem,
                    kind=path.stem.rsplit("-", 1)[0],
                    created=created,
                    size=path.stat().st_size,
                )
            )
        return result

    def clear(self, older_than_days: float | None = None) -> int:
        removed = 0
        cutoff = time.time() - older_than_days * 86400 if older_than_days is not None else None
        for entry in self.entries():
            if cutoff is None or entry.created < cutoff:
                self._path(entry.key).unlink(missing_ok=True)
                removed += 1
        return removed
