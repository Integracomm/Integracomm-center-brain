"""Plano de ação INDIVIDUAL por conta — persona de gestor de CS sênior (B2B).

Gera o "norte para a reunião" do GC a partir de TODOS os dados do relatório
(score/estágio/motivos, tom, execução, faturamento, atividades feitas e
previstas, equipe do squad) + o HISTÓRICO DE ATUALIZAÇÕES escrito pelo gestor
(case_updates) — cada atualização registrada muda o plano na próxima geração.

Dois motores:
  1. Claude (claude-sonnet-5) quando houver créditos de API — qualidade alvo;
  2. fallback DETERMINÍSTICO estruturado (sem LLM) — mesmo contrato, hoje ativo
     (créditos indisponíveis). O relatório declara qual motor gerou.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from ...config import get_settings
from .scoring import action_guideline

_SYSTEM = """Você é um gestor de Customer Success SÊNIOR, especialista em clientes B2B
de assessoria de marketplaces (Mercado Livre, Shopee, Amazon). Você recebe o dossiê de UM
cliente e escreve o plano de ação que VOCÊ executaria para reter/expandir a conta — direto,
específico e acionável, servindo de norte para o gestor da conta antes da reunião.

Regras: use SOMENTE os dados do dossiê (não invente números nem fatos); incorpore as
atualizações do gestor (são o estado mais recente do caso); escreva em pt-BR; formato
markdown EXATO com estas seções:
### Diagnóstico
### Objetivo da próxima reunião
### Plano de ação (próximas 2 semanas)
### Condução da reunião
### Riscos e sinais para acompanhar
Máx. ~350 palavras. Numere as ações. Seja específico (cite marketplaces, valores e nomes
do dossiê quando relevantes)."""


def _dossie(data: dict, updates: list[dict]) -> str:
    """Dossiê em texto (mesmo insumo p/ Claude e p/ o determinístico)."""
    h, s, f, a = data["header"], data["saude"], data["faturamento"], data["atividades"]
    lines = [f"CLIENTE: {h['cliente']} | plano {h.get('plano') or '?'} | mês ref. {h['reference_month_label']}"]
    if data.get("equipe_squad"):
        eq = data["equipe_squad"]
        lines.append("EQUIPE (squad %s): %s" % (eq["squad"], ", ".join(f"{m['funcao']}: {m['nome']}" for m in eq["membros"])))
    lines.append(f"SAÚDE: score {s['score'] if s['score'] is not None else 's/dados'}/100, faixa {s['faixa']}, "
                 f"estágio {s['estagio']}, trajetória {s['trajetoria']}; tom {s['tom']['rotulo']} ({s['tom']['detalhe']})")
    if s.get("motivos"):
        lines.append("MOTIVOS DO SCORE: " + " | ".join(s["motivos"]))
    if s.get("exec_score") is not None:
        lines.append(f"EXECUÇÃO (ClickUp): {s['exec_score']:.0f}/100")
    if f.get("available") and f.get("comparativo"):
        for b in f["comparativo"]:
            lines.append(f"FATURAMENTO CNPJ {b.get('cnpj') or 'único'}: "
                         f"{h['prev_month_label']} R$ {b['total_prev']:,.0f} → {h['reference_month_label']} "
                         + (f"R$ {b['total_ref']:,.0f}" if b.get("ref_lancado") else "(não lançado)"))
    elif f.get("aviso"):
        lines.append(f"FATURAMENTO: {f['aviso']}")
    lines.append(f"ATIVIDADES CONCLUÍDAS NO MÊS: {a['total']}")
    px = (a.get("proximas") or {}).get("tasks") or []
    if px:
        lines.append("PRÓXIMAS PREVISTAS: " + "; ".join(f"{t['nome']} (vence {t['vence_em']})" for t in px[:6]))
    if updates:
        lines.append("ATUALIZAÇÕES DO GESTOR (mais recentes primeiro):")
        for u in updates[:6]:
            lines.append(f"  [{str(u['created_at'])[:10]} {u.get('author') or ''}] {u['text']}")
    return "\n".join(lines)


_MODEL = "claude-sonnet-5"


_PLAN_CACHE_DDL = """CREATE TABLE IF NOT EXISTS growth_plan_cache (
    account_id TEXT NOT NULL,
    ref_month  TEXT NOT NULL,
    texto      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, ref_month)
)"""


def _via_claude(dossie: str, cache_key: tuple[str, str] | None = None) -> str | None:
    # Só tenta o LLM quando explicitamente ligado (GROWTH_LLM_PLANS=1) E com
    # chave — evita pagar ~1s (e retries) numa chamada que hoje falha sem créditos.
    # Passa pelo guarda de orçamento mensal (llm_budget): teto atingido -> None
    # (o plano sai pelo motor determinístico, sem custo).
    # CACHE 20h por conta+mês (14/07: com créditos ativos, cada regeração do
    # relatório pagava ~10-25s de Claude — era a lentidão relatada; mesmo
    # padrão do tom, que pula contas analisadas <20h).
    s = get_settings()
    if not (s.growth_llm_plans and s.anthropic_api_key):
        return None
    try:
        import anthropic
        import psycopg

        from ...llm_budget import ensure_budget, record_usage
        with psycopg.connect(s.app_database_url) as bconn:
            if cache_key:
                with bconn.cursor() as cur:
                    cur.execute(_PLAN_CACHE_DDL)
                    cur.execute("""SELECT texto FROM growth_plan_cache
                                    WHERE account_id=%s AND ref_month=%s
                                      AND created_at > now() - interval '20 hours'""", cache_key)
                    hit = cur.fetchone()
                if hit:
                    return hit[0]
            ensure_budget(bconn)
            cli = anthropic.Anthropic(api_key=s.anthropic_api_key, max_retries=0, timeout=30.0)
            msg = cli.messages.create(
                model=_MODEL, max_tokens=1200,
                thinking={"type": "disabled"},  # volume/custo; sem isso vem ThinkingBlock antes do texto
                system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": dossie}],
            )
            tin = (msg.usage.input_tokens + (msg.usage.cache_read_input_tokens or 0)
                   + (msg.usage.cache_creation_input_tokens or 0))
            record_usage(bconn, "growth:plano_acao", _MODEL, tin, msg.usage.output_tokens)
            texto = next(b.text for b in msg.content if b.type == "text").strip()
            if cache_key and texto:
                with bconn.cursor() as cur:
                    cur.execute("""INSERT INTO growth_plan_cache (account_id, ref_month, texto)
                                   VALUES (%s, %s, %s)
                                   ON CONFLICT (account_id, ref_month) DO UPDATE
                                       SET texto=EXCLUDED.texto, created_at=now()""", (*cache_key, texto))
        return texto
    except Exception:  # noqa: BLE001 — sem créditos/rede/orçamento -> fallback determinístico
        return None


# --- fallback determinístico -------------------------------------------------
_DRIVER_ACOES = {
    "silencio": ("Reativar o canal: mensagem pessoal do GC hoje (não template), com um dado novo da conta "
                 "(ex.: oportunidade vista nos anúncios) que exija resposta.",
                 "Agendar call de 20 min esta semana — cliente em silêncio não reaparece sozinho."),
    "iniciativa_cliente": ("Inverter o fluxo: levar 2 propostas prontas de melhoria (não pedir demanda) — "
                           "cliente que parou de pedir precisa voltar a enxergar valor sem esforço.",
                           "Fechar a call com UM compromisso do cliente (aprovação, material, acesso) p/ medir reengajamento."),
    "tom_negativo": ("Não rebater ponto a ponto: abrir a conversa reconhecendo a insatisfação e pedindo os 2 "
                     "principais incômodos, por ordem.",
                     "Responder com plano datado por incômodo (o que, quem, quando) e enviar por escrito no grupo."),
    "comprimento_msg": ("Respostas encurtando = desengajamento: trocar mensagens longas por 1 pergunta objetiva "
                        "por vez e propor call curta.",),
    "fala_em_cancelar": ("URGENTE: contato do GC hoje, por telefone. Mapear o motivo real do cancelamento antes "
                         "de oferecer qualquer contrapartida.",
                         "Levar à call: resultados entregues (nº de atividades, evolução de faturamento) e opções "
                         "concretas (replanejamento, downgrade temporário) — decidir COM o cliente, não pelo cliente."),
    "critico_recente": ("Houve evento crítico recente: tratá-lo nominalmente na abertura da reunião e apresentar "
                        "a correção feita (ou plano com data).",),
}


def _plan_deterministico(data: dict, updates: list[dict], acc: dict) -> str:
    h, s, f, a = data["header"], data["saude"], data["faturamento"], data["atividades"]
    px = (a.get("proximas") or {}).get("tasks") or []
    drivers = [m.split(":")[0].strip() for m in (s.get("motivos") or [])]

    diag = []
    if s["score"] is not None and s.get("evaluable", True):
        diag.append(f"Conta em **{s['estagio']}** (score {s['score']:.1f}/100, faixa {s['faixa']}, "
                    f"trajetória {s['trajetoria']}).")
    else:
        diag.append("Conta **sem dados de conversa suficientes** para score — o risco real está invisível; "
                    "a prioridade é restabelecer canal e leitura.")
    if s["tom"]["rotulo"] in ("crítico", "negativo", "atenção"):
        diag.append(f"Tom das conversas **{s['tom']['rotulo']}** ({s['tom']['detalhe']}).")
    if s.get("exec_score") is not None and s["exec_score"] < 70:
        diag.append(f"Execução em **{s['exec_score']:.0f}/100** — atrito de entrega alimentando a insatisfação.")
    tot = f.get("comparativo") or []
    t_ref = sum(b["total_ref"] for b in tot)
    t_prev = sum(b["total_prev"] for b in tot)
    lancado = any(b.get("ref_lancado") for b in tot)
    if lancado and t_prev > 0:
        var = (t_ref - t_prev) / t_prev * 100
        diag.append(f"Faturamento {('subiu' if var >= 0 else 'caiu')} {abs(var):.0f}% no mês "
                    f"(R$ {t_prev:,.0f} → R$ {t_ref:,.0f}).".replace(",", "."))
    if a["total"] == 0:
        diag.append("**Nenhuma entrega concluída no mês** — antes da reunião, garantir pelo menos 1 entrega visível.")

    acoes: list[str] = []
    for d in drivers[:3]:
        for txt in _DRIVER_ACOES.get(d, ()):  # ações específicas da dor, na ordem de peso
            if txt not in acoes:
                acoes.append(txt)
    if s.get("exec_score") is not None and s["exec_score"] < 70:
        acoes.append("Destravar a fila no ClickUp com o squad: repriorizar atrasadas e definir datas realistas "
                     "ANTES da reunião — não prometer prazo novo sem fila limpa.")
    if lancado and t_prev > 0 and (t_ref - t_prev) / t_prev <= -0.2:
        acoes.append("Investigar a queda de faturamento (estoque, reputação, sazonalidade, concorrência) e levar "
                     "diagnóstico + 1 ação de recuperação por marketplace.")
    if not acoes:
        acoes.append("Conta estável: usar a reunião para expandir — apresentar 1 oportunidade nova "
                     "(marketplace ainda não explorado, ADS, kit de produtos) e renovar o plano de metas.")
    guia = action_guideline(acc.get("stage") or "nao_avaliavel", is_legacy=bool(acc.get("is_legacy")),
                            recurring_revenue=acc.get("recurring_revenue"),
                            evaluable=bool(acc.get("evaluable")), reasons=acc.get("reasons"),
                            exec_score=s.get("exec_score"))

    conduz = []
    if a["total"]:
        conduz.append(f"Abrir mostrando as {a['total']} entregas do mês (lista na seção Atividades) — valor primeiro.")
    if px:
        conduz.append(f"Apresentar as próximas {len(px)} atividades previstas com datas — mostra plano, reduz ansiedade.")
    conduz.append("Fechar com resumo escrito no grupo do WhatsApp no MESMO dia: combinados, responsáveis e datas.")

    riscos = []
    if "fala_em_cancelar" in drivers or s["estagio"] == "intenção de saída":
        riscos.append("Cancelamento explícito na mesa — sem contato do GC esta semana, a decisão se consolida.")
    if "silencio" in drivers:
        riscos.append("Silêncio prolongado: se não responder em 5 dias úteis, escalar para telefone/contato do decisor.")
    if s.get("exec_score") is not None and s["exec_score"] < 40:
        riscos.append("Entregas atrasadas: qualquer promessa nova sem limpar a fila vira mais frustração.")
    riscos.append("Acompanhar: tom das próximas conversas e resposta do cliente ao plano — registrar TUDO nas "
                  "atualizações do caso (alimenta o próximo plano).")

    parts = ["### Diagnóstico", " ".join(diag),
             "", "### Objetivo da próxima reunião", guia,
             "", "### Plano de ação (próximas 2 semanas)"]
    parts += [f"{i}. {t}" for i, t in enumerate(acoes[:6], 1)]
    parts += ["", "### Condução da reunião"] + [f"- {c}" for c in conduz]
    parts += ["", "### Riscos e sinais para acompanhar"] + [f"- {r}" for r in riscos]
    if updates:
        u = updates[0]
        parts += ["", f"*Plano considera a última atualização do gestor "
                      f"({str(u['created_at'])[:10]}): “{u['text'][:160]}”*"]
    return "\n".join(parts)


def generate_plan(data: dict, updates: list[dict], acc: dict) -> dict:
    """{texto (markdown), gerado_por, gerado_em}. Tenta Claude (com cache 20h
    por conta+mês — regerar o relatório não paga nem espera de novo); senão
    determinístico."""
    dossie = _dossie(data, updates)
    ref = str((data.get("header") or {}).get("reference_month") or "")
    aid = str(acc.get("id") or (data.get("header") or {}).get("account_id") or "")
    texto = _via_claude(dossie, cache_key=(aid, ref) if aid and ref else None)
    motor = "Claude (gestor de CS sênior)" if texto else \
        "regras determinísticas (Claude assume quando os créditos de API forem liberados)"
    if not texto:
        texto = _plan_deterministico(data, updates, acc)
    return {"texto": texto, "gerado_por": motor,
            "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat()}
