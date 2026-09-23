from fastapi.testclient import TestClient

from app.config import settings
from app.db import create_job
from app.main import app


def test_api_key_and_scoped_download_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "api_key", "test-secret")
    with TestClient(app) as client:
        assert client.get("/api/ping").status_code == 200
        assert client.get("/api/jobs").status_code == 401
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
