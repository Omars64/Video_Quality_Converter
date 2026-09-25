from __future__ import annotations

import ipaddress
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .config import settings
from .control import JobControl, run_managed_process


class RemoteDownloadError(ValueError):
    pass


def _youtube_failure(log: str) -> str:
    lower = log.lower()
    if "sign in to confirm you" in lower and "bot" in lower:
        return "YouTube is blocking downloads from this processing server right now. Try again later or use a different server in Settings."
    if "private video" in lower or "sign in" in lower or "login required" in lower:
        return "This YouTube video requires account access and cannot be downloaded by this server."
    if "not available in your country" in lower:
        return "This YouTube video is not available in the server's region."
    return "YouTube could not provide this video. Check the link and try again later."


YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
}
INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com"}
REDIRECT_CODES = {301, 302, 303, 307, 308}
MEDIA_PREFIXES = ("video/", "image/", "audio/")


def _yt_dlp_api():
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ModuleNotFoundError as exc:
        raise RemoteDownloadError("yt-dlp is not installed. Install backend requirements or use Docker.") from exc
    return YoutubeDL, DownloadError


def safe_filename(name: str | None, default: str = "download") -> str:
    clean = Path(name or default).name
    clean = re.sub(r"[^A-Za-z0-9._()\[\] -]+", "_", clean).strip(" ._")
    return clean[:180] or default


def _normalized_host(hostname: str | None) -> str:
    return (hostname or "").strip().rstrip(".").lower()


def is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and _normalized_host(parsed.hostname) in YOUTUBE_HOSTS


def validate_youtube_url(url: str) -> None:
    if not is_youtube_url(url):
        raise RemoteDownloadError("Enter a valid public YouTube video URL.")


def _ip_is_public(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text)
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def validate_public_url(url: str) -> None:
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise RemoteDownloadError("The URL is not valid.") from exc
    if parsed.scheme not in {"http", "https"}:
        raise RemoteDownloadError("Only http:// and https:// URLs are supported.")
    host = _normalized_host(parsed.hostname)
    if not host or host == "localhost" or host.endswith(".local"):
        raise RemoteDownloadError("Local/private network URLs are not allowed.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise RemoteDownloadError("The URL port is not valid.") from exc
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RemoteDownloadError("The link hostname could not be resolved.") from exc
    if not addresses:
        raise RemoteDownloadError("The link hostname did not resolve to an address.")
    for address in addresses:
        if not _ip_is_public(address[4][0]):
            raise RemoteDownloadError("Private, loopback, link-local, and reserved network targets are blocked.")


def inspect_youtube(url: str) -> dict:
    validate_youtube_url(url)
    command = [
        sys.executable, "-m", "yt_dlp",
        "--dump-single-json", "--skip-download", "--no-playlist", "--no-warnings",
        "--socket-timeout", "25", "--retries", "2",
    ]
    if shutil.which("deno"):
        command += ["--js-runtimes", "deno"]
    command.append(url)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=75, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RemoteDownloadError(f"Could not inspect this YouTube video: {exc}") from exc
    if result.returncode != 0:
        raise RemoteDownloadError(_youtube_failure(result.stderr or result.stdout))
    try:
        data = __import__("json").loads(result.stdout)
    except Exception as exc:
        raise RemoteDownloadError("YouTube returned invalid metadata.") from exc

    heights = sorted({
        int(fmt.get("height"))
        for fmt in (data.get("formats") or [])
        if fmt.get("vcodec") not in {None, "none"} and fmt.get("height")
    }, reverse=True)
    qualities = [{"value": "best", "label": "Best available"}]
    qualities.extend({"value": str(height), "label": f"{height}p"} for height in heights[:16])
    return {
        "title": data.get("title") or "YouTube video",
        "album": data.get("album") or data.get("playlist_title") or data.get("channel") or "",
        "channel": data.get("channel") or data.get("uploader"),
        "durationSeconds": data.get("duration"),
        "thumbnail": data.get("thumbnail"),
        "qualities": qualities,
        "webpageUrl": data.get("webpage_url") or url,
    }


def _youtube_format_selector(quality: str) -> str:
    if quality == "best":
        return "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
    try:
        height = int(quality)
    except (TypeError, ValueError) as exc:
        raise RemoteDownloadError("Choose a valid YouTube quality.") from exc
    if height < 144 or height > 8640:
        raise RemoteDownloadError("Choose a valid YouTube quality.")
    return (
        f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
        f"b[height<={height}][ext=mp4]/"
        f"bv*[height<={height}]+ba/b[height<={height}]"
    )


def _yt_base(output_dir: Path) -> list[str]:
    args = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist", "--newline", "--no-warnings",
        "--retries", "4", "--fragment-retries", "4",
        "--max-filesize", str(settings.max_remote_bytes), "--socket-timeout", "30",
        "--concurrent-fragments", str(settings.youtube_concurrent_fragments),
        "--progress-template", "download:MFPROGRESS:%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
        "--paths", str(output_dir),
        "--output", "%(title).120B [%(id)s].%(ext)s",
        "--restrict-filenames",
    ]
    if shutil.which("deno"):
        args += ["--js-runtimes", "deno"]
    if shutil.which("aria2c"):
        args += [
            "--downloader", "http:aria2c", "--downloader", "https:aria2c",
            "--downloader-args", f"aria2c:-x{settings.direct_download_connections} -s{settings.direct_download_connections} -k1M --file-allocation=none",
        ]
    return args


