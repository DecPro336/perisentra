# Perisentra API / pipeline image (Python 3.12 + uv)
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    MLFLOW_DISABLE_AGENT_HINT=1 PERISENTRA_ROOT=/app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 build-essential && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra snowflake --no-install-project
COPY src ./src
COPY configs ./configs
COPY warehouse ./warehouse
RUN uv sync --frozen --no-dev --extra snowflake
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["perisentra", "serve", "--host", "0.0.0.0", "--port", "8000"]
