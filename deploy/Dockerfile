# Painel Integracomm IA — imagem do app (FastAPI + scripts do agente).
# Build a partir da RAIZ do projeto:  docker build -f deploy/Dockerfile .

# --- frontend: dist PRÉ-BUILDADO, NUNCA buildado aqui ----------------------
# INCIDENTE 22/07: o estágio `oven/bun` buildava o SPA DENTRO da instância no
# deploy. O build do Docker NÃO respeita mem_limit (esse só vale p/ o container
# em execução), então o bun+vite ficou sem teto, consumiu a RAM do Lightsail e
# derrubou o host inteiro — SSH parou no banner exchange, site fora do ar.
# Regra desde então: o `dist` é buildado na máquina do Otávio (já é, para a
# validação local) e VIAJA no pacote de deploy (deploy.ps1 gera e envia
# frontend/dist separado, pois dist/ é gitignored). Aqui só copiamos.
# Se o dist não vier, o build falha ALTO na linha do COPY — melhor que OOM.

# --- app Python ------------------------------------------------------------
FROM python:3.13-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 TZ=America/Sao_Paulo

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
# dist pré-buildado (enviado pelo deploy.ps1) — ver bloco no topo do arquivo
COPY frontend/dist frontend/dist
COPY deploy/daily_run.sh deploy/daily_run.sh

EXPOSE 8000
# --proxy-headers: o Caddy termina o TLS; o app enxerga https via X-Forwarded-Proto
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
