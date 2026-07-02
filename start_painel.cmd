@echo off
rem Sobe o painel Integracomm IA (usado pela tarefa agendada IntegracommIA-Painel).
rem Ativa o venv e roda o uvicorn da RAIZ do projeto; log em logs\painel.log.
cd /d "%~dp0"
if not exist logs mkdir logs
call backend\.venv\Scripts\activate.bat
python -m uvicorn backend.main:app --port 8000 >> logs\painel.log 2>&1
