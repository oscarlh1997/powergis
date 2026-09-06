# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# Etapa 1 · dependencias
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install '.[pdf,geo,observability]'

# ---------------------------------------------------------------------------
# Etapa 2 · runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    TZ=Europe/Madrid

# Solo las librerías de sistema que WeasyPrint necesita en ejecución.
# Nada de compiladores en la imagen final.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
        libffi8 shared-mime-info fonts-dejavu-core \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios: un worker que ejecuta código de terceros no corre como root.
RUN useradd --create-home --uid 10001 powergis

COPY --from=builder /opt/venv /opt/venv
COPY --chown=powergis:powergis src /app/src
COPY --chown=powergis:powergis alembic /app/alembic
COPY --chown=powergis:powergis alembic.ini /app/alembic.ini
COPY --chown=powergis:powergis tools /app/tools

WORKDIR /app
ENV PYTHONPATH=/app/src

RUN mkdir -p /data/tiles /data/exports /data/osm && chown -R powergis:powergis /data
USER powergis

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "powergis.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
