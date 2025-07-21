import magic
import validators
import ipaddress
import socket
from urllib.parse import urlparse


def check_hostname(url):
    """Checks if URL is safe to stream from"""
    if not validators.url(url):
        raise ValueError(f"URL could not be validated: {url}")

    parsed_url = urlparse(url)

    def is_private_ip(host):
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local

    ip = socket.gethostbyname(parsed_url.hostname)
    if is_private_ip(ip):
        raise ValueError(f"Attempted to use bad host: {parsed_url.hostname} {ip}")


def filter_headers(headers):
    """If server is run behind Cloudflare, many other headers are added which can prevent streaming from external server, so only keep a few"""
    allowed_headers = {
        "User-Agent",
        "Accept-Encoding",
        "Accept",
        "Connection",
        "Range",
        "Icy-Metadata",
    }
    return {header: value for header, value in headers if header in allowed_headers}


def check_file_mime(file_bytes, allowed_mime_types):
    """Checks given bytes are of an approved MIME type"""
    detected_mime = magic.from_buffer(file_bytes[:1024], mime=True)

    if detected_mime not in allowed_mime_types:
        raise ValueError(f"Detected MIME type is not allowed: {detected_mime}")
