import requests
import base64
import logging
from itertools import tee
from flask import Response, request

import app
from app.utils import check_url, filter_headers, check_file
from app.stream import bp

@bp.route("/<path:encoded_url>")
def proxy_media(encoded_url):
    try:
        original_url = base64.urlsafe_b64decode(encoded_url.encode()).decode()
        check_url(original_url)

        logging.info(f"Streaming: {original_url}")

        headers = filter_headers(request.headers.items())
        media_response = requests.get(
            original_url,
            proxies={"https": app.EXTERNAL_PROXY},
            headers=headers,
            allow_redirects=True,
            stream=True,
        )
        media_response.raise_for_status()

        check_gen, response_gen = tee(
            media_response.iter_content(chunk_size=120000)
        )  # Checking first iter of gen will remove it from the gen, so duplicate the generator

        if (
            media_response.status_code == 206 or media_response.status_code == 200
        ):  # Redirects will return text, want to check the final file
            stream_mime_types = {"audio/mpeg", "audio/x-mpeg", "audio/mp3", "audio/wav", "audio/ogg",
                                 "application/octet-stream", "text/plain"}
            check_file(next(check_gen), stream_mime_types, 50000000)

        return Response(
            response_gen,
            status=media_response.status_code,
            headers=media_response.headers,
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