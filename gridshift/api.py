"""Local web UI and JSON API. Standard library only."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .appliances import default_loads
from .engine import make_plan, plan_dict, ranked
from .providers.base import Cache, ProviderError
from .providers.tariff import TariffConfig
from .solver import Weights
from .sources import GB_TZ, build_slots, postcode_lookup

ROOT = Path(__file__).parent
CACHE_FILE = Path.home() / ".cache" / "gridshift" / "cache.sqlite"
_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache(CACHE_FILE)
    return _cache


def reset_cache(path: Path | None = None) -> None:
    global _cache, CACHE_FILE
    if path is not None:
        CACHE_FILE = path
    if _cache is not None:
        _cache.close()
    _cache = None


def _number(params: dict[str, str], name: str, default: float, lo: float, hi: float) -> float:
    raw = params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}")
    return value


def _flag(params: dict[str, str], name: str, default: bool = True) -> bool:
    raw = params.get(name)
    if raw is None:
        return default
    return raw.lower() not in {"0", "false", "no", "off"}


def plan_payload(params: dict[str, str]) -> dict:
    lat = _number(params, "lat", 51.5074, -90, 90)
    lon = _number(params, "lon", -0.1278, -180, 180)
    postcode = params.get("postcode", "").strip()
    if postcode:
        try:
            lat, lon = postcode_lookup(postcode)
        except ProviderError as exc:
            raise ValueError(str(exc)) from exc

    hours = _number(params, "hours", 24.0, 2, 48)
    carbon_weight = _number(params, "carbon_weight", 0.6, 0, 1)
    price_weight = _number(params, "price_weight", 0.4, 0, 1)
    if carbon_weight + price_weight <= 0:
        raise ValueError("at least one weight must be positive")
    solar_kwp = _number(params, "solar_kwp", 0.0, 0, 50)
    max_load_kw = _number(params, "max_load_kw", 8.0, 0.1, 100)
    source = params.get("source", "auto")
    if source not in {"auto", "neso", "demo"}:
        raise ValueError("source must be auto, neso or demo")
    tz = params.get("tz", GB_TZ)

    try:
        slots, meta = build_slots(
            lat,
            lon,
            hours=hours,
            source=source,
            tariff=TariffConfig(),
            tz=tz,
            cache=get_cache(),
        )
    except ProviderError as exc:
        raise RuntimeError(str(exc)) from exc

    loads = default_loads(slots[0].start, tz, include_ev=_flag(params, "include_ev"))
    weights = Weights(carbon_weight, price_weight)
    plan = make_plan(
        slots, loads, weights=weights, max_load_kw=max_load_kw, kwp=solar_kwp, meta=meta
    )
    payload = plan_dict(plan)
    payload["ranked"] = ranked(plan, loads, weights, max_load_kw, solar_kwp)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = "gridshift/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # keep the console quiet
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            page = (ROOT / "static" / "index.html").read_bytes()
            self._send(200, page, "text/html; charset=utf-8")
            return
        if parsed.path == "/api/health":
            self._json(200, {"status": "ok", "version": "0.1.0"})
            return
        if parsed.path == "/api/plan":
            raw = {key: values[0] for key, values in parse_qs(parsed.query).items() if values}
            try:
                self._json(200, plan_payload(raw))
            except ValueError as exc:
                self._json(400, {"detail": str(exc)})
            except RuntimeError as exc:
                self._json(502, {"detail": str(exc)})
            except Exception as exc:  # noqa: BLE001 - keep the server alive
                self._json(500, {"detail": f"internal error: {exc}"})
            return
        static = ROOT / "static"
        if parsed.path.startswith("/static/"):
            name = parsed.path.removeprefix("/static/")
            if re.fullmatch(r"[A-Za-z0-9._-]+", name) and (static / name).is_file():
                self._send(200, (static / name).read_bytes(), "application/octet-stream")
                return
        if parsed.path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return
        self._json(404, {"detail": "not found"})


def make_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = make_server(host, port)
    print(f"gridshift on http://{host}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()