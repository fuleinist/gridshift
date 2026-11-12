from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

import gridshift.api as api
from gridshift.sources import demo_carbon


@pytest.fixture()
def server(tmp_path):
    api.reset_cache(tmp_path / "cache.sqlite")
    httpd = api.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base
    httpd.shutdown()
    httpd.server_close()
    api.reset_cache(None)


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def test_health(server):
    assert get_json(server + "/api/health")["status"] == "ok"


def test_plan_uses_demo_source(server):
    body = get_json(server + "/api/plan?source=demo&hours=12")
    assert len(body["slots"]) == 24
    assert body["placements"]
    assert body["meta"]["carbon_source"] == "demo curve"


def test_plan_rejects_zero_weights(server):
    with pytest.raises(urllib.error.HTTPError) as caught:
        get_json(server + "/api/plan?source=demo&carbon_weight=0&price_weight=0")
    assert caught.value.code == 400


def test_index_serves_html(server):
    with urllib.request.urlopen(server + "/", timeout=20) as response:
        assert response.status == 200
        assert b"gridshift" in response.read()


def test_ranked_section_present(server):
    body = get_json(server + "/api/plan?source=demo&hours=12")
    assert "dishwasher" in body["ranked"]
    assert len(body["ranked"]["dishwasher"]) == 3


def test_demo_curve_shape():
    from datetime import datetime, timezone

    assert demo_carbon(datetime(2026, 11, 13, 2, 0, tzinfo=timezone.utc)) > 0