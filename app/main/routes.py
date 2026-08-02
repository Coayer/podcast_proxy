from flask import Response, send_from_directory, request
import logging
from app.main import bp


@bp.route("/")
def index() -> Response:
    logging.info(f"[{request.user_agent}] Requested: /")
    return send_from_directory("static", "index.html")
