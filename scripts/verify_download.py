"""Verify a real authenticated download; never print session tokens or signed URLs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
from dotenv import dotenv_values

if os.name == "nt":
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.auth import issue_session
from app.config import settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("link")
    parser.add_argument("--url", default="https://video-quality-converter-api.onrender.com")
    parser.add_argument("--youtube", choices=["mp4", "mp3"])
    parser.add_argument("--auth-file", default=".tools/render-auth.env")
    args = parser.parse_args()
    config = dotenv_values(args.auth_file)
    settings.app_password_hash = config["VQI_APP_PASSWORD_HASH"]
    settings.session_secret = config["VQI_SESSION_SECRET"]
    with httpx.Client(base_url=args.url, headers={"Authorization": f"Bearer {issue_session()}"}, timeout=120) as client:
        print("Backend:", client.get("/api/ping").json(), flush=True)
        payload = {"url": args.link}
        if args.youtube:
            payload.update(outputType=args.youtube, quality="360", audioQuality="128")
        response = client.post("/api/youtube/download" if args.youtube else "/api/remote/download", json=payload)
        response.raise_for_status()
        job_id = response.json()["id"]
        print("Test job:", job_id, flush=True)
        previous = None
        for _ in range(300):
            response = client.get(f"/api/jobs/{job_id}")
            response.raise_for_status()
            job = response.json()
            state = (job["status"], round(job.get("progress", 0)))
            if state != previous:
                print("Progress:", state, flush=True)
                previous = state
            if job["status"] in {"failed", "cancelled", "stopped"}:
                print("Failure:", job.get("error"), flush=True)
                print("Diagnostics:", json.dumps({key: job.get("details", {}).get(key) for key in ("selectedStreams", "extractorDiagnostics", "downloadAttempt", "engineActual")}), flush=True)
                return 1
            if job["status"] == "completed":
                ticket = client.post(f"/api/jobs/{job_id}/download-ticket")
                ticket.raise_for_status()
                folder = Path(".tools/verification") / job_id
                folder.mkdir(parents=True, exist_ok=True)
                output = folder / Path(job["outputName"]).name
                with httpx.stream("GET", args.url + ticket.json()["downloadUrl"], timeout=120) as download:
                    download.raise_for_status()
                    with output.open("wb") as file:
                        for chunk in download.iter_bytes():
                            file.write(chunk)
                assert output.stat().st_size == job["outputSizeBytes"], "Incomplete file transfer"
                probe = subprocess.run([settings.ffprobe_bin, "-v", "error", "-show_entries", "stream=codec_type,codec_name,profile,channels,sample_rate,duration:format=duration,size", "-of", "json", str(output)], capture_output=True, text=True, check=True)
                print(probe.stdout, flush=True)
                streams = json.loads(probe.stdout)["streams"]
                assert any(stream["codec_type"] == "audio" for stream in streams), "Downloaded media has no audio track"
                signal = subprocess.run([settings.ffmpeg_bin, "-hide_banner", "-i", str(output), "-vn", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
                print("\n".join(line for line in signal.stderr.splitlines() if "volume:" in line), flush=True)
                assert signal.returncode == 0, "Audio could not be decoded"
                print("Verified file:", output.resolve(), flush=True)
                return 0
            time.sleep(2)
    raise RuntimeError("Verification timed out")


if __name__ == "__main__":
    raise SystemExit(main())
