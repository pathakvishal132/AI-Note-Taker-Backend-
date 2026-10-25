import os

# Gunicorn configuration for Render deployment
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = 1  # Keep 1 worker to stay well within Render free tier memory (512MB RAM)
timeout = 180  # 180 seconds to allow faster-whisper transcription without worker timeouts
keepalive = 5
max_requests = 100
max_requests_jitter = 10
