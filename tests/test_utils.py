import ipaddress
import socket
from unittest.mock import Mock
import pytest
from app.utils import (
    check_hostname,
    check_file_mime,
    filter_headers,
    filter_response_headers,
    read_capped,
    safe_get,
)


@pytest.fixture
def stub_dns(monkeypatch):
    """Resolve any non-literal hostname to a public IP, so redirect tests stay offline"""

    def fake_gethostbyname(host):
        try:
            ipaddress.ip_address(host)
            return host  # already a literal, judge it as-is
        except ValueError:
            return "93.184.216.34"

    monkeypatch.setattr(socket, "gethostbyname", fake_gethostbyname)


def redirect_to(location):
    return Mock(is_redirect=True, headers={"Location": location})


def final_response():
    return Mock(is_redirect=False)


def session_returning(*responses):
    session = Mock()
    session.get.side_effect = list(responses)
    return session


def requested_urls(session):
    return [call.args[0] for call in session.get.call_args_list]


def test_check_hostname_valid():
    check_hostname("https://www.google.com")


def test_check_hostname_invalid():
    with pytest.raises(ValueError):
        check_hostname("http://localhost")


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud instance metadata
        "http://127.0.0.1:8080/admin",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/router",
        "http://172.16.0.1/internal",
        "http://0.0.0.0/",
        "http://[::1]/",  # IPv6 loopback
    ],
)
def test_check_hostname_blocks_internal_targets(url):
    """The SSRF boundary: none of these may ever be reachable through the proxy"""
    with pytest.raises(ValueError):
        check_hostname(url)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://example.com/",
        "not a url at all",
        "",
    ],
)
def test_check_hostname_rejects_non_http_urls(url):
    with pytest.raises(ValueError):
        check_hostname(url)


def test_check_hostname_unresolvable_raises_value_error():
    """Must be ValueError, not socket.gaierror, so callers can catch it"""
    with pytest.raises(ValueError, match="Could not resolve host"):
        check_hostname("https://this-host-does-not-exist-xyzzy.invalid/rss")


def test_check_file_mime_valid():
    check_file_mime(b"<?xml version='1.0' encoding='UTF-8'?>", {"text/xml"})


def test_check_file_mime_invalid():
    with pytest.raises(ValueError):
        check_file_mime(b"GIF89a", {"application/xml"})


def test_filter_headers_keeps_allowed():
    headers = [("User-Agent", "podcast-app/1.0"), ("Range", "bytes=0-1023")]
    assert filter_headers(headers) == {
        "User-Agent": "podcast-app/1.0",
        "Range": "bytes=0-1023",
    }


def test_filter_headers_is_case_insensitive():
    """HTTP header names are case-insensitive; dropping Range would break seeking"""
    headers = [("user-agent", "podcast-app/1.0"), ("range", "bytes=0-1023")]
    assert filter_headers(headers) == {
        "user-agent": "podcast-app/1.0",
        "range": "bytes=0-1023",
    }


def test_filter_headers_strips_proxy_added_headers():
    headers = [
        ("Accept", "*/*"),
        ("CF-Connecting-IP", "1.2.3.4"),
        ("CF-Ray", "abc123"),
        ("X-Forwarded-For", "1.2.3.4"),
        ("Cookie", "session=secret"),
    ]
    assert filter_headers(headers) == {"Accept": "*/*"}


def test_safe_get_follows_normal_redirects(stub_dns):
    """Podcast CDNs redirect constantly, so this must keep working"""
    session = session_returning(
        redirect_to("https://cdn.example.com/ep1.mp3"), final_response()
    )

    response = safe_get(session, "https://tracking.example.com/ep1.mp3")

    assert response.is_redirect is False
    assert requested_urls(session) == [
        "https://tracking.example.com/ep1.mp3",
        "https://cdn.example.com/ep1.mp3",
    ]


