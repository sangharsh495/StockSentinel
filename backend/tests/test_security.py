"""
Security behaviour: API key, client IP behind a proxy, input validation,
docs hidden when locked, no CORS by default.
"""

import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.security import APIKeyMiddleware, RateLimitMiddleware  # noqa: E402


def _app(key: str = "s3cret-key", limit: int = 100) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/api/thing")
    def thing():
        return {"ok": True}

    app.add_middleware(APIKeyMiddleware, api_key=key)
    app.add_middleware(RateLimitMiddleware, max_requests=limit, window_seconds=60)
    return app


def test_api_requires_key_but_health_is_open():
    c = TestClient(_app())
    assert c.get("/health").status_code == 200
    assert c.get("/api/thing").status_code == 401
    assert c.get("/api/thing", headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.get("/api/thing", headers={"X-API-Key": "s3cret-key"}).status_code == 200


def test_no_key_configured_means_open():
    c = TestClient(_app(key=""))
    assert c.get("/api/thing").status_code == 200


def test_rate_limit_uses_forwarded_client_ip():
    # Render/Cloudflare append the real caller last.
    c = TestClient(_app(key="", limit=2))
    a = {"X-Forwarded-For": "10.0.0.1, 1.1.1.1"}
    b = {"X-Forwarded-For": "10.0.0.1, 2.2.2.2"}
    assert [c.get("/api/thing", headers=a).status_code for _ in range(3)] == [200, 200, 429]
    # a different real client behind the same proxy is not blocked
    assert c.get("/api/thing", headers=b).status_code == 200


def test_watchlist_rejects_bad_device_ids():
    from app.api.watchlist import _check_device
    import pytest
    from fastapi import HTTPException
    assert _check_device("a1b2c3d4e5f60718") == "a1b2c3d4e5f60718"
    for bad in ("", "short", "x' OR '1'='1", "a" * 101, "../../etc"):
        with pytest.raises(HTTPException):
            _check_device(bad)


def test_main_app_hides_docs_and_blocks_cors_when_locked(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "k-123")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    import importlib
    import app.config
    import app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    c = TestClient(main.app)  # no lifespan: no DB needed
    assert c.get("/docs").status_code in (401, 404)
    assert c.get("/openapi.json").status_code in (401, 404)
    r = c.get("/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers
    assert c.get("/api/quant/models").status_code == 401
    monkeypatch.delenv("APP_API_KEY")
    importlib.reload(app.config)
    importlib.reload(app.main)


def test_api_key_ignores_spaces_and_line_breaks_around_it():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.security import APIKeyMiddleware

    app = FastAPI()

    @app.get("/api/x")
    def x():
        return {"ok": True}

    app.add_middleware(APIKeyMiddleware, api_key="  abc123XYZ\n")
    c = TestClient(app)
    assert c.get("/api/x", headers={"X-API-Key": "abc123XYZ"}).status_code == 200
    assert c.get("/api/x", headers={"X-API-Key": "abc123XY"}).status_code == 401
    assert c.get("/api/x").status_code == 401


def test_rate_limit_cannot_be_dodged_with_a_fake_forwarded_header():
    c = TestClient(_app(key="", limit=2))
    # The caller varies the first entry; the proxy-added last entry stays the same.
    codes = [c.get("/api/thing", headers={"X-Forwarded-For": f"9.9.9.{i}, 5.5.5.5"}).status_code
             for i in range(3)]
    assert codes == [200, 200, 429]


def test_rate_limit_prefers_cloudflare_client_ip():
    c = TestClient(_app(key="", limit=1))
    h = {"CF-Connecting-IP": "7.7.7.7"}
    assert c.get("/api/thing", headers={**h, "X-Forwarded-For": "1.2.3.4"}).status_code == 200
    assert c.get("/api/thing", headers={**h, "X-Forwarded-For": "4.3.2.1"}).status_code == 429


def test_path_guard_blocks_odd_urls_but_allows_real_symbols():
    from app.security import PathGuardMiddleware
    app = FastAPI()

    @app.get("/api/stocks/{symbol}")
    def stock(symbol: str):
        return {"symbol": symbol}

    app.add_middleware(PathGuardMiddleware)
    c = TestClient(app)
    for ok in ("RELIANCE", "M&M", "BAJAJ-AUTO", "^NSEI", "BRK.B"):
        assert c.get(f"/api/stocks/{ok.replace('&', '%26')}").status_code == 200, ok
    for bad in ("<script>", "a%27%20OR%201=1", "x" * 101, "%00"):
        assert c.get(f"/api/stocks/{bad}").status_code == 400, bad


def test_device_registration_validates_input():
    import pytest
    from pydantic import ValidationError
    from app.api.notifications import DeviceRegistration
    DeviceRegistration(device_id="a1b2c3d4e5f60718", fcm_token="dGVzdA:APA91b" + "x" * 140)
    for bad in ({"device_id": "x", "fcm_token": "t" * 30},
                {"device_id": "a1b2c3d4e5f60718", "fcm_token": "<html>" * 10},
                {"device_id": "a1b2c3d4e5f60718", "fcm_token": "t" * 5000},
                {"device_id": "a1b2c3d4e5f60718", "fcm_token": "t" * 30, "platform": "ios'--"}):
        with pytest.raises(ValidationError):
            DeviceRegistration(**bad)


def test_docs_hidden_even_without_a_key(monkeypatch):
    monkeypatch.delenv("APP_API_KEY", raising=False)
    monkeypatch.delenv("DEBUG", raising=False)
    import importlib
    import app.config
    import app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    c = TestClient(main.app)
    assert c.get("/docs").status_code == 404
    assert c.get("/openapi.json").status_code == 404
