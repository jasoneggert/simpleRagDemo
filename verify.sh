#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_CHROMA_DIR="${TMPDIR:-/tmp}/doccopilot-verify-chroma"
TMP_DB_PATH="${TMPDIR:-/tmp}/doccopilot-verify.sqlite3"

cd "$ROOT_DIR"

rm -rf "$TMP_CHROMA_DIR"
rm -f "$TMP_DB_PATH"

echo "[1/3] Python compile"
./.venv/bin/python -m py_compile backend/app/*.py backend/scripts/*.py

echo "[2/3] Frontend build"
npm --prefix frontend run build

echo "[3/3] Demo regression suite"
DEMO_MODE=true \
CHROMA_DIR="$TMP_CHROMA_DIR" \
SUPPORT_DB_PATH="$TMP_DB_PATH" \
PYTHONPATH=backend \
./.venv/bin/python backend/scripts/regression_billing_support.py

echo "Verification passed."
