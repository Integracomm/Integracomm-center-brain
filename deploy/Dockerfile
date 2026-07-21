# Painel Integracomm IA — imagem do app (FastAPI + scripts do agente).
# Build a partir da RAIZ do projeto:  docker build -f deploy/Dockerfile .

# --- estágio 1: build do frontend React (Lote 0 do redesenho, 21/07) -------
# bun (mesmo runtime usado localmente); se frontend/ não mudou, o cache do
# Docker pula tudo isto. O dist/ vai para a imagem final; app/spa.py serve.
FROM oven/bun:1.3-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/bun.lock* ./
RUN bun install --frozen-lockfile || bun install
COPY frontend/ .
RUN bun run build

# --- estágio 2: app Python -------------------------------------------------
FROM python:3.13-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 TZ=America/Sao_Paulo

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
COPY --from=frontend /fe/dist frontend/dist
COPY deploy/daily_run.sh deploy/daily_run.sh

EXPOSE 8000
# --proxy-headers: o Caddy termina o TLS; o app enxerga https via X-Forwarded-Proto
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
