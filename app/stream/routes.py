import requests
import base64
import logging
import yt_dlp
from itertools import tee
from cachetools import cached, TTLCache
from flask import Response, request
from urllib.parse import urlparse

import app
from app.utils import check_url, filter_headers, check_file_safety
from app.stream import bp


@cached(cache=TTLCache(maxsize=64, ttl=3600))
def get_youtube_audio_url(video_url):
    """Gets YouTube video audio track file as a URL"""
    with yt_dlp.YoutubeDL({"format": "bestaudio[ext=m4a]", "quiet": True}) as ydl:
        song_info = ydl.extract_info(video_url, download=False)

    return song_info["url"]


@bp.route("/<path:encoded_url>")
def proxy_media(encoded_url):
    """Streams file located at given base64-encoded URL by forwarding HTTP requests and returning upstream responses"""
    try:
        stream_url = base64.urlsafe_b64decode(encoded_url.encode()).decode() # b64 functions get and return encoded bytes, not strings
        check_url(stream_url)

        logging.info(f"Streaming: {stream_url}")

        if urlparse(stream_url).netloc == "www.youtube.com":
            stream_url = get_youtube_audio_url(stream_url)

        headers = filter_headers(request.headers.items())
        upstream_response = requests.get(
            stream_url,
            proxies={"https": app.EXTERNAL_PROXY},
            headers=headers,
            allow_redirects=True,
            stream=True,
        )
        upstream_response.raise_for_status()

        response_generator = upstream_response.iter_content(chunk_size=8192)

        # Check if file being streamed is safe
        if (
                app.STREAMING_SAFETY_CHECK and (upstream_response.status_code == 206 or upstream_response.status_code == 200)
        ): # other status codes not relevant
            check_generator, response_generator = tee(
                upstream_response.iter_content(chunk_size=8192)
            )  # Checking first iter of generator will remove that chunk from the generator, so create duplicate generators
            stream_mime_types = {"audio/mpeg", "audio/x-mpeg", "audio/mp3", "audio/wav", "audio/ogg",
                                 "video/mp4",  # mp4 needed for youtube
                                 "application/octet-stream", "text/plain"}
            check_file_safety(next(check_generator), stream_mime_types, 50000000)

        return Response(
            response_generator,
            status=upstream_response.status_code,
            headers=upstream_response.headers,
        )
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP error occurred: {e}")
        return "Failed to stream from upstream server", e.response.status_code
    except ValueError as e:
        logging.error(f"Requested stream was unsafe: {e}")
        return "Invalid stream file", 403
    except Exception as e:
        logging.error(f"Error streaming media: {e}")
        return "Failed...", 500
