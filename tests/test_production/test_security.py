"""Access control, isolation, input limits, headers and configuration (R5-R10)."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, validate_settings
from tests.test_multimodal.conftest import speech_like, wav


class TestIsolation:
    """A learner can never read or change another learner's data (IDOR)."""

    def test_sessions_are_invisible_across_accounts(self, two_users, mock_llm):
        client, (a, _), (b, _) = two_users
        sid = client.post("/api/v1/sessions/start", json={"language": "Spanish"}, headers=a).json()[
            "session_id"
        ]
        assert client.get(f"/api/v1/sessions/{sid}/state", headers=b).status_code == 404
        chat = {"session_id": sid, "message": "hola"}
        assert client.post("/api/v1/chat", json=chat, headers=b).status_code == 404
        assert client.post(f"/api/v1/sessions/{sid}/end", headers=b).status_code == 404
        # The owner is unaffected.
        assert client.get(f"/api/v1/sessions/{sid}/state", headers=a).status_code == 200

    def test_submissions_cost_trace_and_export_are_scoped(self, two_users, mock_llm, monkeypatch):
        from src.multimodal import pipeline
        from tests.test_multimodal.conftest import make_transcript, scripted

        client, (a, a_id), (b, b_id) = two_users
        monkeypatch.setattr(
            pipeline, "default_provider", lambda: scripted(transcript=make_transcript("hola"))
        )
        body = {"audio_base64": base64.b64encode(wav(speech_like(2.0))).decode()}
        sub = client.post("/api/v1/assessment/speaking", json=body, headers=a).json()
        url = f"/api/v1/assessment/submissions/{sub['submission_id']}"
        assert client.get(url, headers=b).status_code == 404
        assert client.delete(url, headers=b).status_code == 404
        assert client.get(url, headers=a).status_code == 200

        sid = client.post("/api/v1/sessions/start", json={"language": "Spanish"}, headers=a).json()[
            "session_id"
        ]
        client.post("/api/v1/chat", json={"session_id": sid, "message": "hola"}, headers=a)
        assert client.get(f"/api/v1/cost/session/{sid}", headers=b).json()["calls"] == 0
        trace_b = client.get(f"/api/v1/trace/{sid}", headers=b).json()
        assert trace_b["interactions"] == [] and trace_b["spans"] == []

        export_b = client.get("/api/v1/privacy/export", headers=b).json()
        assert a_id not in str(export_b)

    def test_unauthenticated_and_forged_tokens_are_rejected(self, client):
        for path in ("/api/v1/learner/plan", "/api/v1/assessment/submissions", "/api/v1/cost/me"):
            assert client.get(path).status_code == 401
            forged = {"Authorization": "Bearer not-a-real-token"}
            assert client.get(path, headers=forged).status_code == 401


