FROM python:3.13.5-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

FROM python:3.13.5-slim
WORKDIR /app

RUN apt-get update && apt-get install -y libmagic1 ffmpeg && rm -rf /var/lib/apt/lists/*

COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH"
CMD ["gunicorn", "--workers", "2", "--threads", "4", "--worker-class", "gthread", "--bind", "0.0.0.0:80", "wsgi"]
