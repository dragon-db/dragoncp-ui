import os


bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

# Keep this service single-worker until Socket.IO state and background threads
# are redesigned for multi-process coordination.
workers = 1
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "8"))

timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", "5"))

accesslog = "-"
errorlog = "-"
capture_output = True
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
