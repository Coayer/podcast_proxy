import logging

import magic
import validators
import ipaddress
import socket
from urllib.parse import urlparse


def check_url(url):
    if not validators.url(url):
        raise ValueError(f"URL could not be validated: {url}")

    parsed_url = urlparse(url)

    def is_private_ip(host):
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local

    ip = socket.gethostbyname(parsed_url.hostname)
    if is_private_ip(ip):
        raise ValueError(
            f"Attempted to use bad host: {parsed_url.hostname} {ip}"
        )


def filter_headers(headers):
    """Cloudflare adds many other headers which can prevent streaming from external server"""
    allowed_headers = {"User-Agent", "Accept-Encoding", "Accept", "Connection", "Range", "Icy-Metadata"}
    return {header: value for header, value in headers if header in allowed_headers}


def check_file(file_bytes, allowed_mime_types, max_size):
    """Checks file_bytes are approved types and size"""
    detected_mime = magic.from_buffer(file_bytes[:2048], mime=True)

    if detected_mime not in allowed_mime_types:
        raise ValueError(f"Detected MIME type is not allowed: {detected_mime}")

    if len(file_bytes) > max_size:
        raise ValueError(
            f"File size exceeds maximum allowed limit: {
            len(file_bytes) / 1000000}KB/{max_size / {1000000} }KB"
        )