def _run_yt_dlp(command: list[str], report: Callable[[float, dict | None], None], control: JobControl) -> tuple[int, str]:
    proc = run_managed_process(command, control, stderr=subprocess.STDOUT)
    lines: list[str] = []
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            control.check()
            line = raw.strip()
            if line:
                lines.append(line)
                if len(lines) > 120:
                    lines.pop(0)
            if "MFPROGRESS:" in line:
                payload = line.split("MFPROGRESS:", 1)[1]
                parts = payload.split("|", 2)
                match = re.search(r"([0-9.]+)%", parts[0] if parts else "")
                progress = float(match.group(1)) if match else 0.0
                patch: dict = {}
                if len(parts) > 1 and parts[1] not in {"N/A", "Unknown", ""}:
                    patch["downloadSpeed"] = parts[1].strip()
                if len(parts) > 2 and parts[2] not in {"N/A", "Unknown", ""}:
                    patch["downloadEta"] = parts[2].strip()
                report(min(94.0, progress * 0.94), patch)
        code = proc.wait()
        control.check()
        return code, "\n".join(lines[-50:])
    finally:
        control.unregister_process(proc)


def _latest_file(output_dir: Path, suffixes: set[str]) -> Path | None:
    candidates = [p for p in output_dir.iterdir() if p.is_file() and p.suffix.lower() in suffixes and not p.name.endswith(".part")]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def _write_mp3_metadata(path: Path, title: str | None, album: str | None, control: JobControl) -> None:
    if not title and not album:
        return
    temp = path.with_name(path.stem + ".metadata.tmp.mp3")
    command = [settings.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0", "-c", "copy"]
    if title:
        command += ["-metadata", f"title={title}"]
    if album:
        command += ["-metadata", f"album={album}"]
    command.append(str(temp))
    proc = run_managed_process(command, control)
    try:
        _, stderr = proc.communicate()
        control.check()
        if proc.returncode != 0 or not temp.exists():
            raise RemoteDownloadError(f"Could not write MP3 metadata: {(stderr or '')[-1000:]}")
        temp.replace(path)
    finally:
        control.unregister_process(proc)
        temp.unlink(missing_ok=True)


def download_youtube(
    url: str,
    output_dir: Path,
    output_type: str,
    quality: str,
    audio_quality: str,
    title: str | None,
    album: str | None,
    report: Callable[[float, dict | None], None],
    control: JobControl,
) -> tuple[Path, str, str]:
    validate_youtube_url(url)
    output_dir.mkdir(parents=True, exist_ok=True)
    command = _yt_base(output_dir)
    if output_type == "mp3":
        if audio_quality not in {"128", "192", "256", "320"}:
            raise RemoteDownloadError("MP3 quality must be 128, 192, 256, or 320 kbps.")
        command += ["-x", "--audio-format", "mp3", "--audio-quality", f"{audio_quality}K", "--embed-metadata"]
    elif output_type == "mp4":
        command += ["--format", _youtube_format_selector(quality), "--merge-output-format", "mp4"]
    else:
        raise RemoteDownloadError("YouTube output must be MP4 or MP3.")
    command.append(url)

    report(1.0, {"engineActual": "yt-dlp", "outputType": output_type})
    code, log = _run_yt_dlp(command, report, control)
    if code != 0:
        raise RemoteDownloadError(_youtube_failure(log))
    report(96.0, {"engineActual": "yt-dlp + FFmpeg"})

    if output_type == "mp3":
        result = _latest_file(output_dir, {".mp3"})
        if not result:
            raise RemoteDownloadError("YouTube finished but no MP3 file was produced.")
        _write_mp3_metadata(result, title, album, control)
        mime = "audio/mpeg"
    else:
        result = _latest_file(output_dir, {".mp4", ".mkv", ".webm", ".mov", ".m4v"})
        if not result:
            raise RemoteDownloadError("YouTube finished but no video file was produced.")
        mime = mimetypes.guess_type(result.name)[0] or "video/mp4"
    report(100.0, {"downloadEta": "0s"})
    return result, result.name, mime


def _filename_from_headers_or_url(headers: httpx.Headers, url: str) -> str:
    disposition = headers.get("content-disposition", "")
    star_match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, flags=re.IGNORECASE)
    if star_match:
        return safe_filename(unquote(star_match.group(1)), "download")
    plain_match = re.search(r'filename="?([^";]+)"?', disposition, flags=re.IGNORECASE)
    if plain_match:
        return safe_filename(plain_match.group(1), "download")
    return safe_filename(Path(unquote(urlparse(url).path)).name, "download")


