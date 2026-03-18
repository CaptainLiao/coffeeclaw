# =========== Base Stage ===========
FROM python:3.11-slim AS base

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    PYTHONPATH=/app

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# =========== Dev Stage ===========
FROM base AS dev

RUN uv sync --frozen --no-install-project --extra dev

COPY alembic.ini ./
COPY configs/ ./configs/
COPY migrations/ ./migrations/
COPY src/ ./src/

ENV WATCHFILES_FORCE_POLLING=true

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# =========== Prod Stage ===========
FROM base AS prod

COPY alembic.ini ./
COPY configs/ ./configs/
COPY migrations/ ./migrations/
COPY src/ ./src/

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
