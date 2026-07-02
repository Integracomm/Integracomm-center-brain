"""Entrada da aplicação web — rodar a partir da RAIZ do projeto:

    backend\\.venv\\Scripts\\python -m uvicorn backend.main:app --port 8000

Abre em http://localhost:8000 → /login (admin | gestor_growth; senhas no .env
da raiz, geradas automaticamente no 1º boot). O pacote `app/` usa imports
relativos a backend/, então garantimos backend/ no sys.path independentemente
do diretório de onde o uvicorn foi chamado.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.api import app  # noqa: E402,F401
from app.auth import ensure_auth  # noqa: E402

ensure_auth()  # gera/garante credenciais no .env já no boot (não imprime nada)