def test_safe_get_resolves_relative_redirects(stub_dns):
    session = session_returning(redirect_to("/actual/ep1.mp3"), final_response())

    safe_get(session, "https://cdn.example.com/old/ep1.mp3")

    assert requested_urls(session)[1] == "https://cdn.example.com/actual/ep1.mp3"


@pytest.mark.parametrize(
    "internal_url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:6379/",
        "http://10.0.0.5/internal",
    ],
)
def test_safe_get_blocks_redirect_to_internal_address(stub_dns, internal_url):
    """A permitted host must not be able to bounce us somewhere internal"""
    session = session_returning(redirect_to(internal_url), final_response())

    with pytest.raises(ValueError):
        safe_get(session, "https://evil.example.com/ep1.mp3")

    # the internal address was never actually requested
    assert requested_urls(session) == ["https://evil.example.com/ep1.mp3"]


def test_safe_get_never_requests_an_unchecked_first_url():
    session = session_returning(final_response())

    with pytest.raises(ValueError):
        safe_get(session, "http://127.0.0.1/secret")

    session.get.assert_not_called()


def test_safe_get_gives_up_on_redirect_loop():
    session = Mock()
    session.get.return_value = redirect_to("https://example.com/loop")

    with pytest.raises(ValueError, match="Exceeded"):
        safe_get(session, "https://example.com/loop")


def body_of(*chunks):
    response = Mock()
    response.iter_content.return_value = iter(chunks)
    return response


def test_read_capped_returns_body_under_limit():
    assert read_capped(body_of(b"abc", b"def"), max_bytes=100) == b"abcdef"


def test_read_capped_refuses_oversized_body():
    """A hostile feed must not be buffered into memory unbounded"""
    response = body_of(b"x" * 8192, b"x" * 8192, b"x" * 8192)

    with pytest.raises(ValueError, match="exceeds"):
        read_capped(response, max_bytes=10000)

    response.close.assert_called_once()


def test_read_capped_ignores_lying_content_length():
    """The cap is enforced on bytes actually read, not on the declared length"""
    response = body_of(b"x" * 5000, b"x" * 5000)
    response.headers = {"Content-Length": "10"}  # upstream understates the size

    with pytest.raises(ValueError, match="exceeds"):
        read_capped(response, max_bytes=1000)


def test_filter_response_headers_blocks_set_cookie():
    """An arbitrary upstream must not set cookies on the proxy's own domain"""
    headers = {
        "Content-Type": "audio/mpeg",
        "Set-Cookie": "session=attacker",
        "Strict-Transport-Security": "max-age=99999",
        "Server": "nginx",
    }
    assert filter_response_headers(headers) == {"Content-Type": "audio/mpeg"}


def test_filter_response_headers_keeps_range_support():
    """Seeking in a podcast client depends on these surviving"""
    headers = {
        "Content-Type": "audio/mpeg",
        "Accept-Ranges": "bytes",
        "Content-Range": "bytes 0-1023/5000",
        "Content-Length": "1024",
        "ETag": '"abc"',
    }
    assert filter_response_headers(headers) == headers


def test_filter_response_headers_drops_stale_length_when_decompressed():
    """iter_content already gunzipped the body, so both headers now lie"""
    headers = {
        "Content-Type": "audio/mpeg",
        "Content-Encoding": "gzip",
        "Content-Length": "512",
    }
    assert filter_response_headers(headers) == {"Content-Type": "audio/mpeg"}


def test_filter_response_headers_keeps_icy_metadata():
    headers = {"Content-Type": "audio/mpeg", "icy-metaint": "16000", "icy-br": "128"}
    assert filter_response_headers(headers) == headers


def test_safe_get_passes_through_kwargs(stub_dns):
    session = session_returning(final_response())

    safe_get(session, "https://cdn.example.com/ep1.mp3", stream=True, headers={"A": "b"})

    _, kwargs = session.get.call_args
    assert kwargs["stream"] is True
    assert kwargs["headers"] == {"A": "b"}
    assert kwargs["allow_redirects"] is False
