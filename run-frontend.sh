#!/usr/bin/env bash

set -euo pipefail

cd frontend
exec npm run dev -- --host 127.0.0.1 "$@"