def _is_media(content_type: str, filename: str) -> bool:
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime.startswith(MEDIA_PREFIXES):
        return True
    ext = Path(filename).suffix.lower()
    return mime in {"application/octet-stream", "binary/octet-stream"} and ext in settings.allowed_remote_extension_set


def _resolve_url(url: str, client: httpx.Client, method: str = "GET") -> tuple[str, httpx.Response]:
    current = url
    for _ in range(7):
        validate_public_url(current)
        req = client.build_request(method, current, headers={"Range": "bytes=0-0"} if method == "GET" else None)
        response = client.send(req, stream=True)
        if response.status_code in REDIRECT_CODES:
            location = response.headers.get("location")
            response.close()
            if not location:
                raise RemoteDownloadError("The remote server returned an invalid redirect.")
            current = urljoin(current, location)
            continue
        return current, response
    raise RemoteDownloadError("Too many redirects while resolving the link.")


def _direct_probe(url: str) -> dict | None:
    timeout = httpx.Timeout(connect=15.0, read=30.0, write=30.0, pool=15.0)
    headers = {"User-Agent": "Mozilla/5.0 MediaForge/3.2"}
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False, headers=headers) as client:
        final_url, response = _resolve_url(url, client, "GET")
        try:
            if response.status_code not in {200, 206}:
                return None
            filename = _filename_from_headers_or_url(response.headers, final_url)
            content_type = response.headers.get("content-type", "application/octet-stream")
            if not _is_media(content_type, filename):
                return None
            total = 0
            content_range = response.headers.get("content-range", "")
            match = re.search(r"/(\d+)$", content_range)
            if match:
                total = int(match.group(1))
            if not total:
                try:
                    total = int(response.headers.get("content-length", "0") or 0)
                except ValueError:
                    total = 0
            if total and total > settings.max_remote_bytes:
                raise RemoteDownloadError("The remote file is larger than the configured download limit.")
            return {
                "url": final_url,
                "filename": filename,
                "contentType": content_type,
                "size": total,
                "range": response.status_code == 206 or "bytes" in response.headers.get("accept-ranges", "").lower(),
            }
        finally:
            response.close()


def _download_single(
    url: str,
    destination: Path,
    total: int,
    report: Callable[[float, dict | None], None],
    control: JobControl,
) -> None:
    timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)
    headers = {"User-Agent": "Mozilla/5.0 MediaForge/3.2"}
    downloaded = 0
    started = time.monotonic()
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False, headers=headers) as client:
        validate_public_url(url)
        with client.stream("GET", url) as response:
            if response.status_code in REDIRECT_CODES:
                raise RemoteDownloadError("The media URL changed after validation; retry the job.")
            response.raise_for_status()
            with destination.open("wb") as handle:
                for chunk in response.iter_bytes(chunk_size=settings.chunk_size_bytes):
                    control.check()
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > settings.max_remote_bytes:
                        raise RemoteDownloadError("The remote file exceeded the configured download limit.")
                    elapsed = max(0.01, time.monotonic() - started)
                    rate = downloaded / elapsed
                    patch = {"downloadSpeed": f"{rate / 1024 / 1024:.1f} MiB/s"}
                    if total and rate > 0:
                        patch["downloadEtaSeconds"] = max(0, round((total - downloaded) / rate))
                    report(min(99.0, downloaded / total * 100) if total else 10.0, patch)


