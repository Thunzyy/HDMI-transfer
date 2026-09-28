# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.9.24 AS uv
FROM python:3.11-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# OpenCV's Linux wheel needs these shared libraries even without a desktop.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

FROM base AS builder
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --python /usr/local/bin/python --no-install-project \
    --extra web --extra receiver --extra docker
COPY src ./src
COPY sender.html ./
COPY docker ./docker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --python /usr/local/bin/python \
    --extra web --extra receiver --extra docker

# Keep build tools and dependency-download caches out of the runtime image.
FROM base AS runtime
RUN useradd --uid 10001 --create-home hdmi \
    && mkdir -p /app/received_files \
    && chown hdmi:hdmi /app/received_files
COPY --from=builder --chown=hdmi:hdmi /app /app
USER hdmi
EXPOSE 5000
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/receive/status', timeout=3).read()"]
CMD ["python", "docker/serve.py"]
