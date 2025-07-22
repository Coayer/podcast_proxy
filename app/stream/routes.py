import base64
import logging
import os
import yt_dlp
from itertools import tee
from flask import Response, request, send_file, current_app
from urllib.parse import urlparse, parse_qs
import app
from app.utils import check_hostname, filter_headers, check_file_mime
from app.stream import bp


def youtube_stream(stream_url):
    """Handle YouTube video streaming by downloading and caching audio"""
    parsed_url = urlparse(stream_url)
    video_id = parse_qs(parsed_url.query)["v"][0]
    cache_dir = os.path.abspath(os.path.join(current_app.root_path, "..", "cache"))
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    cache_path = os.path.join(cache_dir, f"{video_id}.m4a")

    if not os.path.exists(cache_path):
        logging.info(f"Cache miss for {stream_url}. Downloading to {cache_path}")
        ydl_opts = {
            "format": "bestaudio[ext=m4a]",
            "outtmpl": cache_path,
            "quiet": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([stream_url])
        logging.info(f"Downloaded {stream_url} to cache.")
    else:
        logging.info(f"Cache hit for {stream_url}. Serving from {cache_path}")

    return send_file(cache_path, mimetype="audio/mp4")


def perform_safety_check(upstream_response, stream_url):
    """Perform safety checks on an upstream response"""
    # Check file size limit
    max_size_bytes = 300000000  # 300MB limit
    content_length = upstream_response.headers.get("Content-Length")
    if content_length and int(content_length) > max_size_bytes:
        raise ValueError(
            f"File size {int(content_length) / 1000000:.2f}MB exceeds {max_size_bytes / 1000000}MB limit."
        )

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
    if not (
        urlparse(stream_url).netloc == "traffic.megaphone.fm"
        and stream_url.endswith(".mp3")
    ):
        check_response = tee(
            upstream_response.iter_content(chunk_size=8192)
        )  # Duplicate the upstream response iterator
        check_file_mime(next(check_response), stream_mime_types)


def generic_stream(stream_url):
    headers = filter_headers(request.headers.items())
    upstream_response = app.session.get(
        stream_url,
        proxies={"https": app.EXTERNAL_PROXY},
        headers=headers,
        allow_redirects=True,
        stream=True,
    )
    upstream_response.raise_for_status()

    if app.ENABLE_STREAMING_SAFETY_CHECK and upstream_response.status_code in (
        200,
        206,
    ):  # Only perform checks on successful responses
        try:
            perform_safety_check(upstream_response, stream_url)
        except ValueError as e:
            logging.error(f"Safety check failed for {stream_url}: {e}")
            return "Invalid stream file", 403

    return Response(
        upstream_response.iter_content(chunk_size=8192),
        status=upstream_response.status_code,
        headers=dict(upstream_response.headers),
    )


@bp.route("/<path:encoded_url>")
def proxy_media(encoded_url):
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
