import magic
import requests
import validators
import ipaddress
import socket
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urljoin, urlparse

MAX_REDIRECTS = 5

# Response headers safe to relay to the client. Notably excludes Set-Cookie (an
# arbitrary upstream must not set cookies on the proxy's own domain) and
# Content-Encoding (iter_content has already decompressed the body, so it lies).
ALLOWED_RESPONSE_HEADERS = {
    "content-type",
    "accept-ranges",
    "content-range",
    "last-modified",
    "etag",
    "cache-control",
    "expires",
    "age",
    "date",
}


def check_hostname(url: str) -> None:
    """Checks if URL is safe to stream from"""
    if not validators.url(url):
        raise ValueError(f"URL could not be validated: {url}")

    parsed_url = urlparse(url)

    def is_private_ip(host: str) -> bool:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local

    hostname = parsed_url.hostname
    if hostname is None:
        raise ValueError(f"URL has no hostname: {url}")

    try:
        ip = socket.gethostbyname(hostname)
    except OSError as e:
        # Unresolvable hosts (and IPv6 literals, which gethostbyname cannot handle)
        # are refused rather than left to escape as a bare socket error
        raise ValueError(f"Could not resolve host: {hostname}") from e

    if is_private_ip(ip):
        raise ValueError(f"Attempted to use bad host: {hostname} {ip}")


def safe_get(
    session: requests.Session, url: str, **kwargs: Any
) -> requests.Response:
    """GET a URL, re-checking the host on every redirect hop.

    check_hostname only vets the URL it is handed. Redirects are followed as normal
    (podcast CDNs rely on them heavily) but a permitted host is not allowed to
    bounce us to an internal address.
    """
    for _ in range(MAX_REDIRECTS):
        check_hostname(url)
        response = session.get(url, allow_redirects=False, **kwargs)

        if not response.is_redirect:
            return response

        # Location may be relative, so resolve it against the URL we just fetched
        url = urljoin(url, response.headers["Location"])
        response.close()  # discard the redirect body before following

    raise ValueError(f"Exceeded {MAX_REDIRECTS} redirects, last: {url}")


def filter_headers(headers: Iterable[tuple[str, str]]) -> dict[str, str]:
    """If server is run behind Cloudflare, many other headers are added which can prevent streaming from external server, so only keep a few"""
    # Lowercased because HTTP header names are case-insensitive
    allowed_headers = {
        "user-agent",
        "accept-encoding",
        "accept",
        "connection",
        "range",
        "icy-metadata",
    }
    return {
        header: value for header, value in headers if header.lower() in allowed_headers
    }


def filter_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Only relay upstream response headers that a media client actually needs"""
    filtered = {
        header: value
        for header, value in headers.items()
        # icy-* carry shoutcast stream metadata, which clients request via Icy-Metadata
        if header.lower() in ALLOWED_RESPONSE_HEADERS or header.lower().startswith("icy-")
    }

    # Content-Length is only still accurate if the body was not decompressed in
    # transit; without it clients lose seeking, so keep it when it is trustworthy
    was_decompressed = any(h.lower() == "content-encoding" for h in headers)
    content_length = headers.get("Content-Length")
    if content_length is not None and not was_decompressed:
        filtered["Content-Length"] = content_length

    return filtered


def read_capped(response: requests.Response, max_bytes: int) -> bytes:
    """Read a response body into memory, refusing to buffer more than max_bytes.

    Content-Length is not trusted, since an upstream can omit or understate it.
    """
    chunks = []
    total = 0

    for chunk in response.iter_content(chunk_size=8192):
        total += len(chunk)
        if total > max_bytes:
            response.close()
            raise ValueError(f"Response body exceeds {max_bytes} byte limit")
        chunks.append(chunk)

    return b"".join(chunks)


def check_file_mime(file_bytes: bytes, allowed_mime_types: set[str]) -> None:
    """Checks given bytes are of an approved MIME type"""
    detected_mime = magic.from_buffer(file_bytes[:1024], mime=True)

    if detected_mime not in allowed_mime_types:
        raise ValueError(f"Detected MIME type is not allowed: {detected_mime}")