def _download_parallel(
    url: str,
    destination: Path,
    total: int,
    report: Callable[[float, dict | None], None],
    control: JobControl,
) -> None:
    connections = max(2, min(settings.direct_download_connections, 16))
    chunk = max(1, total // connections)
    ranges = []
    for index in range(connections):
        start = index * chunk
        end = total - 1 if index == connections - 1 else min(total - 1, (index + 1) * chunk - 1)
        if start <= end:
            ranges.append((index, start, end))
    lock = threading.Lock()
    downloaded = 0
    started = time.monotonic()
    parts = [destination.with_name(destination.name + f".part{index:02d}") for index, _, _ in ranges]
    timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)

    def worker(index: int, start: int, end: int) -> None:
        nonlocal downloaded
        headers = {"User-Agent": "Mozilla/5.0 MediaForge/3.2", "Range": f"bytes={start}-{end}"}
        part_bytes = 0
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False, headers=headers) as client:
            validate_public_url(url)
            with client.stream("GET", url) as response:
                if response.status_code != 206:
                    raise RemoteDownloadError("Server did not honor parallel range requests.")
                if response.headers.get("content-range", "").lower() != f"bytes {start}-{end}/{total}":
                    raise RemoteDownloadError("Server returned an unexpected byte range.")
                with parts[index].open("wb") as handle:
                    for data in response.iter_bytes(chunk_size=settings.chunk_size_bytes):
                        control.check()
                        if not data:
                            continue
                        handle.write(data)
                        part_bytes += len(data)
                        if part_bytes > end - start + 1:
                            raise RemoteDownloadError("Server sent more data than the requested byte range.")
                        with lock:
                            downloaded += len(data)
                            elapsed = max(0.01, time.monotonic() - started)
                            rate = downloaded / elapsed
                            report(min(99.0, downloaded / total * 100), {
                                "downloadSpeed": f"{rate / 1024 / 1024:.1f} MiB/s",
                                "downloadEtaSeconds": max(0, round((total - downloaded) / rate)),
                            })
        if part_bytes != end - start + 1:
            raise RemoteDownloadError("Server sent an incomplete byte range.")

    try:
        with ThreadPoolExecutor(max_workers=len(ranges), thread_name_prefix="direct-range") as pool:
            futures = [pool.submit(worker, *item) for item in ranges]
            for future in as_completed(futures):
                future.result()
        with destination.open("wb") as out:
            for part in parts:
                with part.open("rb") as src:
                    shutil.copyfileobj(src, out, length=settings.chunk_size_bytes)
    finally:
        for part in parts:
            part.unlink(missing_ok=True)


def _download_direct(probe: dict, output_dir: Path, report, control) -> tuple[Path, str, str]:
    filename = probe["filename"]
    content_type = probe["contentType"]
    if not Path(filename).suffix:
        filename = safe_filename(filename + (mimetypes.guess_extension(content_type.split(";", 1)[0]) or ""), "download")
    destination = output_dir / filename
    counter = 2
    while destination.exists():
        destination = output_dir / f"{destination.stem}-{counter}{destination.suffix}"
        counter += 1
    try:
        if probe["size"] and probe["range"] and probe["size"] >= 8 * 1024 * 1024 and settings.direct_download_connections > 1:
            try:
                _download_parallel(probe["url"], destination, probe["size"], report, control)
            except RemoteDownloadError:
                destination.unlink(missing_ok=True)
                _download_single(probe["url"], destination, probe["size"], report, control)
        else:
            _download_single(probe["url"], destination, probe["size"], report, control)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if not destination.exists() or destination.stat().st_size == 0:
        raise RemoteDownloadError("The remote server returned an empty file.")
    report(100.0, {"downloadEta": "0s"})
    return destination, destination.name, content_type.split(";", 1)[0] or "application/octet-stream"


def _generic_video_format(url: str) -> str:
    if _is_instagram_post(url):
        # Instagram can expose VP9 video in an MP4 container. Prefer a single
        # MP4 that already includes audio for wider player compatibility.
        return "b[ext=mp4]/bv*[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b"
    return "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"


