"""gunicorn entry point: gunicorn nyabolag.wsgi:app"""
from .web import create_app

app = create_app()
