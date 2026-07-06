# Painel Integracomm IA — imagem do app (FastAPI + scripts do agente).
# Build a partir da RAIZ do projeto:  docker build -f deploy/Dockerfile .
FROM python:3.13-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 TZ=America/Sao_Paulo

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
COPY deploy/daily_run.sh deploy/daily_run.sh

EXPOSE 8000
# --proxy-headers: o Caddy termina o TLS; o app enxerga https via X-Forwarded-Proto
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