def _download_generic_video(url: str, output_dir: Path, report, control, errors: list[str]) -> tuple[Path, str, str] | None:
    command = _yt_base(output_dir) + [
        "--format", _generic_video_format(url),
        "--merge-output-format", "mp4",
        url,
    ]
    code, log = _run_yt_dlp(command, report, control)
    if code != 0:
        errors.append(log)
        return None
    result = _latest_file(output_dir, {".mp4", ".mkv", ".webm", ".mov", ".m4v"})
    if not result:
        return None
    return result, result.name, mimetypes.guess_type(result.name)[0] or "video/mp4"


def _is_instagram_post(url: str) -> bool:
    parsed = urlparse(url)
    return _normalized_host(parsed.hostname) in INSTAGRAM_HOSTS and bool(
        re.fullmatch(r"/(?:p|reel|tv)/[A-Za-z0-9_-]+/?", parsed.path)
    )


def _instagram_photo_urls(url: str, report, control, errors: list[str]) -> list[str] | None:
    """Use yt-dlp's public post metadata; its normal downloader handles videos only."""
    command = [
        sys.executable, "-m", "yt_dlp", "--dump-single-json", "--skip-download",
        "--ignore-no-formats-error", "--no-warnings", "--no-playlist",
        "--socket-timeout", "25", "--retries", "2", url,
    ]
    code, output = _run_yt_dlp(command, report, control)
    if code != 0:
        errors.append(output)
        return None
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        errors.append("Instagram returned invalid public post metadata.")
        return None
    entries = data.get("entries") if data.get("_type") == "playlist" else [data]
    if not isinstance(entries, list) or not entries:
        return None
    if len(entries) > 20:
        raise RemoteDownloadError("Instagram posts with more than 20 items are not supported.")
    # A mixed post still belongs to the video extractor. Never substitute a
    # video's preview frame for the actual video.
    if any(not isinstance(entry, dict) or entry.get("formats") or entry.get("duration") for entry in entries):
        return None
    urls: list[str] = []
    for entry in entries:
        thumbnails = entry.get("thumbnails") or []
        # yt-dlp's Instagram extractor reverses the site's candidate list;
        # the final candidate is the largest original rendition.
        candidates = [item.get("url") for item in reversed(thumbnails) if isinstance(item, dict)]
        candidate = next((value for value in candidates if isinstance(value, str) and value.startswith("https://")), None)
        if not candidate:
            return None
        validate_public_url(candidate)
        urls.append(candidate)
    return urls


def _download_instagram_photos(url: str, output_dir: Path, report, control, errors: list[str]) -> tuple[Path, str, str] | None:
    urls = _instagram_photo_urls(url, report, control, errors)
    if not urls:
        return None
    shortcode = safe_filename(urlparse(url).path.strip("/").split("/")[-1], "post")
    files: list[Path] = []
    total_bytes = 0
    for index, image_url in enumerate(urls, start=1):
        control.check()
        probe = _direct_probe(image_url)
        if not probe or not probe["contentType"].lower().startswith("image/"):
            raise RemoteDownloadError("Instagram exposed photo metadata, but its image server denied the download.")
        if probe["size"] and probe["size"] > settings.max_remote_bytes - total_bytes:
            raise RemoteDownloadError("This Instagram post exceeds the configured download limit.")
        base = (index - 1) / len(urls)
        span = 1 / len(urls)
        path, _, mime = _download_direct(
            probe, output_dir,
            lambda progress, patch=None: report(min(94.0, 5.0 + (base + span * progress / 100) * 85), patch),
            control,
        )
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/avif": ".avif"}.get(mime.lower())
        if not ext:
            raise RemoteDownloadError("Instagram returned an unsupported image format.")
        destination = output_dir / f"instagram-{shortcode}-{index:02d}{ext}"
        path.rename(destination)
        total_bytes += destination.stat().st_size
        if total_bytes > settings.max_remote_bytes:
            raise RemoteDownloadError("This Instagram post exceeds the configured download limit.")
        files.append(destination)
    if len(files) == 1:
        report(100.0, {"engineActual": "Instagram photo resolver", "downloadEta": "0s"})
        return files[0], files[0].name, mimetypes.guess_type(files[0].name)[0] or "image/jpeg"
    archive = output_dir / f"instagram-{shortcode}.zip"
    report(95.0, {"engineActual": "Instagram photo resolver"})
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        for path in files:
            control.check()
            bundle.write(path, arcname=path.name)
    for path in files:
        path.unlink()
    report(100.0, {"downloadEta": "0s"})
    return archive, archive.name, "application/zip"


