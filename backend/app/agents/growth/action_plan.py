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
cliente e escreve o preparo que o gestor lê MINUTOS ANTES de entrar na reunião com ele.

O QUE ESTE DOCUMENTO É — e o que ele NÃO é (regra do Otávio, 23/07):
O gestor JÁ SABE quais tarefas o time tem para fazer; a fila do ClickUp é óbvia para ele e
NÃO é plano de ação. O que ele não tem — e é o que você deve entregar — é como CONDUZIR
ESTA conta: como está a relação, o que esse cliente específico valoriza, o que já irritou,
que assunto abrir e qual evitar, o que funcionou antes com ele. Escreva sobre a RELAÇÃO e
a CONVERSA, não sobre o backlog. Só cite uma tarefa do ClickUp quando ela for o assunto da
conversa (ex.: uma entrega atrasada que o cliente cobrou nominalmente).

Hierarquia das fontes (a mais recente manda): 1) atualizações dos gestores (ClickUp e
painel) — é o estado REAL do caso, escrito por quem falou com o cliente; 2) o que o cliente
disse nas conversas (tom, temas, reclamações); 3) NPS; 4) números (faturamento, execução).

Regras: use SOMENTE os dados do dossiê (não invente fatos, números, nomes nem falas); se
faltar base para uma seção, diga o que precisa ser descoberto na reunião em vez de inventar;
escreva em pt-BR, direto, como quem conhece a conta; formato markdown EXATO com estas seções:
### Onde a relação está
### O que este cliente valoriza (e o que irrita)
### Como conduzir a conversa
### Assuntos a puxar (e os que evitar)
### O que observar depois
Máx. ~350 palavras. Em "Como conduzir a conversa", dê frases de abertura possíveis, não
tópicos genéricos. Seja específico: cite o que o cliente disse/o que o gestor registrou."""


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
    if f.get("conf"):
        lines.append("TIPO DE CONTA: Configuração de Sistema (plano antigo) — SEM acesso aos "
                     "marketplaces do cliente; faturamento não acompanhado por design (não sugerir "
                     "ações de faturamento/planilha; foco em entrega da configuração e relacionamento).")
    if f.get("available") and f.get("comparativo"):
        for b in f["comparativo"]:
            if b.get("prev_antes_inicio"):
                lines.append(f"FATURAMENTO CNPJ {b.get('cnpj') or 'único'}: {h['reference_month_label']} "
                             + (f"R$ {b['total_ref']:,.0f}" if b.get("ref_lancado") else "(não lançado)")
                             + " (cliente novo — sem base no mês anterior)")
                continue
            lines.append(f"FATURAMENTO CNPJ {b.get('cnpj') or 'único'}: "
                         f"{h['prev_month_label']} R$ {b['total_prev']:,.0f} → {h['reference_month_label']} "
                         + (f"R$ {b['total_ref']:,.0f}" if b.get("ref_lancado") else "(não lançado)"))
    elif f.get("aviso"):
        lines.append(f"FATURAMENTO: {f['aviso']}")
    # --- RELACIONAMENTO primeiro: é o que o gestor não tem em lugar nenhum ---
    # Comentários que os gestores escrevem no card do cliente (lista Clientes
    # Ativos). Fonte MAIS ATUAL do estado do caso — quem escreveu falou com o
    # cliente. Até 23/07 o sistema não lia nada disso (pedido do Otávio).
    if data.get("comentarios_clickup"):
        lines.append("ATUALIZAÇÕES DOS GESTORES NO CLICKUP (mais recentes primeiro — "
                     "estado REAL do caso, prevalece sobre os números):")
        for c in data["comentarios_clickup"][:6]:
            quando = (c.get("data") or "")[:10]
            texto = " ".join((c.get("texto") or "").split())[:400]
            lines.append(f"  [{quando} {c.get('autor') or '?'}] {texto}")
    if updates:
        lines.append("ATUALIZAÇÕES DO GESTOR NO PAINEL (mais recentes primeiro):")
        for u in updates[:6]:
            lines.append(f"  [{str(u['created_at'])[:10]} {u.get('author') or ''}] {u['text']}")
    if data.get("nps"):
        lines.append(f"NPS: {data['nps']}")
    # sinal de ESCOPO (caso PP Sports): expectativa desalinhada precede o pedido
    # de cancelamento em semanas e não aparece em score/tom/execução
    esc = data.get("sinal_escopo")
    if esc:
        lines.append(f"⚠ SINAL DE ESCOPO/EXPECTATIVA — {esc['n']} registro(s) do gestor em que o "
                     "cliente questiona o que o plano cobre. É o padrão que precedeu o cancelamento "
                     "do PP Sports; trate ANTES de virar pedido de saída:")
        for o in esc["ocorrencias"]:
            lines.append(f"  [{o['data']} {o['autor']}] {o['trecho']}")
    # --- contexto de entrega: NÃO é o plano, serve só para citar se virar assunto ---
    lines.append(f"ENTREGAS CONCLUÍDAS NO MÊS: {a['total']} (contexto — o gestor já conhece a fila)")
    px = (a.get("proximas") or {}).get("tasks") or []
    if px:
        lines.append("FILA DO CLICKUP (contexto; só citar se o cliente cobrou nominalmente): "
                     + "; ".join(f"{t['nome']} (vence {t['vence_em']})" for t in px[:6]))
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
            cr = msg.usage.cache_read_input_tokens or 0
            cc = msg.usage.cache_creation_input_tokens or 0
            tin = msg.usage.input_tokens + cr + cc
            record_usage(bconn, "growth:plano_acao", _MODEL, tin, msg.usage.output_tokens,
                         cache_read=cr, cache_creation=cc)
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

    # mesmos cabeçalhos do motor Claude — o relatório não pode mudar de forma
    # conforme o motor que gerou (regra do redesenho: uma régua por conceito)
    parts = ["### Onde a relação está", " ".join(diag),
             "", "### O que este cliente valoriza (e o que irrita)", guia,
             "", "### Como conduzir a conversa"]
    parts += [f"{i}. {t}" for i, t in enumerate(acoes[:6], 1)]
    parts += ["", "### Assuntos a puxar (e os que evitar)"] + [f"- {c}" for c in conduz]
    parts += ["", "### O que observar depois"] + [f"- {r}" for r in riscos]
    # o que o gestor registrou tem prioridade sobre qualquer número — mostrar
    # explicitamente as duas fontes (ClickUp e painel), a mais recente primeiro
    coment = (data.get("comentarios_clickup") or [])
    if coment:
        c0 = coment[0]
        parts += ["", f"*Última atualização do gestor no ClickUp "
                      f"({(c0.get('data') or '')[:10]}, {c0.get('autor') or '?'}): "
                      f"“{' '.join((c0.get('texto') or '').split())[:200]}”*"]
    if updates:
        u = updates[0]
        parts += ["", f"*Última atualização no painel "
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
