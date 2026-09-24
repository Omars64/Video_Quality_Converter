"""Exercise real API jobs. Credentials are read from a private dotenv file, never logged."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import time

import httpx
if os.name == "nt":
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
from PIL import Image
from docx import Document
from dotenv import dotenv_values

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8000")
parser.add_argument("--auth-file", default=".tools/render-auth.env")
parser.add_argument("--remote", action="store_true")
parser.add_argument("--docx", action="store_true")
args = parser.parse_args()
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.auth import issue_session
from app.config import settings
from app.version import VERSION
config = dotenv_values(args.auth_file)
settings.app_password_hash = config["VQI_APP_PASSWORD_HASH"]
settings.session_secret = config["VQI_SESSION_SECRET"]
client = httpx.Client(base_url=args.url, headers={"Authorization": f"Bearer {issue_session()}"}, timeout=120)
folder = Path(".tools/smoke"); folder.mkdir(parents=True, exist_ok=True)
image = folder / "sample.png"
Image.new("RGB", (96, 64), (80, 130, 190)).save(image)
pdf = folder / "sample.pdf"
Image.open(image).convert("RGB").save(pdf, "PDF")
video = folder / "sample.mp4"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x90:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)


def job(label, endpoint, *, source=None, field="file", data=None, payload=None):
    if source:
        with source.open("rb") as file:
            response = client.post(endpoint, files={field:(source.name, file)}, data=data)
    else:
        response = client.post(endpoint, json=payload)
    response.raise_for_status()
    job_id = response.json()["id"]
    for _ in range(180):
        response = client.get(f"/api/jobs/{job_id}"); response.raise_for_status()
        result = response.json()
        if result["status"] in {"failed", "cancelled", "stopped"}:
            raise AssertionError(f"{label}: {result.get('error')}")
        if result["status"] == "completed":
            ticket = client.post(f"/api/jobs/{job_id}/download-ticket")
            ticket.raise_for_status()
            download = httpx.get(args.url + ticket.json()["downloadUrl"], timeout=120)
            download.raise_for_status()
            assert download.content, "Empty download"
            if label == "photo PNG":
                assert Image.open(io.BytesIO(download.content)).format == "PNG"
            print(json.dumps({"test":label, "status":"passed", "bytes":len(download.content), "filename":result["outputName"]}), flush=True)
            return
        time.sleep(2)
    raise AssertionError(f"{label}: timed out")


assert client.get('/api/ping').json()['version'] == VERSION
job("photo PNG", "/api/photo/enhance", source=image, data={"scale":"2", "strength":"natural", "output_format":"png"})
job("images to PDF", "/api/images/convert", source=image, field="files", data={"output_format":"pdf"})
job("PDF to PNG ZIP", "/api/images/convert", source=pdf, field="files", data={"output_format":"png"})
job("video 1080p", "/api/video/enhance", source=video, data={"target_height":"1080", "profile":"fast", "enhancement":"light", "engine":"cpu"})
if args.docx:
    doc = Document(); doc.add_paragraph("Media Forge document conversion test.")
    docx = folder / 'sample.docx'; doc.save(docx)
    job("DOCX to PDF", "/api/images/convert", source=docx, field="files", data={"output_format":"pdf"})
if args.remote:
    job("public image link", "/api/remote/download", payload={"url":"https://www.python.org/static/community_logos/python-logo.png"})
    job("public video link", "/api/remote/download", payload={"url":"https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4"})
