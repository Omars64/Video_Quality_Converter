import socket

import pytest

from app.downloads import RemoteDownloadError, is_youtube_url, validate_public_url


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
