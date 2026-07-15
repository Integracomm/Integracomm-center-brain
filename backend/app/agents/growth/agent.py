"""Agente de Growth — implementação de referência do contrato da casca.

Amarra: coleta (WhatsApp via growth-agent-read + ClickUp execução) → análise →
score (scoring.py, pesos 45/25/15/15) → persistência com LOOP DE FEEDBACK
(signal_snapshots + scores + alerts + outcomes) → exposição no painel (RBAC).

NÃO executa ação consequente: apenas calcula, grava e sinaliza.
"""
from __future__ import annotations

import datetime as dt
import sys
from typing import Any

from ..base import AccountScore, Agent, AgentContext
from ..registry import register
from . import scoring


class GrowthAgent(Agent):
    key = "growth"
    role = "gestor_growth"

    def __init__(self, conn_factory: Any = None) -> None:
        # conn_factory() -> conexão psycopg (a casca injeta; None em dry-run)
        self._conn_factory = conn_factory

    # -- coleta -----------------------------------------------------------
    def collect(self, ctx: AgentContext) -> dict[str, list[scoring.SignalInput]]:
        """Lê fontes em modo SOMENTE LEITURA e produz séries de sinais por conta.

        Recebe a amostra em ``ctx.sample`` (lista de dicts com account_id, name,
        group_id, asof e meta). Lê WhatsApp (mensagens via WhatsAppReader +
        analyses do cache) e monta as séries semanais via collectors.
        """
        import os

        from . import collectors
        from ...sources.whatsapp import WhatsAppReader

        sample = getattr(ctx, "sample", None)
        if not sample:
            raise ValueError("ctx.sample vazio — informe as contas (group_id/asof/meta).")

        reader = WhatsAppReader(os.environ["WHATSAPP_READ_API_URL"], os.environ["WHATSAPP_READ_API_KEY"],
                                audit=ctx.audit, run_id=ctx.run_id)

        # confirmador semântico de fala de cancelamento (Claude + cache por msg;
        # None = sem chave/desligado -> regex-only, comportamento anterior)
        from .cancel_confirm import build_confirmer
        confirmer = build_confirmer(self._conn_factory)
        if confirmer is not None:
            print("  [cancel-llm] confirmador semântico ATIVO (Haiku + cache)", file=sys.stderr)

        raw: dict[str, list[scoring.SignalInput]] = {}
        meta: dict[str, dict] = {}
        skipped: list[tuple[str, str]] = []  # (conta, motivo) — resiliência por conta
        try:
            for item in sample:
                gid = item["group_id"]
                # RESILIÊNCIA: uma conta que falha na leitura (timeout persistente,
                # grupo inacessível) é PULADA — não pode derrubar a rodada inteira.
                try:
                    # analyses AO VIVO por grupo (nunca de cache — senão perde CRÍTICO recente)
                    analyses_live = {gid: [(a.analysis_date, a.classification)
                                           for a in reader.iter_analyses(group_id=gid)]}
                    eventos: dict = {}
                    sigs = collectors.build_account_signals(
                        reader, group_internal_id=gid, asof=item["asof"],
                        analyses_by_group=analyses_live, events_out=eventos,
                        cancel_confirmer=confirmer,
                    )
                    # EXECUÇÃO no score (bloco 15%): risco direto pré-computado pelo
                    # runner (mirror ClickUp as-of, porte fiel). Ausente -> bloco fora,
                    # renormaliza (comportamento validado).
                    if item.get("execution_risk") is not None:
                        sigs.append(scoring.SignalInput(
                            "execucao", "execution", [], higher_is_worse=True,
                            source="clickup", direct_risk=float(item["execution_risk"]),
                        ))
                    # TOM via Claude (3b): série semanal de risco (0-1) pré-computada
                    # pelo run_tone_analysis e cacheada no banco; o runner anexa.
                    # Filtra à janela do score; sem análise -> sinal fora (renormaliza
                    # dentro do bloco tone, que segue com tom_negativo/comprimento).
                    tone = item.get("tone_series") or []
                    asof = item["asof"]
                    tone_pts = [(d, r) for d, r in tone
                                if asof - dt.timedelta(days=90) <= d <= asof]
                    if tone_pts:
                        sigs.append(scoring.SignalInput(
                            "tom_claude", "tone", tone_pts, higher_is_worse=True,
                            source="claude", absolute_is_risk=True,
                        ))
                    raw[item["account_id"]] = sigs
                    meta[item["account_id"]] = {
                        "name": item["name"], "plan_category": item.get("plan_category"),
                        "is_legacy": item.get("is_legacy", False),
                        "recurring_revenue": item.get("recurring_revenue"),
                        "case_events": eventos.get("episodios") or [],
                    }
                except Exception as e:  # noqa: BLE001 — isolar falha de UMA conta
                    skipped.append((item.get("name", gid), f"{type(e).__name__}: {e}"))
                    print(f"  [skip] {item.get('name', gid)[:40]}: {type(e).__name__}", file=sys.stderr)
        finally:
            reader.close()
        ctx.account_meta = meta  # consumido pelo score()
        ctx.skipped = skipped    # exposto p/ o runner reportar/auditar
        return raw

    # -- análise ----------------------------------------------------------
    def analyze(self, ctx: AgentContext, raw: dict[str, Any]) -> dict[str, list[scoring.SignalInput]]:
        """As séries já vêm como SignalInput do collect. (O refino de tom via
        Claude/Sonnet — passo 3b — entra aqui quando houver créditos de API.)"""
        return raw

    # -- score ------------------------------------------------------------
    def score(self, ctx: AgentContext, analyzed: dict[str, list[scoring.SignalInput]]) -> list[AccountScore]:
        scores: list[AccountScore] = []
        meta = getattr(ctx, "account_meta", {}) if ctx else {}
        for account_id, signals in analyzed.items():
            m = meta.get(account_id, {})
            scores.append(
                scoring.score_account(
                    account_id=account_id,
                    account_name=m.get("name", account_id),
                    signals=signals,
                    plan_category=m.get("plan_category"),
                    is_legacy=m.get("is_legacy", False),
                    recurring_revenue=m.get("recurring_revenue"),
                    now=ctx.window_end if ctx else None,
                )
            )
        return scores

    # -- persistência + LOOP DE FEEDBACK ----------------------------------
    def persist(self, ctx: AgentContext, scores: list[AccountScore]) -> None:
        """Grava score/alerta/auditoria E a foto dos sinais (sinal × desfecho)."""
        if self._conn_factory is None:
            return  # dry-run (sem DB) — usado em testes da fórmula
        from ...db import persistence as P

        conn = self._conn_factory()
        try:
            meta = getattr(ctx, "account_meta", {}) if ctx else {}
            for s in scores:
                acc = P.ensure_account(
                    conn, id_interno=s.account_id, name=s.account_name,
                    name_norm=s.account_name.lower(), plan_category=s.plan_category,
                    is_legacy=s.is_legacy, recurring_revenue=s.recurring_revenue,
                )
                P.audit(conn, actor=f"agent:{self.key}", action="read",
                        source="whatsapp+clickup", scope="janela", account_id=acc, run_id=ctx.run_id)
                P.record_signal_snapshots(
                    conn, account_id=acc, run_id=ctx.run_id, captured_at=s.computed_at,
                    signals=[{"source": r.source, "signal_key": r.text.split(":")[0],
                              "value_num": r.weight, "leading": r.leading} for r in s.reasons],
                )
                with conn.cursor() as cur:  # estágio ANTERIOR (p/ evento de recuperação)
                    cur.execute("SELECT stage FROM scores WHERE account_id=%s ORDER BY computed_at DESC LIMIT 1",
                                (acc,))
                    row = cur.fetchone()
                    prev_stage = row[0] if row else None
                sid = P.record_score(conn, account_id=acc, run_id=ctx.run_id, score=s)
                P.audit(conn, actor=f"agent:{self.key}", action="score", account_id=acc, run_id=ctx.run_id)
                P.record_alert(conn, account_id=acc, score_id=sid, score=s)
                if scoring.should_alert(s):
                    P.audit(conn, actor=f"agent:{self.key}", action="alert", account_id=acc, run_id=ctx.run_id)
                self._record_case_timeline(
                    conn, account_id=acc, score=s, prev_stage=prev_stage,
                    episodios=meta.get(s.account_id, {}).get("case_events") or [])
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _record_case_timeline(conn: Any, *, account_id: str, score: AccountScore,
                              prev_stage: str | None, episodios: list[dict]) -> None:
        """Linha do tempo AUTOMÁTICA do caso (case_updates, autor 'agente'):
        pedido de cancelamento do cliente → equipe abordando o tema → estágio
        normalizado. Texto determinístico com a data do evento = chave de dedup
        (add_case_update_once); só datas/derivados, sem conteúdo bruto (LGPD).
        Aparece no relatório individual e na aba Alertas."""
        from ...reports import add_case_update_once

        for ep in episodios:
            ini = ep["inicio"]
            add_case_update_once(
                conn, account_id, "agente",
                f"[auto] Cliente verbalizou pedido de cancelamento no grupo em {ini.strftime('%d-%m-%Y')}.")
            if ep.get("equipe"):
                d_eq, quem = ep["equipe"]
                add_case_update_once(
                    conn, account_id, "agente",
                    f"[auto] Equipe abordou o cancelamento no grupo em {d_eq.strftime('%d-%m-%Y')} ({quem}).")
        exit_stage = scoring.DeclineStage.EXIT_INTENT.value
        if prev_stage == exit_stage and score.stage.value != exit_stage and score.evaluable:
            hoje = dt.date.today().strftime("%d-%m-%Y")
            add_case_update_once(
                conn, account_id, "agente",
                f"[auto] Estágio normalizado em {hoje}: 3 semanas sem novas falas de cancelamento "
                "— relacionamento em recuperação.")

    # -- exposição (RBAC) -------------------------------------------------
    def surface(self, ctx: AgentContext, scores: list[AccountScore]) -> None:
        """Painel lê de `scores`/`alerts` filtrando pelo papel. Sem ação aqui."""
        return None


# Encaixe na casca: registrar = o painel passa a exibir Growth sob gestor_growth.
register(GrowthAgent())
