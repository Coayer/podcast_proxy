import logging
import os
import requests
from http import cookiejar
from flask import Flask

EXTERNAL_PROXY: str | None = os.getenv("EXTERNAL_PROXY")
ENABLE_STREAMING_SAFETY_CHECK: bool = (
    os.getenv("ENABLE_STREAMING_SAFETY_CHECK", "false").lower() == "true"
)

class BlockAllCookies(cookiejar.DefaultCookiePolicy):
    """Refuse to store or send cookies.

    One Session is shared by every request, so a cookie set by one upstream would
    otherwise be replayed on another user's request to that same host. Client
    cookies are already stripped by filter_headers, so nothing here relies on them.
    """

    def set_ok(self, cookie, request) -> bool:
        return False

    def return_ok(self, cookie, request) -> bool:
        return False


session: requests.Session = requests.Session()
session.cookies.set_policy(BlockAllCookies())


def create_app() -> Flask:
    app = Flask(__name__)

    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s"
    )

    logging.info(f"Using proxy server: {EXTERNAL_PROXY}")
    logging.info(f"Streaming safety check enabled: {ENABLE_STREAMING_SAFETY_CHECK}")

    from app.main import bp as main_bp

    app.register_blueprint(main_bp)

    from app.feed import bp as feed_bp

    app.register_blueprint(feed_bp, url_prefix="/feed")

    from app.stream import bp as stream_bp

    app.register_blueprint(stream_bp, url_prefix="/stream")

    return app
