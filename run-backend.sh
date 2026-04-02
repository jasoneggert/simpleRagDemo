#!/usr/bin/env bash

set -euo pipefail

exec ./.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 "$@"
