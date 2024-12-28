from flask import Blueprint

bp = Blueprint("stream", __name__)

from app.stream import routes