def _html_media_candidates(url: str) -> list[str]:
    validate_public_url(url)
    timeout = httpx.Timeout(connect=15.0, read=30.0, write=20.0, pool=10.0)
    headers = {"User-Agent": "Mozilla/5.0 MediaForge/3.2"}
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False, headers=headers) as client:
        final_url, response = _resolve_url(url, client, "GET")
        try:
            if response.status_code not in {200, 206}:
                return []
            content_type = response.headers.get("content-type", "").lower()
            if "html" not in content_type:
                return []
            data = b""
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                data += chunk
                if len(data) >= 2 * 1024 * 1024:
                    break
        finally:
            response.close()
    soup = BeautifulSoup(data, "html.parser")
    raw: list[str] = []
    meta_keys = [
        ("property", "og:video"), ("property", "og:video:url"), ("property", "og:image"),
        ("name", "twitter:player:stream"), ("name", "twitter:image"),
    ]
    for attr, value in meta_keys:
        tag = soup.find("meta", attrs={attr: value})
        if tag and tag.get("content"):
            raw.append(tag["content"])
    for tag in soup.find_all(["video", "source", "img"]):
        for attr in ("src", "data-src", "data-original"):
            if tag.get(attr):
                raw.append(tag[attr])
        if tag.get("srcset"):
            entries = [piece.strip().split(" ")[0] for piece in tag["srcset"].split(",") if piece.strip()]
            raw.extend(reversed(entries))
    seen = set()
    results = []
    for value in raw:
        candidate = urljoin(final_url, value)
        if candidate not in seen:
            seen.add(candidate)
            results.append(candidate)
    return results[:40]


def download_public_media(
    url: str,
    output_dir: Path,
    report: Callable[[float, dict | None], None],
    control: JobControl,
) -> tuple[Path, str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    validate_public_url(url)
    report(1.0, {"engineActual": "Public media resolver"})

    probe = _direct_probe(url)
    if probe:
        report(2.0, {"engineActual": "Parallel HTTP downloader" if probe["range"] else "HTTP downloader"})
        return _download_direct(probe, output_dir, report, control)

    # yt-dlp supports many public media pages beyond YouTube. It is tried before
    # generic HTML parsing because it understands site manifests and stream merging.
    extractor_errors: list[str] = []
    if _is_instagram_post(url):
        result = _download_instagram_photos(url, output_dir, report, control, extractor_errors)
        if result:
            return result
    try:
        result = _download_generic_video(url, output_dir, report, control, extractor_errors)
        if result:
            report(100.0, {"engineActual": "yt-dlp site extractor"})
            return result
    except Exception:
        control.check()

    report(5.0, {"engineActual": "HTML media discovery"})
    for candidate in _html_media_candidates(url):
        control.check()
        try:
            probe = _direct_probe(candidate)
            if probe:
                return _download_direct(probe, output_dir, report, control)
        except RemoteDownloadError:
            continue

    host = _normalized_host(urlparse(url).hostname)
    blocked = any(
        re.search(r"\b403\b|\bblocked\b", error, re.IGNORECASE) for error in extractor_errors
    )
    if blocked and (host == "reddit.com" or host.endswith(".reddit.com")):
        raise RemoteDownloadError(
            "Reddit blocked automated access to this post from the processing server (HTTP 403). "
            "Try a direct public image/video URL if one is available."
        )
    if blocked:
        raise RemoteDownloadError(
            f"{host} blocked automated access from this processing server (HTTP 403). "
            "Try a direct public image/video URL if one is available."
        )
    if any(re.search(r"\b429\b|too many requests|rate.limit", error, re.IGNORECASE) for error in extractor_errors):
        raise RemoteDownloadError(f"{host} is rate-limiting this processing server. Try again later.")
    if _is_instagram_post(url):
        raise RemoteDownloadError(
            "Instagram did not expose downloadable public media to this server. "
            "Check that the post is public; login-only or blocked posts cannot be downloaded here."
        )
    raise RemoteDownloadError(
        "No downloadable public image/video was found at this URL. The site may require login, "
        "limit automated access, or use a media format this app does not support."
    )
