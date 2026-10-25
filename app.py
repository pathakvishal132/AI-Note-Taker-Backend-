"""WSGI entry point for hosting platforms like Render defaulting to 'gunicorn app:app'."""
import os
from notetaker.wsgi import application

# Expose 'app' for gunicorn app:app
app = application
