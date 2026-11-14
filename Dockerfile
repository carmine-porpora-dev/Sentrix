# ---------------------------------------------------------------------------------------------
# 1. Interfaccia: npm ci && npm run build -> frontend/dist
# ---------------------------------------------------------------------------------------------
FROM node:22.23-slim AS frontend
WORKDIR /build

# Prima le dipendenze: questo strato resta in cache finché package-lock.json non cambia.
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci

# La build legge i font del designer (design/design-system/fonts, via src/styles/fonts.css).
COPY frontend/ frontend/
COPY design/design-system/ design/design-system/
RUN cd frontend && npm run build

# ---------------------------------------------------------------------------------------------
# 2. Backend + interfaccia compilata. Stessa alberatura del repository (/app/backend, /app/config,
#    ...): i percorsi del codice (config/, seeds/, demo_cache/, frontend/dist) sono relativi a /app.
# ---------------------------------------------------------------------------------------------
FROM python:3.12-slim-trixie AS runtime

# uv a versione fissata (la stessa del lockfile in uso).
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/backend/.venv/bin:$PATH" \
    DATA_DIR=/data

WORKDIR /app/backend

# Dipendenze di produzione, esattamente quelle di uv.lock (--frozen: il lock non si tocca).
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/app app
COPY backend/scripts scripts
COPY config /app/config
COPY seeds /app/seeds
COPY demo_cache /app/demo_cache
COPY --from=frontend /build/frontend/dist /app/frontend/dist

# Utente non root con UID/GID fissi: i permessi di /data (volume sulla VM) sono prevedibili e
# deploy/deploy.sh li imposta per lo stesso 10001.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir /data \
    && chown app:app /data
USER 10001:10001

EXPOSE 8000
# Un solo processo: cache LIVE, limiti e run in corso stanno in memoria (spech 4.1).
CMD ["sh", "scripts/start.sh"]
