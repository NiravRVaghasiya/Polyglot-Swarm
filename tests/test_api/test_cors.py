"""CORS: the separately served React app must be able to call the API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.config import settings


def _preflight(client: TestClient, origin: str):
    return client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


def _app_with_origins(monkeypatch, origins: str) -> TestClient:
    from src.api.app import create_app

    monkeypatch.setattr(settings, "cors_origins", origins, raising=False)
    return TestClient(create_app())


class TestCors:
    def test_default_allows_the_local_react_dev_server(self, client):
        resp = _preflight(client, "http://localhost:3000")
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
        allowed_headers = resp.headers["access-control-allow-headers"].lower()
        assert "authorization" in allowed_headers
        assert "content-type" in allowed_headers

    def test_unlisted_origin_is_not_allowed(self, client):
        resp = _preflight(client, "https://evil.example")
        assert "access-control-allow-origin" not in resp.headers

    def test_simple_request_from_allowed_origin_gets_cors_header(self, client):
        resp = client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"

    def test_origins_are_configurable(self, temp_storage, monkeypatch):
        client = _app_with_origins(
            monkeypatch, "https://tutor.example.com, https://staging.example.com"
        )
        for origin in ("https://tutor.example.com", "https://staging.example.com"):
            assert _preflight(client, origin).headers["access-control-allow-origin"] == origin
        assert (
            "access-control-allow-origin" not in _preflight(client, "http://localhost:3000").headers
        )

    def test_empty_setting_disables_cors(self, temp_storage, monkeypatch):
        client = _app_with_origins(monkeypatch, "")
        resp = client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert "access-control-allow-origin" not in resp.headers
