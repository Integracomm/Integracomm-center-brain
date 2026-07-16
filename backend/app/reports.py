"""Relatório mensal de assessoria por cliente — composição e persistência.

Junta as 3 fontes num objeto único e AUDITÁVEL, salvo em `reports` (JSONB):
  1. Faturamento — planilha individual do cliente (link na mestre de NPS);
  2. Atividades — subtarefas concluídas no período (ClickUp API → mirror);
  3. Saúde — score/faixa/trajetória + sinais do Postgres próprio (agente Growth).

"Observações e próximos passos": por enquanto TEMPLATES determinísticos sobre
os dados (sem chamada de LLM — créditos de API indisponíveis); quando liberados,
esta seção passa a ser gerada via Claude mantendo o mesmo contrato de dados.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any

from .agents.growth.scoring import action_guideline
from .sources import clickup_activities as CU
from .sources import nps_sheets as NPS
from .sources import squads_sheet as SQ

_STAGE_LABEL = {"saudavel": "saudável", "desengajamento_inicial": "desengajamento inicial",
                "insatisfacao_latente": "insatisfação latente", "insatisfacao_ativa": "insatisfação ativa",
                "intencao_de_saida": "intenção de saída", "nao_avaliavel": "não avaliável"}
_TRAJ_LABEL = {"subindo": "melhorando", "estavel": "estável", "caindo": "piorando",
               "desconhecida": "desconhecida"}

_MONTH_NAMES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
                "agosto", "setembro", "outubro", "novembro", "dezembro"]

_REPORTS_DDL = """
CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id TEXT NOT NULL,
    account_name TEXT NOT NULL,
    reference_month DATE NOT NULL,
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    generated_by TEXT,
    status TEXT DEFAULT 'generated',
    data JSONB NOT NULL,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_account ON reports(account_id, reference_month DESC);

