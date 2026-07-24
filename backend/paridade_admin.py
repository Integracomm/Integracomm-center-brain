# -*- coding: utf-8 -*-
"""Paridade do Painel Administrativo: ENDPOINT × tela HTML (caminho REAL).

O Admin é a tela de MAIOR risco da migração: ela controla permissão por área,
promoção a admin e link de redefinição de senha. Um erro aqui não mostra um
número torto — mostra dado a quem não deveria ver. Por isso a checagem central
é NOMINAL: usuário a usuário, as áreas e os sinalizadores do payload têm de ser
IDÊNTICOS aos de `list_users` (a mesma fonte que o HTML usa).

Guarda do refactor: `_teams_html` passou a consumir `_teams_dados`; aqui o HTML
que ele gera é comparado BYTE A BYTE com a versão anterior (git HEAD).

Rodar de dentro de backend/:  .venv/Scripts/python.exe paridade_admin.py
"""
import os
import re

import app.api as A
from app.auth import AREAS, list_users

ok = fail = 0


def check(nome, esperado, obtido):
    global ok, fail
    bate = esperado == obtido
    ok, fail = ok + bate, fail + (not bate)
    print(f"  [{'OK ' if bate else 'FALHA'}] {nome}")
    if not bate:
        print(f"          esperado (HTML): {esperado!r}")
        print(f"          obtido   (SPA) : {obtido!r}")


ADM = "adm@integracomm.com.br"

# ===========================================================================
# 1) _teams_html novo (consome _teams_dados) × antigo do git — byte a byte
# ===========================================================================
print("\n== Times por área · HTML novo × antigo do git")
SP = ("C:/Users/USUARIO/AppData/Local/Temp/claude/"
      "C--Users-USUARIO-Desktop-Nova-aplica--o-Integracomm/"
      "7f0d262c-bdee-4f90-a185-306738c72101/scratchpad/api_old.py")
if not os.path.exists(SP):
    print("  [SKIP] versão antiga não disponível — diff byte a byte pulado")
else:
    src = open(SP, encoding="utf-8").read()
    m = re.search(r"^def _teams_html\(conn\) -> str:.*?(?=^def )", src, re.S | re.M)
    if not m:
        print("  [SKIP] _teams_html não localizado na versão antiga")
    else:
        ns = dict(vars(A))  # reusa os globais atuais (_TEAM_AREAS, _PAPEL_LBL, escape, _hint)
        exec(compile(m.group(0), "api_old._teams_html", "exec"), ns)
        with A._conn() as c:
            velho = ns["_teams_html"](c)
            novo = A._teams_html(c)
        check("HTML de _teams_html idêntico ao anterior", velho, novo)

# ===========================================================================
# 2) PERMISSÕES — nominal, usuário a usuário (o que mais importa)
# ===========================================================================
print("\n== Contas e permissões · payload × list_users (nominal)")
with A._conn() as c:
    users_html = list_users(c)
    payload = A.admin_dados(c, ADM)

check("mesma quantidade de contas", len(users_html), len(payload["usuarios"]))

por_email = {u["email"]: u for u in payload["usuarios"]}
for u in users_html:
    e = u["email"]
    p = por_email.get(e)
    if p is None:
        check(f"{e}: presente no payload", True, False)
        continue
    check(f"{e}: ÁREAS idênticas",
          sorted(u.get("areas") or []), sorted(p["areas"]))
    check(f"{e}: status", u["status"], p["status"])
    check(f"{e}: is_admin", bool(u.get("is_admin")), p["is_admin"])
    check(f"{e}: id", str(u["id"]), p["id"])

# ninguém se auto-rebaixa: a flag `eu` marca SÓ a conta da sessão
eus = [p["email"] for p in payload["usuarios"] if p["eu"]]
check("flag 'eu' marca exatamente a conta da sessão", [ADM] if ADM in por_email else [], eus)

# as colunas de área do payload são as MESMAS do RBAC
check("mapa de áreas = AREAS do auth.py", dict(AREAS), payload["areas"])

# ===========================================================================
# 3) Demais blocos vêm das mesmas fontes
# ===========================================================================
print("\n== Blocos restantes · mesma fonte do HTML")
with A._conn() as c:
    acessos = A._admin_acessos(c)
    integ = A._integracoes_status(c)
    times = A._teams_dados(c)
    from app.llm_budget import month_summary
    llm = month_summary(c)

# acessos: views/last_seen do payload batem com o audit_log
for p in payload["usuarios"][:8]:
    n, _ult = acessos.get(p["email"], (0, None))
    check(f"{p['email']}: nº de acessos", n, p["views"])

fontes_html = [r for r in integ if r["fonte"] != "_cobertura"]
check("integrações: mesma qtde de fontes", len(fontes_html), len(payload["integracoes"]["fontes"]))
check("integrações: mesmos nomes",
      [r["fonte"] for r in fontes_html],
      [f["fonte"] for f in payload["integracoes"]["fontes"]])
check("integrações: mesmos status",
      [r["status"] for r in fontes_html],
      [f["status"] for f in payload["integracoes"]["fontes"]])

check("times: mesmas áreas", [t["area"] for t in times],
      [t["area"] for t in payload["times"]])
check("times: mesmos membros por área",
      [[m["nome"] for m in t["membros"]] for t in times],
      [[m["nome"] for m in t["membros"]] for t in payload["times"]])
# desligado NÃO aparece na tela (mas segue na régua histórica)
from app.team_config import eh_desligado
with A._conn() as c:
    for t in payload["times"]:
        for m in t["membros"]:
            if eh_desligado(c, t["area"], m["nome"]):
                check(f"{m['nome']}: desligado não deveria aparecer", False, True)

if llm:
    check("IA: gasto do mês", round(llm["spent_usd"], 4), round(payload["llm"]["spent_usd"], 4))
    check("IA: teto", round(llm["cap_usd"], 4), round(payload["llm"]["cap_usd"], 4))

# ===========================================================================
# 4) O endpoint é fechado a não-admin
# ===========================================================================
print("\n== Trava de acesso")
import inspect
fonte = inspect.getsource(A.api_admin_painel)
check("endpoint /api/admin/painel exige admin", True,
      'role != "admin"' in fonte and "403" in fonte)
fonte_pg = inspect.getsource(A.admin_panel)
check("rota /admin redireciona não-admin", True, 'role != "admin"' in fonte_pg)
check("rota /admin faz o chaveamento do SPA", True, "view_response" in fonte_pg)

print(f"\n=========== ADMIN · PARIDADE: {ok} OK · {fail} FALHA(S) ===========")
