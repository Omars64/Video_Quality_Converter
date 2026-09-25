import socket
import json
import zipfile

import pytest

from app.downloads import RemoteDownloadError, is_youtube_url, validate_public_url, _youtube_failure
from app import downloads


def test_youtube_url_detection():
    assert is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert is_youtube_url("https://youtu.be/abc")
    assert not is_youtube_url("https://example.com/video.mp4")


def test_private_urls_are_rejected():
    with pytest.raises(RemoteDownloadError):
        validate_public_url("http://127.0.0.1/video.mp4")
    with pytest.raises(RemoteDownloadError):
        validate_public_url("http://localhost/video.mp4")
    with pytest.raises(RemoteDownloadError, match="port"):
        validate_public_url("http://example.com:bad/video.mp4")


def test_youtube_bot_block_has_clear_message():
    message = _youtube_failure("ERROR: Sign in to confirm you're not a bot. Use --cookies for authentication")
    assert "blocking downloads" in message
    assert "--cookies" not in message


def test_reddit_block_reports_actual_host_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(downloads, "validate_public_url", lambda _: None)
    monkeypatch.setattr(downloads, "_direct_probe", lambda _: None)
    monkeypatch.setattr(downloads, "_html_media_candidates", lambda _: [])

    def rejected_extractor(url, output_dir, report, control, errors):
        errors.append("HTTP Error 403: Blocked")
        return None

    monkeypatch.setattr(downloads, "_download_generic_video", rejected_extractor)
    class Control:
        def check(self):
            pass

    with pytest.raises(RemoteDownloadError, match="Reddit blocked.*403"):
        downloads.download_public_media("https://www.reddit.com/r/example/s/abc", tmp_path, lambda *_: None, Control())


def test_instagram_photo_carousel_becomes_zip(monkeypatch, tmp_path):
    monkeypatch.setattr(downloads, "validate_public_url", lambda _: None)
    monkeypatch.setattr(downloads, "_direct_probe", lambda url: None if "instagram.com/p/" in url else {
        "url": url, "contentType": "image/webp", "filename": "photo.webp", "size": 100, "range": False,
    })
    metadata = {"_type": "playlist", "entries": [
        {"formats": [], "thumbnails": [{"url": f"https://cdn.example/{index}-small.webp"},
                                      {"url": f"https://cdn.example/{index}-large.webp"}]}
        for index in (1, 2)
    ]}
    monkeypatch.setattr(downloads, "_run_yt_dlp", lambda *_: (0, json.dumps(metadata)))
    selected = []

    def save_image(probe, output_dir, report, control):
        selected.append(probe["url"])
        path = output_dir / f"photo-{len(selected)}.webp"
        path.write_bytes(b"image")
        report(100.0, None)
        return path, path.name, "image/webp"

    monkeypatch.setattr(downloads, "_download_direct", save_image)

    class Control:
        def check(self):
            pass

    path, name, mime = downloads.download_public_media(
        "https://www.instagram.com/p/AbC123", tmp_path, lambda *_: None, Control(),
    )
    assert selected == ["https://cdn.example/1-large.webp", "https://cdn.example/2-large.webp"]
    assert mime == "application/zip"
    assert path.name == name == "instagram-AbC123.zip"
    with zipfile.ZipFile(path) as archive:
        assert archive.namelist() == ["instagram-AbC123-01.webp", "instagram-AbC123-02.webp"]


def test_instagram_video_does_not_become_thumbnail(monkeypatch):
    monkeypatch.setattr(downloads, "validate_public_url", lambda _: None)
    metadata = {"formats": [{"url": "https://cdn.example/video.mp4"}],
                "thumbnails": [{"url": "https://cdn.example/preview.webp"}]}
    monkeypatch.setattr(downloads, "_run_yt_dlp", lambda *_: (0, json.dumps(metadata)))
    class Control:
        def check(self):
            pass

    assert downloads._instagram_photo_urls(
        "https://www.instagram.com/reel/AbC123", lambda *_: None, Control(), [],
    ) is None


def test_instagram_video_prefers_combined_mp4_with_audio():
    instagram = downloads._generic_video_format("https://www.instagram.com/reel/AbC123")
    other = downloads._generic_video_format("https://example.com/video")
    assert instagram.startswith("b[ext=mp4]/")
    assert other.startswith("bv*[ext=mp4]+ba[ext=m4a]/")
    assert downloads._generic_video_format("https://instagram.com.evil.example/reel/AbC123") == other