class TestInputLimits:
    def test_oversized_body_is_rejected_before_parsing(self, temp_storage, monkeypatch):
        from src.api.app import create_app
        from src.config import settings

        monkeypatch.setattr(settings, "max_request_bytes", 1024)
        client = TestClient(create_app())
        resp = client.post(
            "/api/v1/auth/register",
            content=b'{"username": "x", "password": "' + b"y" * 2000 + b'"}',
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 413 and resp.json()["detail"]["code"] == "too_large"

    def test_short_passwords_are_refused(self, client):
        resp = client.post("/api/v1/auth/register", json={"username": "s", "password": "short"})
        assert resp.status_code == 400 and "at least 8" in resp.json()["detail"]

    def test_per_user_work_rate_limit(self, auth_client, mock_llm, monkeypatch):
        from src.api.deps import user_work_limiter

        client, headers, _ = auth_client
        monkeypatch.setattr(user_work_limiter, "max_calls", 2)
        codes = [
            client.post("/api/v1/sessions/start", json={"language": "Spanish"}, headers=headers)
            for _ in range(3)
        ]
        assert [c.status_code for c in codes] == [200, 200, 429]
        assert codes[-1].json()["detail"]["code"] == "rate_limited"
        assert int(codes[-1].headers["retry-after"]) >= 1

    def test_invalid_idempotency_key_is_rejected(self, auth_client):
        client, headers, _ = auth_client
        resp = client.post(
            "/api/v1/review/submit",
            json={"word": "gato", "correct": True},
            headers={**headers, "Idempotency-Key": "bad key!"},
        )
        assert resp.status_code == 400


class TestHeadersAndErrors:
    def test_security_headers_and_request_id(self, client):
        resp = client.get("/health", headers={"X-Request-ID": "trace-123"})
        assert resp.headers["x-request-id"] == "trace-123"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert "default-src 'none'" in resp.headers["content-security-policy"]
        # A malformed id is replaced, not echoed (log injection).
        bad = client.get("/health", headers={"X-Request-ID": "a b\nc"})
        assert bad.headers["x-request-id"] != "a b\nc" and len(bad.headers["x-request-id"]) == 32

    def test_unhandled_errors_return_a_request_id_not_a_trace(self, temp_storage):
        from src.api.app import create_app

        app = create_app()

        @app.get("/boom")
        def boom() -> None:
            raise RuntimeError("secret internals")

        resp = TestClient(app, raise_server_exceptions=False).get("/boom")
        assert resp.status_code == 500
        assert resp.json()["request_id"] and "secret" not in resp.text

    def test_readiness_does_not_leak_exception_text(self, client, monkeypatch):
        from src.memory import db

        def broken():
            raise RuntimeError("/srv/secret/path.db is locked")

        monkeypatch.setattr(db, "connect", broken)
        body = client.get("/ready").json()
        assert body["checks"]["database"] == {"ok": False, "error": "RuntimeError"}
        assert "secret" not in str(body)

    def test_metrics_require_the_token_when_configured(self, temp_storage, monkeypatch):
        from src.api.app import create_app
        from src.config import settings

        monkeypatch.setattr(settings, "metrics_token", "t" * 32)
        client = TestClient(create_app())
        assert client.get("/metrics").status_code == 401
        ok = client.get("/metrics", headers={"Authorization": "Bearer " + "t" * 32})
        assert ok.status_code == 200 and "polyglot_http_requests_total" in ok.text

    def test_docs_can_be_disabled(self, temp_storage, monkeypatch):
        from src.api.app import create_app
        from src.config import settings

        monkeypatch.setattr(settings, "api_docs_enabled", False)
        client = TestClient(create_app())
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def _prod(**overrides) -> Settings:
    base = {
        "app_env": "production",
        "anthropic_api_key": "k",
        "cors_origins": "https://app.example.org",
        "api_docs_enabled": False,
        "log_format": "json",
        "metrics_token": "m" * 32,
        "llm_global_daily_budget_usd": 50.0,
        "restic_repository": "s3:https://s3.example.org/backups/polyglot",
        "restic_password": "p" * 24,
    }
    return Settings(**{**base, **overrides})


class TestProductionConfiguration:
    def test_a_safe_production_configuration_passes(self, monkeypatch):
        monkeypatch.delenv("POLYGLOT_DETERMINISTIC", raising=False)
        assert validate_settings(_prod()) == []

    @pytest.mark.parametrize(
        ("override", "fragment"),
        [
            ({"cors_origins": "http://localhost:3000"}, "CORS_ORIGINS"),
            ({"api_docs_enabled": True}, "API_DOCS_ENABLED"),
            ({"log_format": "text"}, "LOG_FORMAT"),
            ({"metrics_token": ""}, "METRICS_TOKEN"),
            ({"llm_global_daily_budget_usd": 0.0}, "BUDGET"),
            ({"telemetry_enabled": False}, "TELEMETRY_ENABLED"),
            ({"app_env": "prod"}, "APP_ENV"),
            ({"restic_repository": ""}, "RESTIC_REPOSITORY"),
            ({"restic_repository": "/data/offsite"}, "RESTIC_REPOSITORY"),
            ({"restic_repository": "local:/mnt/backup"}, "RESTIC_REPOSITORY"),
            ({"restic_password": "short"}, "RESTIC_PASSWORD"),
        ],
    )
    def test_unsafe_settings_are_reported(self, monkeypatch, override, fragment):
        monkeypatch.delenv("POLYGLOT_DETERMINISTIC", raising=False)
        assert any(fragment in p for p in validate_settings(_prod(**override)))

    def test_deterministic_mode_is_refused_in_production(self, monkeypatch):
        monkeypatch.setenv("POLYGLOT_DETERMINISTIC", "1")
        assert any("DETERMINISTIC" in p for p in validate_settings(_prod()))

    def test_the_api_refuses_to_start_with_unsafe_production_settings(
        self, temp_storage, monkeypatch
    ):
        from src.api.app import create_app
        from src.config import settings

        monkeypatch.setattr(settings, "app_env", "production")
        with pytest.raises(RuntimeError, match="CORS_ORIGINS"), TestClient(create_app()):
            pass

    def test_gradio_requires_credentials_in_production(self):
        from src.main import gradio_auth

        assert gradio_auth(Settings(app_env="development")) is None
        assert gradio_auth(Settings(gradio_auth="ops:long-password")) == ("ops", "long-password")
        with pytest.raises(SystemExit):
            gradio_auth(Settings(app_env="production"))
