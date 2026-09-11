import app as app_module
from flask import request


def _make_app(monkeypatch, trusted_proxy_count):
    monkeypatch.setattr(app_module, "TRUSTED_PROXY_COUNT", trusted_proxy_count)
    flask_app = app_module.create_app()
    flask_app.config.update(TESTING=True)

    @flask_app.route("/scheme-check")
    def scheme_check():
        return f"{request.scheme}://{request.host}"

    return flask_app


def test_forwarded_headers_ignored_when_no_trusted_proxies(monkeypatch):
    client = _make_app(monkeypatch, 0).test_client()

    response = client.get(
        "/scheme-check",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "public.example.com"},
    )

    assert response.get_data(as_text=True) == "http://localhost"


def test_forwarded_headers_trusted_for_configured_hop_count(monkeypatch):
    client = _make_app(monkeypatch, 1).test_client()

    response = client.get(
        "/scheme-check",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "public.example.com"},
    )

    assert response.get_data(as_text=True) == "https://public.example.com"


def test_only_configured_hop_count_is_trusted(monkeypatch):
    # Two Proto values are present, but only 1 hop is configured as trusted, so
    # only the right-most (added by the actual reverse proxy) should be used -
    # a client-supplied left-most value must not be able to override it.
    client = _make_app(monkeypatch, 1).test_client()

    response = client.get(
        "/scheme-check",
        headers={"X-Forwarded-Proto": "http, https"},
    )

    assert response.get_data(as_text=True) == "https://localhost"
