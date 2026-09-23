from fastapi.testclient import TestClient

from app.config import settings
from app.db import create_job
from app.main import app
from app.auth import hash_password, issue_session, valid_session, _attempts


def test_api_key_and_scoped_download_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "api_key", "test-secret")
    with TestClient(app) as client:
        assert client.get("/api/ping").status_code == 200
        denied = client.get("/api/jobs", headers={"Origin": "https://localhost"})
        assert denied.status_code == 401
        assert denied.headers["access-control-allow-origin"] == "https://localhost"
        headers = {"Authorization": "Bearer test-secret"}
        assert client.get("/api/jobs", headers=headers).status_code == 200

        output = settings.outputs_dir / "result.txt"
        output.write_text("ready")
        create_job({"id": "finished", "status": "completed", "input_path": "", "output_path": str(output)})
        response = client.post("/api/jobs/finished/download-ticket", headers=headers)
        assert response.status_code == 200
        ticket_url = response.json()["downloadUrl"]
        assert client.get(ticket_url).text == "ready"
        assert client.get("/api/jobs/finished/download").status_code == 401
        assert client.get(ticket_url.replace("finished", "other")).status_code == 401

        preflight = client.options("/api/jobs", headers={
            "Origin": "https://localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        })
        assert preflight.status_code == 200


def test_password_sessions_and_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "app_password_hash", hash_password("test-only-password"))
    monkeypatch.setattr(settings, "session_secret", "test-signing-secret-with-at-least-32-characters")
    _attempts.clear()
    with TestClient(app) as client:
        assert client.get("/api/jobs").status_code == 401
        assert client.post("/api/auth/login", json={"password":"wrong"}).status_code == 401
        response = client.post("/api/auth/login", json={"password":"test-only-password"})
        assert response.status_code == 200
        token = response.json()["token"]
        assert valid_session(token)
        assert not valid_session(token + "x")
        assert client.get("/api/auth/session", headers={"Authorization":f"Bearer {token}"}).status_code == 200
        for _ in range(5):
            assert client.post("/api/auth/login", json={"password":"wrong"}).status_code == 401
        assert client.post("/api/auth/login", json={"password":"wrong"}).status_code == 429
    _attempts.clear()


def test_unconfigured_server_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "app_password_hash", "")
    with TestClient(app) as client:
        assert client.get("/api/jobs").status_code == 503
        assert client.post("/api/auth/login", json={"password":"anything"}).status_code == 503
