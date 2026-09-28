#!/usr/bin/env sh
set -eu
if ! command -v uv >/dev/null 2>&1; then
  echo 'uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/' >&2
  exit 1
fi
cd "$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
uv sync --locked --extra web
exec uv run --no-sync hdmi-web "$@"
