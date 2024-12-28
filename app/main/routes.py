import logging
from flask import render_template, request

from app.main import bp

@bp.route("/")
def index():
    logging.info(f"/ request: {request.user_agent}")
    return render_template("index.html")