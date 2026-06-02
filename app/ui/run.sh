#!/bin/bash
# CLIP Flask UI launcher.
# Honors $PORT (injected by Railway/Render); falls back to 8080.
# Called by docker-entrypoint.sh when CLIP_UI=flask.
set -e
PORT="${PORT:-8080}"
cd /app
exec python3 app/ui/server.py --port "$PORT" --host 0.0.0.0
