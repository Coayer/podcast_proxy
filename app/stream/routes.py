import base64
import logging
import os
import re
import time
import requests
import yt_dlp
from collections.abc import Iterator
from itertools import chain
from flask import Response, request, send_file, current_app
from urllib.parse import urlparse, parse_qs
import app
from app.utils import (
    check_hostname,
    filter_headers,
    filter_response_headers,
    check_file_mime,
    safe_get,
)
from app.stream import bp


# Video IDs land in a cache filename, so restrict them to characters that cannot
# traverse out of the cache directory
VIDEO_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")

CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # a swept entry only costs one re-download
MAX_DOWNLOAD_BYTES = 500_000_000  # refuse to cache a single oversized video


def sweep_cache(cache_dir: str, ttl_seconds: int = CACHE_TTL_SECONDS) -> None:
    """Delete cache entries past their TTL.

    Without this the cache grows forever, since every distinct video ID writes a
    file that is never removed. Failures are logged rather than raised: a sweep
    problem must not take down the request that triggered it.
    """
    cutoff = time.time() - ttl_seconds

    for entry in os.scandir(cache_dir):
        if not entry.name.endswith(".m4a") or not entry.is_file():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                os.remove(entry.path)
                logging.info(f"Evicted stale cache entry: {entry.name}")
        except OSError as e:
            # another worker may have swept or replaced it already
            logging.warning(f"Could not sweep {entry.name}: {e}")


def youtube_stream(stream_url: str) -> Response:
    """Handle YouTube video streaming by downloading and caching audio"""
    parsed_url = urlparse(stream_url)

    video_ids = parse_qs(parsed_url.query).get("v", [])
    if not video_ids or not VIDEO_ID_PATTERN.fullmatch(video_ids[0]):
        raise ValueError(f"Invalid YouTube video ID in URL: {stream_url}")
    video_id = video_ids[0]

    cache_dir = os.path.abspath(os.path.join(current_app.root_path, "..", "cache"))
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    cache_path = os.path.join(cache_dir, f"{video_id}.m4a")

    if not os.path.exists(cache_path):
        logging.info(f"Cache miss for {stream_url}. Downloading to {cache_path}")

        # sweep before growing the cache, so the work happens on the slow path
        sweep_cache(cache_dir)

        ydl_opts = {
            "format": "bestaudio[ext=m4a]",
            "outtmpl": cache_path,
            "quiet": True,
            "max_filesize": MAX_DOWNLOAD_BYTES,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([stream_url])

        # max_filesize aborts without writing anything, so report that plainly
        # rather than letting send_file fail on a missing path
        if not os.path.exists(cache_path):
            raise ValueError(f"Download produced no file (size limit?): {stream_url}")

        logging.info(f"Downloaded {stream_url} to cache.")
    else:
        logging.info(f"Cache hit for {stream_url}. Serving from {cache_path}")

    return send_file(cache_path, mimetype="audio/mp4")


def checked_stream_body(
    upstream_response: requests.Response, stream_url: str
) -> Iterator[bytes]:
    """Perform safety checks on an upstream response.

    Returns the iterator to stream to the client, with any bytes consumed by the
    MIME check chained back on so nothing is dropped.
    """
    # Check file size limit
    max_size_bytes = 300000000  # 300MB limit
    content_length = upstream_response.headers.get("Content-Length")
    if content_length and int(content_length) > max_size_bytes:
        raise ValueError(
            f"File size {int(content_length) / 1000000:.2f}MB exceeds {max_size_bytes / 1000000}MB limit."
        )

    body = upstream_response.iter_content(chunk_size=8192)

    # Check file content safety
    stream_mime_types = {
        "audio/mpeg",
        "audio/x-mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/wav",
        "audio/ogg",
    }

    # megaphone.fm mp3 streams are detected as application/octet-stream, so have to assume they are safe
    if (
        urlparse(stream_url).netloc == "traffic.megaphone.fm"
        and stream_url.endswith(".mp3")
    ):
        return body

    first_chunk = next(body, b"")
    check_file_mime(first_chunk, stream_mime_types)
    return chain([first_chunk], body)


def generic_stream(stream_url: str) -> Response | tuple[str, int]:
    headers = filter_headers(request.headers.items())
    upstream_response = safe_get(
        app.session,
        stream_url,
        proxies={"http": app.EXTERNAL_PROXY, "https": app.EXTERNAL_PROXY},
        headers=headers,
        stream=True,
    )
    upstream_response.raise_for_status()

    if app.ENABLE_STREAMING_SAFETY_CHECK and upstream_response.status_code in (
        200,
        206,
    ):  # Only perform checks on successful responses
        try:
            body = checked_stream_body(upstream_response, stream_url)
        except ValueError as e:
            logging.error(f"Safety check failed for {stream_url}: {e}")
            return "Invalid stream file", 403
    else:
        body = upstream_response.iter_content(chunk_size=8192)

    return Response(
        body,
        status=upstream_response.status_code,
        headers=filter_response_headers(upstream_response.headers),
    )


@bp.route("/<path:encoded_url>")
def proxy_media(encoded_url: str) -> Response | tuple[str, int]:
    """Streams file located at given base64-encoded URL"""
    try:
        stream_url = base64.urlsafe_b64decode(encoded_url.encode()).decode()
        logging.info(f"[{request.user_agent}] Streaming: {stream_url}")

        if urlparse(stream_url).netloc == "www.youtube.com":
            return youtube_stream(stream_url)

        check_hostname(stream_url)
        return generic_stream(stream_url)
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return "An internal server error occurred", 500
