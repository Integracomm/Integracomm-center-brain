"""Envio diário do relatório ao Slack: garantido, único e honesto sobre a idade.

Contexto (Otávio 27/07: "o relatório diário do Slack não foi enviado na sexta"):
o envio vivia DENTRO da rodada das 06h (`run_portfolio --slack`). Quando a
rodada trava ou estoura o teto de 4h — o que aconteceu em 24, 25, 26 e 27/07 —
ela nunca chega à linha do envio e o grupo dos gestores simplesmente não recebe
nada. Silêncio indistinguível de "não há novidade".

Agora existe um caminho independente (backup às 10h15) e os dois compartilham:
  - guarda de idempotência por DIA, para os dois caminhos não duplicarem;
  - aviso de idade do dado, porque a rodada pode ter travado e os scores serem
    de dias atrás (em 27/07 estavam congelados havia 4 dias e ninguém sabia).
"""
from __future__ import annotations

import app.slack as S


class _Cur:
    """Cursor de mentira: devolve a resposta programada por padrão de SQL."""

    def __init__(self, respostas: dict, executados: list):
        self._r, self._ex, self._ultimo = respostas, executados, None

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, sql, params=None):
        self._ultimo = " ".join(sql.split())
        self._ex.append((self._ultimo, params))

    def fetchone(self):
        for chave, val in self._r.items():
            if chave in self._ultimo:
                return val
        return None


class _Conn:
    def __init__(self, respostas, executados):
        self._r, self._ex = respostas, executados

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def cursor(self): return _Cur(self._r, self._ex)


def _monta(monkeypatch, *, ja_enviou, dias_de_atraso):
    """Prepara slack.py com um banco e um _report_from/_report_text de mentira."""
    enviados, executados = [], []
    respostas = {
        "FROM audit_log WHERE action='report_slack'": (1,) if ja_enviou else None,
        "FROM scores": (dias_de_atraso,),
    }
    import app.api as A
    monkeypatch.setattr(A, "_conn", lambda: _Conn(respostas, executados))
    monkeypatch.setattr(A, "_latest_scores", lambda c: [{"computed_at": "x"}])
    monkeypatch.setattr(A, "_open_alerts", lambda c: [])
    monkeypatch.setattr(A, "_report_from", lambda s, a, **k: {"fake": True})
    monkeypatch.setattr(A, "_report_text", lambda r: "RELATORIO")
    monkeypatch.setattr(S, "send_text", lambda t: enviados.append(t))
    return enviados, executados


def test_envia_quando_ainda_nao_enviou_hoje(monkeypatch):
    enviados, executados = _monta(monkeypatch, ja_enviou=False, dias_de_atraso=0)
    assert S.enviar_relatorio_diario(actor="test") == "enviado"
    assert enviados == ["RELATORIO"]
    # e registra na auditoria, que é o que sustenta a guarda do dia seguinte
    assert any("INSERT INTO audit_log" in sql for sql, _ in executados)


def test_nao_duplica_quando_a_rodada_ja_enviou(monkeypatch):
    """A rodada das 06h enviou; o backup das 10h15 tem de ficar quieto."""
    enviados, executados = _monta(monkeypatch, ja_enviou=True, dias_de_atraso=0)
    assert S.enviar_relatorio_diario(actor="script:send_slack_report") == "ja-enviado-hoje"
    assert enviados == []
    assert not any("INSERT INTO audit_log" in sql for sql, _ in executados)


def test_force_ignora_a_guarda(monkeypatch):
    enviados, _ = _monta(monkeypatch, ja_enviou=True, dias_de_atraso=0)
    assert S.enviar_relatorio_diario(actor="test", force=True) == "enviado"
    assert enviados == ["RELATORIO"]


def test_avisa_quando_o_dado_esta_velho(monkeypatch):
    """Rodada travada há 4 dias: o relatório sai, mas dizendo que é dado velho.
    Mandar números de 4 dias atrás como se fossem de hoje é pior que não mandar."""
    enviados, _ = _monta(monkeypatch, ja_enviou=False, dias_de_atraso=4)
    assert S.enviar_relatorio_diario(actor="test") == "enviado-com-aviso"
    texto = enviados[0]
    assert "4 dia(s) atrás" in texto
    assert texto.rstrip().endswith("RELATORIO")  # o aviso vem ANTES, não substitui


def test_dado_do_dia_nao_leva_aviso(monkeypatch):
    enviados, _ = _monta(monkeypatch, ja_enviou=False, dias_de_atraso=0)
    S.enviar_relatorio_diario(actor="test")
    assert enviados[0] == "RELATORIO"
