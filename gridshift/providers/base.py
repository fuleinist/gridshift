"""Shared provider helpers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx


class ProviderError(RuntimeError):
    """A public data source could not be read."""


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    timeout: float = 25.0,
    retries: int = 2,
) -> Any:
    """GET a JSON document with a small retry budget."""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = httpx.get(
                url,
                params=params,
                timeout=timeout,
                headers={"User-Agent": "gridshift/0.1 (+https://github.com/fuleinist/gridshift)"},
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # noqa: BLE001 - provider errors differ
            last_error = exc
            if attempt < retries:
                time.sleep(0.4 * (attempt + 1))
    raise ProviderError(f"request failed: {url} ({last_error})") from last_error


class Cache:
    """Tiny SQLite cache for provider payloads. Safe to share between threads."""

    def __init__(self, path: str | Path):
        import sqlite3
        import threading

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS payloads (key TEXT PRIMARY KEY, fetched_at REAL, body TEXT)"
        )
        self._conn.commit()

    def get(self, key: str, max_age_s: float = 3600.0) -> Any | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT fetched_at, body FROM payloads WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        fetched_at, body = row
        if time.time() - fetched_at > max_age_s:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None

    def put(self, key: str, payload: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO payloads (key, fetched_at, body) VALUES (?, ?, ?)",
                (key, time.time(), json.dumps(payload)),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()