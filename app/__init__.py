import logging
import os
import requests
from flask import Flask

EXTERNAL_PROXY = os.getenv("EXTERNAL_PROXY")
ENABLE_STREAMING_SAFETY_CHECK = (
    os.getenv("ENABLE_STREAMING_SAFETY_CHECK", "false").lower() == "true"
)

session = requests.Session()


def create_app():
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
