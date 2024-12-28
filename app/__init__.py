import logging
import os
from flask import Flask

EXTERNAL_PROXY = os.getenv("EXTERNAL_PROXY")

def create_app():
    app = Flask(__name__)

    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s"
    )

    logging.info(f"Using proxy server: {EXTERNAL_PROXY}")

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    from app.feed import bp as feed_bp
    app.register_blueprint(feed_bp, url_prefix="/feed")

    from app.stream import bp as stream_bp
    app.register_blueprint(stream_bp, url_prefix="/stream")

    return app