-- Atualizações de caso escritas pelo GESTOR (ex.: "reunião feita, contornei o
-- cancelamento propondo X"). Alimentam o plano de ação da conta e podem estar
-- ligadas a um alerta específico (aba Alertas).
CREATE TABLE IF NOT EXISTS case_updates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    alert_id UUID REFERENCES alerts(id) ON DELETE SET NULL,
    author TEXT,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_case_updates_acct ON case_updates(account_id, created_at DESC);
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS notes TEXT;
"""


def list_case_updates(conn: Any, account_id: str, limit: int = 20) -> list[dict]:
    ensure_reports_table(conn)
    with conn.cursor() as cur:
        cur.execute("""SELECT id, author, text, created_at, alert_id FROM case_updates
                        WHERE account_id=%s ORDER BY created_at DESC LIMIT %s""",
                    (account_id, limit))
        return [{"id": str(i), "author": a, "text": t,
                 "created_at": c.isoformat(), "alert_id": (str(al) if al else None)}
                for i, a, t, c, al in cur.fetchall()]


def add_case_update(conn: Any, account_id: str, author: str | None, text: str,
                    alert_id: str | None = None) -> None:
    ensure_reports_table(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO case_updates (account_id, alert_id, author, text) VALUES (%s,%s,%s,%s)",
                    (account_id, alert_id, author, text))


def add_case_update_once(conn: Any, account_id: str, author: str | None, text: str) -> bool:
    """Grava a atualização SÓ se o texto exato ainda não existe para a conta —
    eventos automáticos (linha do tempo do agente) rodam todo dia e o texto
    determinístico (com a data do evento) é a chave de dedup."""
    ensure_reports_table(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM case_updates WHERE account_id=%s AND text=%s LIMIT 1",
                    (account_id, text))
        if cur.fetchone():
            return False
        cur.execute("INSERT INTO case_updates (account_id, author, text) VALUES (%s,%s,%s)",
                    (account_id, author, text))
        return True


def _case_history(conn: Any, account_id: str, updates: list[dict]) -> list[dict]:
    """Histórico de interações do caso, cronológico (antigo → recente): eventos
    automáticos do agente + notas dos gestores (case_updates) + AÇÕES registradas
    com desfecho (interventions). Insumo de reunião — sai na impressão."""
    eventos = [{"quando": u["created_at"], "autor": u["author"] or "—",
                "texto": u["text"], "resultado": None} for u in updates]
    with conn.cursor() as cur:
        cur.execute("""SELECT taken_at, taken_by, action_text, result FROM interventions
                        WHERE account_id=%s ORDER BY taken_at""", (account_id,))
        eventos += [{"quando": t.isoformat(), "autor": (por or "gestor"),
                     "texto": f"Ação registrada: {txt}",
                     "resultado": (res if res and res != "pendente" else None)}
                    for t, por, txt, res in cur.fetchall()]
    return sorted(eventos, key=lambda e: e["quando"])


def ensure_reports_table(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(_REPORTS_DDL)


def month_label(iso: str) -> str:
    y, m = iso.split("-")
    return f"{_MONTH_NAMES[int(m) - 1]}/{y}"


def default_ref_month(today: dt.date | None = None) -> str:
    d = (today or dt.date.today()).replace(day=1) - dt.timedelta(days=1)
    return d.strftime("%Y-%m")


def _month_bounds(ref: str) -> tuple[dt.datetime, dt.datetime, str]:
    """(início, fim-exclusivo, mês-anterior 'YYYY-MM') do mês de referência."""
    y, m = int(ref[:4]), int(ref[5:7])
    start = dt.datetime(y, m, 1, tzinfo=dt.timezone.utc)
    end = dt.datetime(y + (m == 12), (m % 12) + 1, 1, tzinfo=dt.timezone.utc)
    prev = start - dt.timedelta(days=1)
    return start, end, prev.strftime("%Y-%m")


def _account_row(conn: Any, account_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT a.id, a.name, a.plan_category, a.manager_name, a.is_legacy,
                      a.recurring_revenue,
                      s.score, s.risk_band, s.stage, s.trajectory, s.evaluable,
                      s.confidence, s.computed_at, s.id AS score_id
                 FROM accounts a
            LEFT JOIN LATERAL (SELECT * FROM scores s WHERE s.account_id = a.id
                               ORDER BY s.computed_at DESC LIMIT 1) s ON TRUE
                WHERE a.id = %s""", (account_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        acc = dict(zip(cols, row))
        acc["reasons"] = []
        if acc.get("score_id"):
            cur.execute("SELECT text, is_leading, weight FROM score_reasons "
                        "WHERE score_id=%s ORDER BY weight DESC", (acc["score_id"],))
            acc["reasons"] = [{"text": t, "leading": l, "weight": float(w)}
                              for t, l, w in cur.fetchall()]
        return acc


def _signals(conn: Any, account_id: str, start: dt.datetime, end: dt.datetime) -> dict:
    """Sinais p/ a seção de saúde: preferimos os capturados DENTRO do mês; se não
    houver (a série começou depois), caímos para o mais recente, sinalizando."""
    keys = ("tom_negativo", "fala_em_cancelar", "critico_recente", "exec_score")
    out: dict[str, dict] = {}
    with conn.cursor() as cur:
        for key in keys:
            cur.execute(
                """SELECT value_num, value_text, captured_at FROM signal_snapshots
                    WHERE account_id=%s AND signal_key=%s AND captured_at >= %s AND captured_at < %s
                    ORDER BY captured_at DESC LIMIT 1""", (account_id, key, start, end))
            row = cur.fetchone()
            in_month = row is not None
            if not row:
                cur.execute(
                    """SELECT value_num, value_text, captured_at FROM signal_snapshots
                        WHERE account_id=%s AND signal_key=%s
                        ORDER BY captured_at DESC LIMIT 1""", (account_id, key))
                row = cur.fetchone()
            if row:
                out[key] = {"value": (float(row[0]) if row[0] is not None else None),
                            "text": row[1], "captured_at": row[2].date().isoformat(),
                            "in_month": in_month}
    return out


def _tone_label(sig: dict) -> tuple[str, str]:
    """(rótulo, detalhe) do tom predominante a partir dos sinais derivados."""
    if sig.get("fala_em_cancelar"):
        return "crítico", "houve menção a cancelamento no período analisado"
    if sig.get("critico_recente"):
        return "negativo", "evento crítico recente nas conversas"
    tom = sig.get("tom_negativo", {}).get("value")
    if tom is None:
        return "sem dados", "sem sinal de tom no período"
    pct = tom * 100 if tom <= 1 else tom  # tolera escala 0-1 ou 0-100
    if pct >= 50:
        return "negativo", f"{pct:.0f}% dos dias de conversa com tom negativo"
    if pct >= 20:
        return "atenção", f"{pct:.0f}% dos dias de conversa com tom negativo"
    return "estável", f"apenas {pct:.0f}% dos dias de conversa com tom negativo"


def _observacoes(acc: dict, fat: dict, atv: dict, tone: tuple[str, str], ref: str) -> dict:
    """Seção 'Observações e próximos passos' — determinística (ver docstring)."""
    partes: list[str] = []
    sug: list[str] = []
    nome_mes = month_label(ref)

    if acc.get("evaluable") and acc.get("score") is not None:
        partes.append(
            f"A conta encerrou {nome_mes} com score de relacionamento "
            f"{float(acc['score']):.1f}/100 (faixa {acc['risk_band']}, "
            f"{_STAGE_LABEL.get(acc['stage'], acc['stage'])}), com trajetória "
            f"{_TRAJ_LABEL.get(acc['trajectory'], acc['trajectory'])}.")
    else:
        partes.append(f"A conta não tinha dados de conversa suficientes para score em {nome_mes} "
                      "— vale revisão manual do relacionamento.")

    totals = fat.get("comparativo") or []
    t_ref = sum(b["total_ref"] for b in totals)
    t_prev = sum(b["total_prev"] for b in totals)
    ref_lancado = any(b.get("ref_lancado") for b in totals)
    if fat.get("available") and totals:
        if not ref_lancado:
            partes.append(f"O faturamento de {nome_mes} ainda não estava lançado na planilha "
                          "na data de geração (a planilha é atualizada todo dia 1º) — "
                          "regerar o relatório após a atualização.")
        elif t_prev > 0:
            var = (t_ref - t_prev) / t_prev * 100
            direcao = "cresceu" if var >= 0 else "caiu"
            partes.append(f"O faturamento nos marketplaces {direcao} {abs(var):.1f}% vs o mês anterior "
                          f"(R$ {t_ref:,.0f} vs R$ {t_prev:,.0f}).".replace(",", "."))
            if var <= -20:
                sug.append("Faturamento caiu mais de 20% no mês — investigar causa com o cliente "
                           "(estoque, reputação da conta, sazonalidade) e alinhar plano de recuperação.")
        else:
            partes.append(f"Faturamento registrado no mês: R$ {t_ref:,.0f} (sem base comparável no mês anterior).".replace(",", "."))
    elif not fat.get("available"):
        if fat.get("conf"):
            partes.append("Cliente de Configuração de Sistema (plano antigo): sem acesso às plataformas "
                          "de marketplace do cliente — faturamento não acompanhado (esperado, não é pendência).")
        else:
            partes.append("Sem planilha de faturamento disponível para esta conta no período.")
            sug.append("Regularizar a planilha de NPS/faturamento do cliente (link ausente ou acesso restrito na mestre).")

    # total_mes = régua mensal (a lista atv.tasks é o HISTÓRICO completo desde 15/07)
    n_atv = atv.get("total_mes", len(atv.get("tasks") or []))
    if n_atv:
        partes.append(f"Foram concluídas {n_atv} atividades de assessoria no período.")
    else:
        partes.append("Nenhuma atividade concluída registrada no período.")
        sug.append("Sem entregas concluídas no mês — revisar o plano de ação no ClickUp e "
                   "comunicar o andamento ao cliente.")

    tone_lbl, tone_det = tone
    if tone_lbl in ("crítico", "negativo"):
        partes.append(f"O tom das conversas está {tone_lbl} ({tone_det}).")
        sug.append("Tom de conversa deteriorado — priorizar contato pessoal do GC nesta semana.")

    guia = action_guideline(
        acc.get("stage") or "nao_avaliavel", is_legacy=bool(acc.get("is_legacy")),
        recurring_revenue=(float(acc["recurring_revenue"]) if acc.get("recurring_revenue") is not None else None),
        evaluable=bool(acc.get("evaluable")),
        reasons=acc.get("reasons"), exec_score=(acc.get("exec_score")),
    )
    if guia:
        sug.append(guia)

    return {"texto": " ".join(partes), "sugestoes": sug,
            "gerado_por": "template determinístico (LLM entra quando os créditos de API forem liberados)"}


def build_report(conn: Any, account_id: str, ref_month: str, generated_by: str | None) -> dict:
    """Gera o relatório completo de UMA conta para o mês de referência e salva
    em `reports`. Retorna o payload (com `report_id`)."""
    acc = _account_row(conn, account_id)
    if not acc:
        raise LookupError(f"conta {account_id} não encontrada")
    if acc.get("recurring_revenue") is not None:
        acc["recurring_revenue"] = float(acc["recurring_revenue"])
    start, end, prev_month = _month_bounds(ref_month)

    # --- faturamento (planilha individual via mestre) ---
    # clientes [CONF-...] = Configuração de Sistema (plano antigo): SEM acesso
    # às plataformas do cliente -> nunca estarão na planilha de NPS (Otávio
    # 15/07, caso WMA) — o aviso explica em vez de cobrar regularização
    import re as _re
    is_conf = bool(_re.match(r"^\s*\[CONF", acc["name"] or "", _re.I))
    fat: dict[str, Any] = {"available": False, "aviso": None, "comparativo": [],
                           "match_note": None, "sheet_link": None, "months_meta": None,
                           "conf": is_conf}
    master, match_note = NPS.find_master_row(acc["name"])
    fat["match_note"] = match_note
    sheet_info: dict = {}
    if master is None and is_conf:
        fat["aviso"] = ("Cliente de Configuração de Sistema (plano antigo) — sem acesso às plataformas "
                        "de marketplace do cliente; não consta na planilha de NPS/faturamento (esperado).")
    elif master is None:
        fat["aviso"] = "Planilha não disponível — conta não encontrada na planilha mestre de NPS."
    elif not master["sheet_id"]:
        fat["aviso"] = (f"Planilha não disponível — na mestre consta: “{master['link_raw'] or 'sem link'}”.")
    else:
        fat["sheet_link"] = master["link_raw"]
        try:
            parsed = NPS.fetch_individual(master["sheet_id"], master["gid"])
            sheet_info = parsed.get("info") or {}
            # guarda: a mestre pode linkar a planilha de OUTRO cliente — se o
            # nome declarado na individual divergir da conta, não confiar nos
            # dados de cabeçalho dela e sinalizar o link p/ correção
            sheet_cli = NPS.norm_account(sheet_info.get("cliente"))
            if sheet_cli and sheet_cli != NPS.norm_account(acc["name"]):
                fat["aviso"] = (f"Atenção: a planilha linkada na mestre declara outro cliente "
                                f"(“{sheet_info.get('cliente')}”) — o faturamento abaixo pode não ser "
                                f"desta conta; verificar o link na coluna C da mestre.")
                fat["match_note"] = ((fat["match_note"] or "") + " ⚠ planilha declara outro cliente").strip()
                sheet_info = {}
            fat["comparativo"] = NPS.faturamento_compare(parsed, ref_month, prev_month)
            fat["available"] = True
            fat["months_meta"] = parsed.get("base_year_source")
            # não sobrescrever o aviso de link errado (mais grave que falta de lançamento)
            if not fat["comparativo"] and not fat["aviso"]:
                fat["aviso"] = f"Planilha encontrada, mas sem faturamento lançado em {month_label(ref_month)}."
            elif fat["comparativo"] and not any(b.get("ref_lancado") for b in fat["comparativo"]) and not fat["aviso"]:
                fat["aviso"] = (f"Faturamento de {month_label(ref_month)} ainda não lançado na planilha "
                                "(atualizada todo dia 1º) — valores exibidos são do mês anterior.")
        except Exception as e:  # noqa: BLE001 — planilha privada/fora do ar não derruba o relatório
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (401, 403):
                fat["aviso"] = ("Planilha não disponível — acesso restrito. Pedir ao dono para "
                                "compartilhar como “qualquer pessoa com o link: leitor” e regerar o relatório.")
            else:
                fat["aviso"] = f"Planilha não disponível — acesso falhou ({type(e).__name__})."

    # --- atividades (ClickUp API -> fallback mirror) ---
    # HISTÓRICO COMPLETO no relatório (Otávio 15/07: visão inteira antes da
    # reunião), agrupado por MÊS do mais recente ao mais antigo; a contagem do
    # MÊS de referência segue separada (régua do plano de ação/observações).
    agora = dt.datetime.now(dt.timezone.utc)
    atv = CU.completed_activities(acc["name"], dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc), agora)
    atv["tasks"].sort(key=lambda t: t["concluida_em"], reverse=True)
    total_mes = sum(1 for t in atv["tasks"]
                    if start.date().isoformat() <= t["concluida_em"] < end.date().isoformat())
    atv["total_mes"] = total_mes  # régua mensal p/ observações/plano
    grupos: dict[str, list] = {}
    for t in atv["tasks"]:
        chave = month_label(t["concluida_em"][:7])
        grupos.setdefault(chave, []).append(t)  # meses na ordem de chegada (desc)
    atv["grupos"] = [{"categoria": k, "tarefas": v} for k, v in grupos.items()]
    # próximas previstas: sempre relativas a HOJE (insumo p/ a reunião do GC),
    # independente do mês de referência do relatório
    proximas = CU.upcoming_activities(acc["name"])
    # em ATRASO: abertas com vencimento vencido — a fila de cobrança do gestor
    # (tarefa vencida não é 'próxima' nem 'concluída' e ficava invisível)
    atrasadas = CU.overdue_activities(acc["name"])
    atv["atrasadas"] = atrasadas
    clickup_url = CU.card_url(acc["name"])

    # --- saúde do relacionamento ---
    sig = _signals(conn, str(acc["id"]), start, end)
    acc["exec_score"] = sig.get("exec_score", {}).get("value")
    tone = _tone_label(sig)
    saude = {
        "score": (float(acc["score"]) if acc.get("score") is not None else None),
        "faixa": acc.get("risk_band"), "estagio": _STAGE_LABEL.get(acc.get("stage"), acc.get("stage")),
        "trajetoria": _TRAJ_LABEL.get(acc.get("trajectory"), acc.get("trajectory")),
        "evaluable": bool(acc.get("evaluable")),
        "motivos": [r["text"] for r in acc.get("reasons", [])[:5]],
        "tom": {"rotulo": tone[0], "detalhe": tone[1]},
        "exec_score": acc["exec_score"],
        # motivo da nota de execução (ex.: 'Implantação crítica: 11 meses desde a
        # venda') — sem ele, 'atrasada' sem tarefa vencida parecia inconsistente
        # (caso DNEZA 15/07)
        "exec_motivo": sig.get("exec_score", {}).get("text"),
        "sinais_do_mes": all(v.get("in_month") for v in sig.values()) if sig else False,
        "score_computado_em": (acc["computed_at"].date().isoformat() if acc.get("computed_at") else None),
    }

    # --- equipe do squad (planilha de composição dos SQUADs); contas sem
    # Bx-Sy no tag (ex.: [ADS-GU]) usam a equipe do mirror como fallback ---
    mirror_info = CU.mirror_client_info(acc["name"]) or {}
    equipe_squad = None
    squad_gc = None
    try:
        hit = SQ.team_for_account(acc["name"], fallback_key=mirror_info.get("equipe"))
        if hit:
            equipe_squad = {"squad": hit[0], "membros": hit[1]}
            squad_gc = SQ.gc_of_team(hit[1])
    except Exception:  # noqa: BLE001 — planilha de squads fora do ar não derruba o relatório
        pass

    # --- cabeçalho (planilha > mirror > squad > banco, nesta ordem) ---
    header = {
        "account_id": str(acc["id"]), "account_name": acc["name"],
        "cliente": (sheet_info.get("cliente") or acc["name"]),
        "plano": sheet_info.get("plano") or mirror_info.get("contrato") or acc.get("plan_category"),
        "gc": (sheet_info.get("gc") or mirror_info.get("gerente_de_contas")
               or squad_gc or acc.get("manager_name")),
        "equipe": (sheet_info.get("equipe") or mirror_info.get("equipe")
                   or (equipe_squad and equipe_squad["squad"])),
        "reference_month": ref_month, "reference_month_label": month_label(ref_month),
        "prev_month": prev_month, "prev_month_label": month_label(prev_month),
        "clickup_url": clickup_url,
    }

    data = {"header": header, "equipe_squad": equipe_squad, "faturamento": fat,
            "atividades": {"source": atv["source"], "aviso": atv["aviso"],
                           "total": total_mes, "total_hist": len(atv["tasks"]),
                           "grupos": atv["grupos"],
                           "atrasadas": {"source": atrasadas["source"], "aviso": atrasadas["aviso"],
                                         "tasks": atrasadas["tasks"]},
                           "proximas": {"source": proximas["source"], "aviso": proximas["aviso"],
                                        "tasks": proximas["tasks"],
                                        "geradas_em": dt.date.today().isoformat()}},
            "saude": saude,
            "observacoes": _observacoes(acc, fat, atv, tone, ref_month)}

    # --- plano de ação individual (gestor de CS sênior) + histórico do caso ---
    from .agents.growth.action_plan import generate_plan
    updates = list_case_updates(conn, str(acc["id"]), limit=50)
    data["case_updates"] = updates
    data["historico"] = _case_history(conn, str(acc["id"]), updates)
    data["plano_acao"] = generate_plan(data, updates, acc)

    # --- persiste ---
    ensure_reports_table(conn)
    rid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO reports (id, account_id, account_name, reference_month, generated_by, data)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (rid, str(acc["id"]), acc["name"], f"{ref_month}-01", generated_by, json.dumps(data)))
    data["report_id"] = rid
    data["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    data["generated_by"] = generated_by
    return data


def load_report(conn: Any, report_id: str) -> dict | None:
    ensure_reports_table(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT data, generated_at, generated_by, notes FROM reports WHERE id=%s",
                    (report_id,))
        row = cur.fetchone()
    if not row:
        return None
    data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    data["report_id"] = report_id
    data["generated_at"] = row[1].isoformat() if row[1] else None
    data["generated_by"] = row[2]
    data["notes"] = row[3]
    return data
