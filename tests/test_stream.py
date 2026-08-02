from unittest.mock import Mock, patch
import base64
import os
import time
import pytest

import requests
from requests.cookies import extract_cookies_to_jar

import app as app_module
from app.stream.routes import (
    CACHE_TTL_SECONDS,
    MAX_DOWNLOAD_BYTES,
    checked_stream_body,
    generic_stream,
    sweep_cache,
    youtube_stream,
)


def encode(url):
    return base64.urlsafe_b64encode(url.encode()).decode()

MP3_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 100


def make_upstream(chunks, content_length=None):
    """Fake a streamed requests.Response yielding the given chunks"""
    response = Mock()
    response.headers = {} if content_length is None else {"Content-Length": content_length}
    response.iter_content.return_value = iter(chunks)
    return response


def test_proxy_media_generic_stream(client):
    with patch("app.stream.routes.generic_stream") as mock_generic_stream:
        mock_generic_stream.return_value = "generic stream success"
        url = base64.urlsafe_b64encode(b"https://example.com/audio.mp3").decode()
        response = client.get(f"/stream/{url}")
        assert response.status_code == 200
        assert response.data == b"generic stream success"


def test_proxy_media_youtube_stream(client):
    with patch("app.stream.routes.youtube_stream") as mock_youtube_stream:
        mock_youtube_stream.return_value = "youtube stream success"
        url = base64.urlsafe_b64encode(
            b"https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        ).decode()
        response = client.get(f"/stream/{url}")
        assert response.status_code == 200
        assert response.data == b"youtube stream success"


def test_checked_stream_body_does_not_drop_first_chunk():
    """The chunk consumed by the MIME check must still reach the client"""
    upstream = make_upstream([MP3_BYTES, b"second", b"third"])

    body = checked_stream_body(upstream, "https://example.com/audio.mp3")

    assert b"".join(body) == MP3_BYTES + b"second" + b"third"


def test_checked_stream_body_rejects_disallowed_mime():
    upstream = make_upstream([b"<html><body>not audio</body></html>"])

    with pytest.raises(ValueError, match="MIME type is not allowed"):
        list(checked_stream_body(upstream, "https://example.com/audio.mp3"))


def test_checked_stream_body_rejects_oversize_response():
    upstream = make_upstream([MP3_BYTES], content_length="400000000")

    with pytest.raises(ValueError, match="exceeds"):
        list(checked_stream_body(upstream, "https://example.com/audio.mp3"))


def test_checked_stream_body_skips_mime_check_for_megaphone():
    """megaphone.fm mp3s detect as application/octet-stream, so the check is bypassed"""
    upstream = make_upstream([b"\x00\x01\x02 arbitrary octet-stream bytes"])

    body = checked_stream_body(upstream, "https://traffic.megaphone.fm/x.mp3")

    assert b"".join(body) == b"\x00\x01\x02 arbitrary octet-stream bytes"


@pytest.mark.parametrize(
    "video_id",
    [
        "../../../../tmp/pwned",
        "..%2f..%2fetc%2fpasswd",
        "sub/dir/file",
        "with.dot",
        "",
    ],
)
def test_youtube_stream_rejects_traversal_in_video_id(app, video_id):
    """video_id becomes a cache filename, so it must not be able to escape the dir"""
    with app.test_request_context():
        with pytest.raises(ValueError, match="Invalid YouTube video ID"):
            youtube_stream(f"https://www.youtube.com/watch?v={video_id}")


def test_youtube_stream_rejects_missing_video_id(app):
    with app.test_request_context():
        with pytest.raises(ValueError, match="Invalid YouTube video ID"):
            youtube_stream("https://www.youtube.com/watch?list=PL123")


def point_cache_at(app, tmp_path):
    """youtube_stream caches in <root_path>/../cache, so relocate root_path"""
    app.root_path = str(tmp_path / "app")
    return tmp_path / "cache"


def test_youtube_stream_serves_from_cache_on_hit(app, tmp_path):
    """A cached file is served without invoking yt-dlp"""
    cache_dir = point_cache_at(app, tmp_path)
    cache_dir.mkdir()
    (cache_dir / "dQw4w9WgXcQ.m4a").write_bytes(b"cached audio")

    with app.test_request_context():
        with patch("app.stream.routes.yt_dlp.YoutubeDL") as mock_ydl:
            response = youtube_stream("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    mock_ydl.assert_not_called()
    assert response.status_code == 200


def test_youtube_stream_downloads_on_cache_miss(app, tmp_path):
    cache_dir = point_cache_at(app, tmp_path)

    def fake_download(urls):
        (cache_dir / "dQw4w9WgXcQ.m4a").write_bytes(b"downloaded audio")

    with app.test_request_context():
        with patch("app.stream.routes.yt_dlp.YoutubeDL") as mock_ydl:
            mock_ydl.return_value.__enter__.return_value.download = fake_download
            response = youtube_stream("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert mock_ydl.called
    ydl_opts = mock_ydl.call_args[0][0]
    assert ydl_opts["outtmpl"] == os.path.join(str(cache_dir), "dQw4w9WgXcQ.m4a")
    assert response.status_code == 200


def age_file(path, seconds_old):
    stamp = time.time() - seconds_old
    os.utime(path, (stamp, stamp))


def test_sweep_cache_removes_expired_and_keeps_fresh(tmp_path):
    stale = tmp_path / "old.m4a"
    fresh = tmp_path / "new.m4a"
    stale.write_bytes(b"old")
    fresh.write_bytes(b"new")
    age_file(stale, CACHE_TTL_SECONDS + 60)

    sweep_cache(str(tmp_path))

    assert not stale.exists()
    assert fresh.exists()


def test_sweep_cache_ignores_non_cache_files(tmp_path):
    """Only .m4a entries are ours to delete"""
    other = tmp_path / "important.txt"
    other.write_bytes(b"not ours")
    age_file(other, CACHE_TTL_SECONDS + 60)

    sweep_cache(str(tmp_path))

    assert other.exists()


def test_sweep_cache_survives_file_vanishing_mid_sweep(tmp_path):
    """Another worker may remove the same entry concurrently"""
    stale = tmp_path / "old.m4a"
    stale.write_bytes(b"old")
    age_file(stale, CACHE_TTL_SECONDS + 60)

    with patch("app.stream.routes.os.remove", side_effect=FileNotFoundError):
        sweep_cache(str(tmp_path))  # must not raise


def test_youtube_stream_sweeps_and_caps_download_on_miss(app, tmp_path):
    cache_dir = point_cache_at(app, tmp_path)
    cache_dir.mkdir(parents=True)

    stale = cache_dir / "oldvideo.m4a"
    stale.write_bytes(b"old")
    age_file(stale, CACHE_TTL_SECONDS + 60)

    def fake_download(urls):
        (cache_dir / "dQw4w9WgXcQ.m4a").write_bytes(b"downloaded")

    with app.test_request_context():
        with patch("app.stream.routes.yt_dlp.YoutubeDL") as mock_ydl:
            mock_ydl.return_value.__enter__.return_value.download = fake_download
            youtube_stream("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert not stale.exists()  # swept on the miss
    assert mock_ydl.call_args[0][0]["max_filesize"] == MAX_DOWNLOAD_BYTES


def test_youtube_stream_does_not_sweep_on_cache_hit(app, tmp_path):
    """A hit is the fast path; it should not pay for a directory scan"""
    cache_dir = point_cache_at(app, tmp_path)
    cache_dir.mkdir(parents=True)
    (cache_dir / "dQw4w9WgXcQ.m4a").write_bytes(b"cached")

    with app.test_request_context():
        with patch("app.stream.routes.sweep_cache") as mock_sweep:
            youtube_stream("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    mock_sweep.assert_not_called()


def test_youtube_stream_errors_when_download_writes_nothing(app, tmp_path):
    """max_filesize aborts without writing, which must not surface as a missing file"""
    cache_dir = point_cache_at(app, tmp_path)
    cache_dir.mkdir(parents=True)

    with app.test_request_context():
        with patch("app.stream.routes.yt_dlp.YoutubeDL") as mock_ydl:
            mock_ydl.return_value.__enter__.return_value.download = lambda urls: None
            with pytest.raises(ValueError, match="produced no file"):
                youtube_stream("https://www.youtube.com/watch?v=dQw4w9WgXcQ")


def upstream_with(headers):
    response = Mock(status_code=200, headers=headers)
    response.iter_content.return_value = iter([b"audio bytes"])
    response.raise_for_status.return_value = None
    return response


def test_generic_stream_strips_upstream_set_cookie(app):
    """A hostile upstream must not set cookies on the proxy's own domain"""
    upstream = upstream_with(
        {"Content-Type": "audio/mpeg", "Set-Cookie": "session=attacker"}
    )

    with app.test_request_context():
        with patch("app.stream.routes.safe_get", return_value=upstream):
            response = generic_stream("https://cdn.example.com/ep1.mp3")

    assert "Set-Cookie" not in response.headers
    assert response.headers["Content-Type"] == "audio/mpeg"


def test_generic_stream_preserves_range_headers(app):
    """Seeking must keep working for normal playback"""
    upstream = upstream_with(
        {
            "Content-Type": "audio/mpeg",
            "Accept-Ranges": "bytes",
            "Content-Range": "bytes 0-1023/5000",
        }
    )

    with app.test_request_context():
        with patch("app.stream.routes.safe_get", return_value=upstream):
            response = generic_stream("https://cdn.example.com/ep1.mp3")

    assert response.headers["Accept-Ranges"] == "bytes"
    assert response.headers["Content-Range"] == "bytes 0-1023/5000"


def test_shared_session_does_not_store_upstream_cookies():
    """One Session serves every user, so its jar must not accumulate their cookies"""
    raw = Mock()
    raw._original_response.msg.get_all.return_value = [
        "evil=1; Domain=cdn.example.com; Path=/"
    ]
    prepared = requests.Request("GET", "https://cdn.example.com/ep1.mp3").prepare()

    app_module.session.cookies.clear()
    extract_cookies_to_jar(app_module.session.cookies, prepared, raw)

    assert len(app_module.session.cookies) == 0


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/secret",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/internal",
    ],
)
def test_proxy_media_blocks_internal_targets(client, url):
    """End-to-end: an internal address must never be fetched"""
    with patch("app.stream.routes.app.session.get") as mock_get:
        response = client.get(f"/stream/{encode(url)}")

    mock_get.assert_not_called()
    assert response.status_code == 500
