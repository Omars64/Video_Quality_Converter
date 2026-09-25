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


def test_instagram_video_prefers_explicit_audio_merge():
    instagram = downloads._generic_video_format("https://www.instagram.com/reel/AbC123")
    other = downloads._generic_video_format("https://example.com/video")
    assert instagram.startswith("bv[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/")
    assert other.startswith("bv*[ext=mp4]+ba[ext=m4a]/")
    assert downloads._generic_video_format("https://instagram.com.evil.example/reel/AbC123") == other


def test_instagram_audio_is_converted_to_aac_lc(monkeypatch, tmp_path):
    source = tmp_path / "reel.mp4"
    source.write_bytes(b"original")
    monkeypatch.setattr(downloads, "_audio_stream_info", lambda path: {
        "codec_name": "aac", "profile": "LC" if ".tmp." in path.name else "HE-AAC",
    })
    commands = []

    class Process:
        returncode = 0

        def communicate(self):
            temporary = tmp_path / "reel.audio-compatible.tmp.mp4"
            temporary.write_bytes(b"compatible")
            return "", ""

    class Control:
        def check(self):
            pass

        def unregister_process(self, process):
            pass

    def run(command, control):
        commands.append(command)
        return Process()

    monkeypatch.setattr(downloads, "run_managed_process", run)
    downloads._ensure_instagram_audio_compatibility(source, lambda *_: None, Control())
    assert source.read_bytes() == b"compatible"
    assert not (tmp_path / "reel.audio-compatible.tmp.mp4").exists()
    assert commands[0][commands[0].index("-c:v") + 1] == "copy"
    assert commands[0][commands[0].index("-profile:a") + 1] == "aac_low"


def test_instagram_aac_lc_audio_is_left_unchanged(monkeypatch, tmp_path):
    source = tmp_path / "reel.mp4"
    source.write_bytes(b"already-compatible")
    monkeypatch.setattr(downloads, "_audio_stream_info", lambda _: {"codec_name": "aac", "profile": "LC"})
    monkeypatch.setattr(downloads, "run_managed_process", lambda *_: pytest.fail("unneeded transcode"))
    downloads._ensure_instagram_audio_compatibility(source, lambda *_: None, None)
    assert source.read_bytes() == b"already-compatible"


def test_missing_audio_is_not_treated_as_compatible(monkeypatch, tmp_path):
    monkeypatch.setattr(downloads, "_audio_stream_info", lambda _: None)
    with pytest.raises(RemoteDownloadError, match="no audio track"):
        downloads._ensure_instagram_audio_compatibility(tmp_path / "reel.mp4", lambda *_: None, None)


def test_audio_failure_cannot_fall_back_to_video_only_html(monkeypatch, tmp_path):
    monkeypatch.setattr(downloads, "validate_public_url", lambda _: None)
    monkeypatch.setattr(downloads, "_direct_probe", lambda _: None)
    monkeypatch.setattr(downloads, "_download_instagram_photos", lambda *_: None)
    def fail(*_):
        raise RemoteDownloadError("audio conversion failed")
    monkeypatch.setattr(downloads, "_download_generic_video", fail)
    monkeypatch.setattr(downloads, "_html_media_candidates", lambda _: pytest.fail("unsafe fallback"))
    with pytest.raises(RemoteDownloadError, match="audio conversion failed"):
        downloads.download_public_media("https://www.instagram.com/reel/test", tmp_path, lambda *_: None, None)


def test_final_output_path_ignores_newer_intermediate(monkeypatch, tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"merged")
    (tmp_path / "final.f123.mp4").write_bytes(b"video-only")
    log = "MFOUTPUT:" + json.dumps(str(final))
    assert downloads._finished_download(tmp_path, log) == final
    with pytest.raises(RemoteDownloadError, match="verified final"):
        downloads._finished_download(tmp_path, "no final path")
    with pytest.raises(RemoteDownloadError, match="verified final"):
        downloads._finished_download(tmp_path, "MFOUTPUT:" + json.dumps(str(tmp_path.parent / "outside.mp4")))


def test_youtube_provider_has_bounded_client_fallback(monkeypatch):
    monkeypatch.setattr(downloads.shutil, "which", lambda name: "/usr/local/bin/chromium-token" if name == "chromium-token" else None)
    attempts = downloads._youtube_client_options()
    assert len(attempts) == 2
    assert "youtube:player_client=mweb,web_safari" in attempts[0]
    assert attempts[1] == []
    assert downloads._youtube_retryable("ERROR: Sign in to confirm you're not a bot")
    assert not downloads._youtube_retryable("Private video")
