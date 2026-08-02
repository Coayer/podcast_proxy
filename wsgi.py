from flask import Flask

from app import create_app

application: Flask = create_app()