"""Gerador da apresentação ALL HANDS mensal — /allhands (pedido Otávio 15/07/26).

Replica o design do deck oficial (ALL HANDS - JUNHO-26.pdf: fundo preto #0d0d0d,
amarelo Integracomm #ffc107, Montserrat, cards #1a1a1a, capa com a arte de feixes
dourados extraída do próprio PDF) e preenche os slides de DADOS automaticamente
com as mesmas réguas oficiais do app:

  1. Capa (mês/ano)
  2. Marketing & Comercial — funil do mês fechado (_funil_oficial) + vendas por
     plano (produto dos deals won) + meta da planilha de planejamento
  3. Operação: clientes por plano (espelho da Operação, antigos × novos)
  4. Saídas (churn) por plano no mês (grw_cancelamentos) + taxa × meta
  5. Evolução da taxa de cancelamento (planilha, jan → mês fechado)
  6. Metas do mês seguinte (meta comercial + meta churn)
  7-8. Promovidos & Destaques (MANUAL: nome/cargo/tipo/nível/foto — slide sai se vazio)
  9. Novos colaboradores (MANUAL: liga/desliga + nomes — roteiro fixo do deck)
 10. Orientações & Novidades (MANUAL: cards título/subtítulo/texto — sai se vazio)
 10b. Slides EXTRAS (MANUAL, 16/07: quantos quiser — categoria/título; cada linha
      do texto vira um marcador; imagem opcional à direita. Ex.: evento do mês)
 11. Fechamento ("ótimo mês para todos nós")

Fotos enviadas no formulário são EMBUTIDAS em base64 no HTML gerado (nada é
persistido). Exportar = botão Imprimir/PDF (@page 16:9 tamanho PowerPoint).
"""
from __future__ import annotations

import base64
import datetime as dt
from html import escape
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()

_ASSETS = Path(__file__).parent / "assets"
_MESES = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO",
          "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]

# classificação de planos observada no deck de junho (coluna Antigos × Novos)
_PLANOS_NOVOS = ("start", "traction", "scale", "platinum", "elite")


def _deps():
    from . import api as A
    return A


def _b64(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _require_admin(request: Request):
    A = _deps()
    s = A._session(request)
    if not s:
        return None, RedirectResponse("/login", status_code=302)
    user, role = s
    if role != "admin":
        return None, RedirectResponse("/", status_code=302)
    return s, None


def _mes_fechado_default() -> dt.date:
    hoje = dt.date.today()
    return (hoje.replace(day=1) - dt.timedelta(days=1)).replace(day=1)


# ---------------------------------------------------------------------------
# dados automáticos
# ---------------------------------------------------------------------------
_LISTA_CLIENTES_ATIVOS = "901002253296"  # ADM › Clientes › Clientes Ativos
# rótulo do deck ← rótulos do campo Serviço, em ordem de PRIORIDADE (cliente com
# múltiplos serviços conta uma vez, no plano mais alto; ADS/Estratégia só quando
# não há plano de assessoria)
_PLANO_DECK = [
    ("Elite", ("ELITE",)), ("Platinum", ("PLATINUM",)), ("Scale", ("SCALE",)),
    ("Traction", ("TRACTION",)), ("Start", ("Assessoria Start",)),
    ("Smart", ("Assessoria Smart",)), ("Master", ("Assessoria Master",)),
    ("ADS", ("ADS para Marketplace",)), ("Estratégia", ("Estratégia de Vendas",)),
    ("Antigo/Basic", ("Assessoria Basic", "Assessoria", "Assessoria Potencializar")),
]


def _clientes_ativos_por_plano(fim_mes: dt.date) -> tuple[list[tuple[str, int]], dict[str, int]]:
    """Contagens por plano na lista Clientes Ativos, AS-OF o fim do mês de
    referência (criado até lá e não fechado até lá — gerar em julho o deck de
    junho não pode contar o estado de hoje; validação Otávio 15/07).
    Retorna DUAS réguas: (por SERVIÇO, por CLIENTE).
    - por SERVIÇO = régua do slide 'Clientes por plano' (cliente com plano +
      ADS aparece nas duas linhas; o 'total geral' do deck é a SOMA: jun=245);
    - por CLIENTE = cada card conta 1× no plano de maior prioridade — régua da
      TAXA de cancelamento (16/07: a base implícita do deck antigo é por
      cliente, não por serviço).
    'pausada por inatividade' fica fora (inadimplente); serviços acessórios
    (Implantação, Consultoria, CNPJ Adicional...) não são linhas do deck."""
    from .config import get_settings
    from .sources.clickup_activities import _download_list
    s = get_settings()
    lista = s.clickup_list_clientes_ativos or _LISTA_CLIENTES_ATIVOS
    try:
        tasks = _download_list(s.clickup_api_token, lista)
    except Exception:  # noqa: BLE001 — ClickUp fora não derruba a geração
        return []
    corte = dt.datetime.combine(fim_mes + dt.timedelta(days=1), dt.time(3, 0),
                                tzinfo=dt.timezone.utc)  # fim do dia BRT

    def ts(ms):
        return dt.datetime.fromtimestamp(int(ms) / 1000, tz=dt.timezone.utc) if ms else None

    contagem: dict[str, int] = {}
    por_cliente: dict[str, int] = {}
    for t in tasks:
        if t.get("parent"):
            continue
        if (t.get("status") or {}).get("status") == "pausada por inatividade":
            continue  # inadimplente (regra Otávio) — o deck não conta
        criado, fechado = ts(t.get("date_created")), ts(t.get("date_closed"))
        if not criado or criado >= corte or (fechado is not None and fechado < corte):
            continue
        rotulos = set()
        for c in (t.get("custom_fields") or []):
            if c.get("name") == "Serviço":
                opts = {o["id"]: (o.get("label") or o.get("name") or "")
                        for o in (c.get("type_config", {}).get("options") or [])}
                rotulos = {opts.get(v, "") for v in (c.get("value") or [])}
                break
        primeiro = True
        for nome, labels in _PLANO_DECK:  # multi-serviço: uma linha por serviço
            if any(lb in rotulos for lb in labels):
                contagem[nome] = contagem.get(nome, 0) + 1
                if primeiro:  # por CLIENTE: só o plano de maior prioridade
                    por_cliente[nome] = por_cliente.get(nome, 0) + 1
                    primeiro = False
    ordem = [nome for nome, _ in _PLANO_DECK]
    return sorted(contagem.items(), key=lambda x: ordem.index(x[0])), por_cliente


def _dados_mes(conn, mes: dt.date) -> dict:
    """Todos os números dos slides automáticos, nas réguas oficiais do app."""
    import calendar

    from .marketing.ui import _funil_oficial
    from .sources import planejamento_financeiro as PF

    fim = mes.replace(day=calendar.monthrange(mes.year, mes.month)[1])
    passou, booked, _tot, receita = _funil_oficial(conn, mes, fim)

    with conn.cursor() as cur:
        # vendas por plano (produto do deal won no mês; sem produto = 'Outros')
        cur.execute("""SELECT COALESCE(NULLIF(produto, ''), 'Outros'), count(*),
                              COALESCE(sum(COALESCE(valor_custom, valor)), 0)
                         FROM mkt_deals_attribution
                        WHERE status='won' AND won_time >= %s AND won_time < %s
                        GROUP BY 1 ORDER BY 2 DESC""",
                    (f"{mes} 00:00-03", f"{fim + dt.timedelta(days=1)} 00:00-03"))
        vendas_plano = [(p, int(n), float(v)) for p, n, v in cur.fetchall()]
        # saídas do mês por plano (régua oficial de cancelamentos). Normaliza:
        # rótulo composto 'Master + ADS' conta no plano principal; plano VAZIO
        # na planilha fica fora das colunas (como no deck) e vira nota de rodapé
        cur.execute("""SELECT COALESCE(NULLIF(plano, ''), ''), count(*),
                              COALESCE(sum(valor), 0)
                         FROM grw_cancelamentos
                        WHERE tipo='cancelamento' AND mes = %s
                        GROUP BY 1 ORDER BY 2 DESC""", (mes,))
        brutos = [(p.strip(), int(n), float(v or 0)) for p, n, v in cur.fetchall()]
        agr: dict[str, int] = {}
        agr_mrr: dict[str, float] = {}
        saidas_sem_plano = 0
        for p, n, v in brutos:
            principal = p.split("+")[0].strip()
            if not principal:
                saidas_sem_plano += n
                continue
            agr[principal] = agr.get(principal, 0) + n
            agr_mrr[principal] = agr_mrr.get(principal, 0.0) + v
        saidas_plano = sorted(agr.items(), key=lambda x: -x[1])
        saidas_total = sum(n for _, n in saidas_plano)

    # clientes ativos por plano — lista CLIENTES ATIVOS do ClickUp (ADM›Clientes,
    # 901002253296): é a FONTE do deck oficial (validado 15/07: 30/06 ≈ 245 do
    # deck de junho; Antigo/Basic 9 e Estratégia 2 exatos). Régua: card-raiz com
    # status 'ativo' (pausada por inatividade = inadimplente, fora — regra do
    # Otávio), 1 plano por cliente pela prioridade de Serviço.
    clientes_plano, cli_por_plano = _clientes_ativos_por_plano(fim)
    base_ativa = sum(n for _, n in clientes_plano)

    pf = PF.carrega()
    meta_mes = meta_prox = churn_meta = None
    churn_serie: list[tuple[str, float]] = []
    if pf:
        iso = f"{mes.year:04d}-{mes.month:02d}"
        if iso in pf["meses"]:
            i = pf["meses"].index(iso)
            meta_mes = PF.linha(pf, "Meta Bookings [R$]")[i]
            if i + 1 < len(pf["meses"]):
                meta_prox = PF.linha(pf, "Meta Bookings [R$]")[i + 1]
                churn_meta = PF.linha(pf, "Taxa de cancelamento - TOTAL")[i + 1]
            tx = PF.linha(pf, "Taxa de cancelamento - TOTAL")
            for j, m_iso in enumerate(pf["meses"]):
                if m_iso.startswith(str(mes.year)) and m_iso <= iso and tx[j] is not None:
                    churn_serie.append((_MESES[int(m_iso[5:7]) - 1][:3], tx[j]))
            # zeros no INÍCIO da série = mês sem dado lançado, não churn zero
            # (Otávio 15/07: jan 0,0%% saía no gráfico como se fosse real)
            while churn_serie and not churn_serie[0][1]:
                churn_serie.pop(0)
    # taxa GERAL do mês (régua Otávio 16/07): só planos RECORRENTES — o B1/Start
    # é semestral pago à vista (não recorrente) e distorcia a taxa geral; era
    # essa a diferença p/ os números dos decks antigos. Régua: cancelados
    # recorrentes ÷ base ativa recorrente. Junto vai a visão por FATURAMENTO
    # (MRR perdido dos recorrentes no mês).
    def _recorrente(plano: str) -> bool:
        p = (plano or "").upper()
        return "START" not in p and not p.startswith("B1")

    # base da TAXA = por CLIENTE (cada cliente 1×), não por serviço — a base
    # implícita nos decks antigos (saídas ÷ taxa) é menor que a soma das linhas
    # e compatível com contagem por cliente sem B1 (análise 16/07)
    base_rec = sum(n for p, n in cli_por_plano.items() if _recorrente(p))
    saidas_rec = sum(n for p, n in saidas_plano if _recorrente(p))
    mrr_rec_perdido = sum(v for p, v in agr_mrr.items() if _recorrente(p))
    taxa_mes = (saidas_rec / base_rec) if base_rec else None

    return {"funil": passou, "bookings": booked, "receita": receita,
            "vendas_plano": vendas_plano, "clientes_plano": clientes_plano,
            "base_ativa": base_ativa, "saidas_plano": saidas_plano,
            "saidas_total": saidas_total, "saidas_sem_plano": saidas_sem_plano,
            "base_rec": base_rec, "saidas_rec": saidas_rec,
            "mrr_rec_perdido": mrr_rec_perdido,
            "taxa_mes": taxa_mes, "meta_mes": meta_mes, "meta_prox": meta_prox,
            "churn_meta": churn_meta, "churn_serie": churn_serie}


# ---------------------------------------------------------------------------
# formulário (conteúdo manual do mês)
# ---------------------------------------------------------------------------
_FORM_CSS = """
body{margin:0;background:#0d0d0d;color:#fff;font-family:'Montserrat',sans-serif;padding:34px}
h1{font-weight:700;letter-spacing:.08em} .sec{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:18px 22px;margin:16px 0;max-width:900px}
.sec h2{color:#ffc107;font-size:15px;letter-spacing:.1em;margin:0 0 4px} .sec p{color:#9a9a9a;font-size:12.5px;margin:0 0 12px}
label{display:block;font-size:11px;color:#9a9a9a;text-transform:uppercase;letter-spacing:.08em;margin:8px 0 3px}
input,select,textarea{background:#111;border:1px solid #333;border-radius:8px;color:#fff;font-family:inherit;font-size:13.5px;padding:8px 10px;width:100%;box-sizing:border-box}
.row{display:grid;grid-template-columns:150px 1fr 1fr 110px 1fr auto;gap:10px;align-items:end;margin-bottom:10px}
.row3{display:grid;grid-template-columns:1fr 1fr 2fr auto;gap:10px;align-items:end;margin-bottom:10px}
button{cursor:pointer;font-family:inherit} .add{background:none;border:1px dashed #555;color:#bbb;border-radius:8px;padding:7px 14px;font-size:12.5px}
.del{background:none;border:none;color:#e05555;font-size:17px;padding:0 4px}
.go{background:#ffc107;color:#111;border:none;border-radius:10px;font-weight:700;font-size:15px;letter-spacing:.05em;padding:13px 30px;margin-top:10px}
a{color:#ffc107}
"""

_EMOJIS = [("📌", "aviso geral"), ("📢", "comunicado"), ("☕", "café / copa"), ("🍽️", "cozinha / almoço"),
           ("🚪", "porta / acesso"), ("🔑", "chaves / crachá"), ("🧹", "limpeza / organização"), ("🚻", "banheiros"),
           ("❄️", "ar-condicionado"), ("🖥️", "equipamentos / TI"), ("📶", "internet / wi-fi"), ("🅿️", "estacionamento"),
           ("📦", "encomendas"), ("🕐", "horários"), ("🔇", "silêncio / foco"), ("🎉", "eventos / festas"),
           ("🎂", "aniversários"), ("🏢", "espaço / obras"), ("🧯", "segurança"), ("🎮", "área de descanso"),
           ("💡", "dica"), ("⚠️", "atenção"), ("✅", "novo processo"), ("🚀", "novidade")]

_TIPOS_DQ = ("DESTAQUE", "PROMOÇÃO", "MÉRITO")

_FORM_JS = """
function addDestaque(){
  var d=document.createElement('div'); d.className='row';
  d.innerHTML="<div><label>tipo</label><select name=dq_tipo><option>DESTAQUE</option><option>PROMOÇÃO</option><option>MÉRITO</option></select></div>"
    +"<div><label>nome</label><input name=dq_nome placeholder='ex.: Valéria Gatti'></div>"
    +"<div><label>cargo</label><input name=dq_cargo placeholder='ex.: Coordenadora de Vendas'></div>"
    +"<div><label>nível (opc.)</label><input name=dq_nivel placeholder='ex.: Nível 2'></div>"
    +"<div><label>foto (opc.)</label><input type=file name=dq_foto accept='image/*'>"
    +"<input type=hidden name=dq_foto_b64 value=''></div>"
    +"<button type=button class=del onclick='this.parentNode.remove()'>✕</button>";
  document.getElementById('destaques').appendChild(d);
}
var EMOJIS=__EMOJIS__;
function addOrientacao(){
  var d=document.createElement('div'); d.className='row3';
  var opts=EMOJIS.map(function(e){return "<option value='"+e[0]+"'>"+e[0]+"  "+e[1]+"</option>";}).join("");
  d.innerHTML="<div style='max-width:190px'><label>ícone</label><select name=or_icone>"+opts+"</select></div>"
    +"<div><label>título</label><input name=or_titulo placeholder='ex.: MÁQUINA DE CAFÉ'></div>"
    +"<div><label>texto</label><input name=or_texto placeholder='ex.: atenção na finalização da bebida'></div>"
    +"<button type=button class=del onclick='this.parentNode.remove()'>✕</button>";
  document.getElementById('orientacoes').appendChild(d);
}
function addExtra(){
  var d=document.createElement('div');
  d.style.cssText='border:1px dashed #3a3a3a;border-radius:10px;padding:12px 14px;margin-bottom:12px';
  d.innerHTML="<div style='display:grid;grid-template-columns:220px 1fr auto;gap:10px;align-items:end'>"
    +"<div><label>categoria (canto do slide)</label><input name=sx_kicker placeholder='ex.: Eventos'></div>"
    +"<div><label>título do slide</label><input name=sx_titulo placeholder='ex.: Feira do Empreendedor — próximo mês'></div>"
    +"<button type=button class=del onclick='this.parentNode.parentNode.remove()'>✕</button></div>"
    +"<label>conteúdo — cada linha vira um marcador no slide</label>"
    +"<textarea name=sx_texto rows=3 placeholder='ex.:\\nData: 12/08, das 9h às 18h\\nLocal: Expo Center Norte\\nQuem vai: time de Vendas + Growth'></textarea>"
    +"<label>imagem (opcional — aparece à direita do texto)</label><input type=file name=sx_foto accept='image/*'>"
    +"<input type=hidden name=sx_foto_b64 value=''>";
  document.getElementById('extras').appendChild(d);
}
"""


def _form_page(mes_sel: dt.date | None = None, destaques: list | None = None,
               novos: dict | None = None, orientacoes: list | None = None,
               extras: list | None = None) -> str:
    """Formulário do All Hands — vazio (1ª visita) ou PRÉ-PREENCHIDO (16/07:
    '← ajustar conteúdo' não pode perder o que já foi digitado; fotos voltam
    como campo oculto base64 e são mantidas a menos que se envie outra)."""
    import json as _json
    hoje = dt.date.today()
    meses_opts = []
    for k in range(0, 4):
        m = hoje.replace(day=1)
        for _ in range(k + 1):
            m = (m - dt.timedelta(days=1)).replace(day=1)
        meses_opts.append(m)
    if mes_sel and mes_sel not in meses_opts:
        meses_opts.append(mes_sel)
    alvo = mes_sel or meses_opts[0]
    opcoes = "".join(f"<option value='{m.isoformat()}'{' selected' if m == alvo else ''}>"
                     f"{_MESES[m.month - 1].title()} / {m.year}</option>" for m in meses_opts)

    def _e(v):
        return escape(str(v or ""), quote=True)

    _NOTA_FOTO = "<div style='font-size:10.5px;color:#7fae7f;margin-top:3px'>✓ mantida da edição anterior — envie outra para trocar</div>"
    dq_rows = ""
    for dq in (destaques or []):
        tipos = "".join(f"<option{' selected' if t == dq.get('tipo') else ''}>{t}</option>" for t in _TIPOS_DQ)
        dq_rows += (
            "<div class=row>"
            f"<div><label>tipo</label><select name=dq_tipo>{tipos}</select></div>"
            f"<div><label>nome</label><input name=dq_nome value=\"{_e(dq.get('nome'))}\"></div>"
            f"<div><label>cargo</label><input name=dq_cargo value=\"{_e(dq.get('cargo'))}\"></div>"
            f"<div><label>nível (opc.)</label><input name=dq_nivel value=\"{_e(dq.get('nivel'))}\"></div>"
            f"<div><label>foto (opc.)</label><input type=file name=dq_foto accept='image/*'>"
            f"{_NOTA_FOTO if dq.get('foto') else ''}"
            f"<input type=hidden name=dq_foto_b64 value=\"{_e(dq.get('foto'))}\"></div>"
            "<button type=button class=del onclick='this.parentNode.remove()'>✕</button></div>")
    or_rows = ""
    for o in (orientacoes or []):
        opts = "".join(f"<option value='{ic}'{' selected' if ic == o.get('icone') else ''}>{ic}  {lb}</option>"
                       for ic, lb in _EMOJIS)
        or_rows += (
            "<div class=row3>"
            f"<div style='max-width:190px'><label>ícone</label><select name=or_icone>{opts}</select></div>"
            f"<div><label>título</label><input name=or_titulo value=\"{_e(o.get('titulo'))}\"></div>"
            f"<div><label>texto</label><input name=or_texto value=\"{_e(o.get('texto'))}\"></div>"
            "<button type=button class=del onclick='this.parentNode.remove()'>✕</button></div>")
    sx_blocks = ""
    for ex in (extras or []):
        sx_blocks += (
            "<div style='border:1px dashed #3a3a3a;border-radius:10px;padding:12px 14px;margin-bottom:12px'>"
            "<div style='display:grid;grid-template-columns:220px 1fr auto;gap:10px;align-items:end'>"
            f"<div><label>categoria (canto do slide)</label><input name=sx_kicker value=\"{_e(ex.get('kicker'))}\"></div>"
            f"<div><label>título do slide</label><input name=sx_titulo value=\"{_e(ex.get('titulo'))}\"></div>"
            "<button type=button class=del onclick='this.parentNode.parentNode.remove()'>✕</button></div>"
            "<label>conteúdo — cada linha vira um marcador no slide</label>"
            f"<textarea name=sx_texto rows=3>{escape(ex.get('texto') or '')}</textarea>"
            "<label>imagem (opcional — aparece à direita do texto)</label><input type=file name=sx_foto accept='image/*'>"
            f"{_NOTA_FOTO if ex.get('foto') else ''}"
            f"<input type=hidden name=sx_foto_b64 value=\"{_e(ex.get('foto'))}\"></div>")
    novos_chk = " checked" if novos else ""
    js = _FORM_JS.replace("__EMOJIS__", _json.dumps([list(e) for e in _EMOJIS], ensure_ascii=False))
    return f"""<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>All Hands — gerar apresentação</title>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;700;800&display=swap" rel=stylesheet>
<style>{_FORM_CSS}</style></head><body>
<a href="/">← voltar à central</a>
<h1>APRESENTAÇÃO <span style="color:#ffc107">ALL HANDS</span></h1>
<p style="color:#9a9a9a;max-width:860px">Os slides de dados (funil, vendas por plano, clientes por plano, churn, evolução e metas)
são preenchidos automaticamente com as mesmas réguas do painel. Preencha abaixo só o conteúdo do mês —
<b>seções vazias saem da apresentação</b>. Fotos são embutidas na hora (nada fica salvo no servidor).</p>
<form method=post action="/allhands/gerar" enctype="multipart/form-data">
<div class=sec><h2>MÊS DE REFERÊNCIA</h2><p>use um mês fechado — os números do funil/churn são do mês inteiro</p>
<select name=mes style="max-width:280px">{opcoes}</select></div>
<div class=sec><h2>DESTAQUES & PROMOÇÕES</h2><p>um slide por pessoa, no layout do deck (foto, tipo, nome, cargo, nível)</p>
<div id=destaques>{dq_rows}</div><button type=button class=add onclick="addDestaque()">+ adicionar pessoa</button></div>
<div class=sec><h2>NOVOS COLABORADORES</h2><p>liga o slide de boas-vindas (roteiro fixo: nome+equipe · primeiros dias · hobbies)</p>
<label style="display:flex;align-items:center;gap:8px;text-transform:none;font-size:13.5px;color:#fff">
<input type=checkbox name=tem_novos value=1 style="width:auto"{novos_chk}> temos novos colaboradores este mês</label>
<label>nomes (opcional, vira subtítulo do slide)</label><input name=novos_nomes value="{_e((novos or {}).get('nomes'))}" placeholder="ex.: Ana (Growth) · Pedro (Vendas)" style="max-width:600px"></div>
<div class=sec><h2>ORIENTAÇÕES & NOVIDADES</h2><p>cards de avisos internos, como no deck (2 por linha)</p>
<div id=orientacoes>{or_rows}</div><button type=button class=add onclick="addOrientacao()">+ adicionar aviso</button></div>
<div class=sec><h2>SLIDES EXTRAS</h2><p>slides livres no design do deck — ex.: um evento do mês que vem, um projeto novo.
Dê um título, escreva o conteúdo (cada linha vira um marcador) e anexe uma imagem se quiser; entram antes do fechamento</p>
<div id=extras>{sx_blocks}</div><button type=button class=add onclick="addExtra()">+ adicionar slide</button></div>
<button type=submit class=go>GERAR APRESENTAÇÃO →</button>
<p style="color:#777;font-size:12px">a apresentação abre na tela para conferência — de lá você exporta em PDF (Imprimir),
baixa o PPTX editável ou volta para ajustar o conteúdo sem perder nada.</p>
</form><script>{js}</script></body></html>"""


@router.get("/allhands", response_class=HTMLResponse)
def allhands_form(request: Request):
    s, redir = _require_admin(request)
    if redir:
        return redir
    return HTMLResponse(_form_page())


@router.post("/allhands/editar", response_class=HTMLResponse)
async def allhands_editar(request: Request):
    """'← ajustar conteúdo' da apresentação gerada: reabre o formulário com
    TUDO que foi digitado (16/07 — antes voltava vazio e perdia o trabalho)."""
    s, redir = _require_admin(request)
    if redir:
        return redir
    mes, destaques, novos, orientacoes, extras = await _parse_form(await request.form(**_FORM_LIMITS))
    return HTMLResponse(_form_page(mes, destaques, novos, orientacoes, extras))


# ---------------------------------------------------------------------------
# geração dos slides
# ---------------------------------------------------------------------------
def _fmt_brl0(v) -> str:
    return "—" if v is None else f"R$ {v:,.0f}".replace(",", ".")


_SLIDE_CSS = """
*{box-sizing:border-box}body{margin:0;background:#333;font-family:'Montserrat',sans-serif;color:#fff}
.slide{width:960px;height:540px;background:#0d0d0d;position:relative;overflow:hidden;margin:18px auto;box-shadow:0 8px 30px rgba(0,0,0,.55)}
.pad{padding:44px 52px}
.kicker{color:#ffc107;font-size:13px;font-weight:700;letter-spacing:.28em;text-transform:uppercase}
h1.t{font-size:30px;font-weight:800;letter-spacing:.06em;margin:6px 0 0;text-transform:uppercase}
.sub{color:#9a9a9a;font-size:12.5px;letter-spacing:.14em;text-transform:uppercase;margin-top:4px}
.card{background:#1a1a1a;border:1px solid #262626;border-radius:14px}
.amarelo{color:#ffc107}.num{font-weight:800;font-variant-numeric:tabular-nums}
.chipy{display:inline-block;background:#ffc107;color:#111;font-weight:800;font-size:12px;letter-spacing:.16em;padding:5px 14px;border-radius:4px}
table.tp{width:100%;border-collapse:collapse;font-size:14.5px}
table.tp td{padding:6px 4px;border-bottom:1px solid #262626}
table.tp td:last-child{text-align:right;font-weight:700}
table.tp tr.tot td{border-top:2px solid #ffc107;border-bottom:none;font-weight:800;color:#ffc107}
.rodape{position:absolute;left:52px;bottom:18px;color:#555;font-size:10.5px;letter-spacing:.2em;text-transform:uppercase}
.toolbar{position:sticky;top:0;background:#111;padding:10px 18px;display:flex;gap:10px;align-items:center;z-index:9;border-bottom:1px solid #2a2a2a}
.toolbar button{background:#ffc107;color:#111;border:none;border-radius:8px;font-weight:700;font-family:inherit;padding:9px 18px;cursor:pointer}
.toolbar a{color:#ffc107;font-size:13px}
@media print{body{background:#fff}.toolbar{display:none}.slide{margin:0;box-shadow:none;page-break-after:always}
@page{size:338.67mm 190.5mm;margin:0}}
"""


def _slide(inner: str, rodape: str, bg: str = "#0d0d0d") -> str:
    return (f"<div class=slide style='background:{bg}'>{inner}"
            f"<div class=rodape>{escape(rodape)}</div></div>")


_PLANOS_BARRAS = ["B1-START", "B2-TRACTION", "B3-SCALE", "B4-PLATINUM", "B5-ELITE",
                  "Assessoria (Renovação)"]


def _plano_barra(produto: str) -> str:
    """Normaliza o rótulo de produto do Pipedrive p/ o nome do deck."""
    p = (produto or "").upper()
    for pref, nome in (("B1", "B1-START"), ("B2", "B2-TRACTION"), ("B3", "B3-SCALE"),
                       ("B4", "B4-PLATINUM"), ("B5", "B5-ELITE")):
        if p.startswith(pref):
            return nome
    return "Assessoria (Renovação)"


def _vendas_plano_barras(vendas_plano: list[tuple[str, int, float]]) -> str:
    """Gráfico de barras horizontais 'Vendas por plano' — layout do deck
    (barras amarelas sobre grade, valor na ponta, eixo 0..max)."""
    cont: dict[str, int] = {n: 0 for n in _PLANOS_BARRAS}
    for produto, n, _v in vendas_plano:
        cont[_plano_barra(produto)] += n
    vmax = max(cont.values()) or 1
    step = max(1, round(vmax / 6))
    ticks = list(range(0, vmax + step, step))
    grade = ("repeating-linear-gradient(90deg,#2c2c2c 0,#2c2c2c 1px,transparent 1px,"
             f"transparent calc(100%/{max(1, len(ticks) - 1)}))")
    rows = ""
    for nome in _PLANOS_BARRAS:
        v = cont[nome]
        w = v / (ticks[-1] or 1) * 100
        barra = (f"<div style='height:24px;width:{max(w, 1.2):.1f}%;background:#ffc107;"
                 "border-radius:0 4px 4px 0'></div>") if v else ""
        rows += ("<div style='display:flex;align-items:center;gap:10px;margin:11px 0'>"
                 f"<div style='width:152px;text-align:right;font-size:12.5px;font-weight:600;line-height:1.2'>{escape(nome)}</div>"
                 f"<div style='flex:1;position:relative;background:{grade}'>"
                 "<div style='display:flex;align-items:center;gap:8px'>"
                 f"{barra}<span class=num style='font-size:14px'>{v}</span></div></div></div>")
    eixo = "".join(f"<span>{t}</span>" for t in ticks)
    return (f"<div class=card style='padding:20px 24px'>{rows}"
            f"<div style='display:flex;justify-content:space-between;margin:6px 0 0 162px;"
            f"font-size:10.5px;color:#777'>{eixo}</div></div>")


def _hidden_form(mes: dt.date, destaques: list[dict], novos: dict | None,
                 orientacoes: list[dict], extras: list[dict]) -> str:
    """Todo o conteúdo manual como campos ocultos — permite, NA página gerada,
    baixar o PPTX e voltar ao formulário sem redigitar nada (16/07)."""
    def _e(v):
        return escape(str(v or ""), quote=True)

    h = [f"<input type=hidden name=mes value='{mes.isoformat()}'>"]
    for dq in destaques:
        h += [f"<input type=hidden name=dq_tipo value=\"{_e(dq['tipo'])}\">",
              f"<input type=hidden name=dq_nome value=\"{_e(dq['nome'])}\">",
              f"<input type=hidden name=dq_cargo value=\"{_e(dq['cargo'])}\">",
              f"<input type=hidden name=dq_nivel value=\"{_e(dq.get('nivel'))}\">",
              f"<input type=hidden name=dq_foto_b64 value=\"{_e(dq.get('foto'))}\">"]
    if novos:
        h += ["<input type=hidden name=tem_novos value=1>",
              f"<input type=hidden name=novos_nomes value=\"{_e(novos.get('nomes'))}\">"]
    for o in orientacoes:
        h += [f"<input type=hidden name=or_icone value=\"{_e(o['icone'])}\">",
              f"<input type=hidden name=or_titulo value=\"{_e(o['titulo'])}\">",
              f"<input type=hidden name=or_texto value=\"{_e(o.get('texto'))}\">"]
    for ex in extras or []:
        h += [f"<input type=hidden name=sx_kicker value=\"{_e(ex.get('kicker'))}\">",
              f"<input type=hidden name=sx_titulo value=\"{_e(ex['titulo'])}\">",
              # textarea oculta preserva as QUEBRAS DE LINHA (viram marcadores)
              f"<textarea name=sx_texto style='display:none'>{escape(ex.get('texto') or '')}</textarea>",
              f"<input type=hidden name=sx_foto_b64 value=\"{_e(ex.get('foto'))}\">"]
    return "".join(h)


def _gerar_html(mes: dt.date, d: dict, destaques: list[dict], novos: dict | None,
                orientacoes: list[dict], extras: list[dict] | None = None) -> str:
    mes_nome = _MESES[mes.month - 1]
    prox = (mes.replace(day=28) + dt.timedelta(days=5)).replace(day=1)
    rodape = f"ALL HANDS · {mes_nome} {mes.year}"
    capa_b64 = _b64(_ASSETS / "allhands_capa.jpg", "image/jpeg")
    estrela_b64 = _b64(_ASSETS / "allhands_estrela.png", "image/png")
    slides = []

    # 1 — capa
    slides.append(_slide(
        f"<img src='{capa_b64}' style='position:absolute;inset:0;width:100%;height:100%;object-fit:cover'>"
        "<div style='position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;align-items:center'>"
        "<div style='font-size:64px;font-weight:800;letter-spacing:.30em;text-shadow:0 2px 24px rgba(0,0,0,.8)'>ALL HANDS</div>"
        f"<div style='font-size:19px;letter-spacing:.5em;color:#ffc107;margin-top:10px'>{mes_nome} / {mes.year}</div></div>", ""))

    # 2 — marketing & comercial: MESMO conteúdo do deck original (feedback
    # Otávio 15/07 — só Leads/Oportunidades/Vendas, Meta e Vendas por plano
    # em BARRAS; sem funil completo nem receita)
    fun = d["funil"]

    def item_funil(icone, rotulo, valor):
        return ("<div class=card style='display:flex;align-items:center;gap:14px;padding:13px 18px;margin:11px 0'>"
                f"<div style='width:42px;height:42px;border-radius:9px;background:#ffc107;display:flex;"
                f"align-items:center;justify-content:center;font-size:21px'>{icone}</div>"
                f"<div><div style='font-size:12px;font-weight:700;letter-spacing:.14em'>{rotulo}</div>"
                f"<div class=num style='font-size:23px'>{valor:,}</div></div></div>").replace(",", ".")

    slides.append(_slide(
        "<div class=pad>"
        "<div class=kicker>Marketing & Comercial</div>"
        "<div style='display:flex;gap:44px;margin-top:8px'>"
        "<div style='flex:1'>"
        "<div style='color:#ffc107;font-size:19px;font-weight:800;letter-spacing:.06em;"
        "border-bottom:1px solid #333;padding-bottom:8px'>FUNIL DE VENDAS</div>"
        + item_funil("👥", "TOTAL DE LEADS", fun[0])
        + item_funil("🎯", "OPORTUNIDADES", fun[4])
        + item_funil("🤝", "TOTAL DE VENDAS", d["bookings"])
        + "<div style='display:flex;margin-top:22px'>"
        "<div style='width:7px;background:#ffc107;border-radius:2px'></div>"
        "<div class=card style='flex:1;text-align:center;padding:14px;border-radius:0 14px 14px 0'>"
        "<div style='font-size:11px;color:#9a9a9a;letter-spacing:.22em'>META</div>"
        f"<div class=num style='font-size:34px'>{_fmt_brl0(d['meta_mes'])}</div></div></div>"
        "</div>"
        "<div style='flex:1.25'>"
        "<div style='color:#ffc107;font-size:19px;font-weight:800;letter-spacing:.06em;"
        "border-bottom:1px solid #333;padding-bottom:8px;margin-bottom:14px'>VENDAS POR PLANO</div>"
        + _vendas_plano_barras(d["vendas_plano"])
        + "</div></div></div>", rodape))

    # 3 — operação: clientes por plano
    novos_set = _PLANOS_NOVOS
    col_novos = [(p, n) for p, n in d["clientes_plano"] if any(k in p.lower() for k in novos_set)]
    col_ant = [(p, n) for p, n in d["clientes_plano"] if (p, n) not in col_novos]

    def coluna(titulo, itens):
        linhas = "".join(f"<tr><td>{escape(p)}</td><td>{n}</td></tr>" for p, n in itens[:9])
        tot = sum(n for _, n in itens)
        return (f"<div class=card style='flex:1;padding:16px 22px'>"
                f"<div class=sub style='margin-bottom:8px'>{titulo}</div>"
                f"<table class=tp><tr style='color:#9a9a9a;font-size:11px'><td>PLANO</td><td style='text-align:right'>CLIENTES</td></tr>"
                f"{linhas}<tr class=tot><td>Total</td><td>{tot}</td></tr></table></div>")

    slides.append(_slide(
        "<div class=pad><div class=kicker>Operação</div><h1 class=t>Clientes por plano</h1>"
        f"<div style='display:flex;align-items:center;gap:16px;margin:12px 0 14px'>"
        f"<span class='num amarelo' style='font-size:46px'>{d['base_ativa']}</span>"
        "<span class=sub>total geral de clientes ativos</span></div>"
        f"<div style='display:flex;gap:22px'>{coluna('Planos antigos', col_ant)}{coluna('Planos novos', col_novos)}</div>"
        "<div style='color:#777;font-size:10.5px;margin-top:10px'>fonte: lista Clientes Ativos (ClickUp), "
        "cliente com mais de um serviço conta em cada linha — gere a apresentação logo após o fechamento do mês "
        "(gerada muito depois, cartões já movidos p/ Cancelados saem da foto e subcontam)</div></div>",
        rodape))

    # 4 — saídas (churn), duas colunas novos × antigos como no deck
    sd_novos = [(p, n) for p, n in d["saidas_plano"] if any(k in p.lower() for k in _PLANOS_NOVOS)]
    sd_ant = [(p, n) for p, n in d["saidas_plano"] if (p, n) not in sd_novos]

    def col_saida(titulo, itens):
        linhas = "".join(f"<tr><td>{escape(p)}</td><td>{n}</td></tr>" for p, n in itens[:7])
        tot = sum(n for _, n in itens)
        return (f"<div class=card style='flex:1;padding:13px 18px'>"
                f"<div class=sub style='margin-bottom:6px'>{titulo}</div>"
                f"<table class=tp style='font-size:13px'>{linhas}"
                f"<tr class=tot><td>Total</td><td>{tot}</td></tr></table></div>")

    taxa_txt = f"{d['taxa_mes'] * 100:.1f}%".replace(".", ",") if d["taxa_mes"] is not None else "—"
    meta_ch = f"{(d['churn_meta'] or 0.05) * 100:.0f}%"
    nota_sp = (f"<div style='color:#777;font-size:11px;margin-top:10px'>+ {d['saidas_sem_plano']} saída(s) "
               "sem plano lançado na planilha de cancelamentos (fora das colunas — corrigir na planilha)</div>"
               if d.get("saidas_sem_plano") else "")
    slides.append(_slide(
        "<div class=pad><div class=kicker>Retenção</div><h1 class=t>Saídas de clientes (churn)</h1>"
        "<div style='display:flex;gap:22px;margin-top:16px'>"
        + col_saida("Planos antigos", sd_ant) + col_saida("Planos novos", sd_novos) +
        "<div style='flex:1;display:flex;flex-direction:column;gap:14px'>"
        f"<div class=card style='padding:18px;text-align:center'><div class='num' style='font-size:40px;color:#ff5555'>{taxa_txt}</div>"
        "<div class=sub>taxa de cancelamento do mês</div>"
        f"<div class='num' style='font-size:19px;color:#ff8a8a;margin-top:10px'>{_fmt_brl0(d.get('mrr_rec_perdido'))}</div>"
        "<div class=sub>faturamento recorrente perdido</div>"
        f"<div style='color:#777;font-size:10px;margin-top:6px'>régua: cancelados recorrentes ÷ clientes recorrentes ativos "
        f"({d.get('saidas_rec', 0)} de {d.get('base_rec', 0)}; cada cliente conta 1×) — B1/Start fora: semestral, não recorrente</div></div>"
        f"<div class=card style='padding:18px;text-align:center'><div class='num amarelo' style='font-size:40px'>{meta_ch}</div>"
        "<div class=sub>meta taxa de cancelamento</div></div></div></div>" + nota_sp + "</div>", rodape))

    # 5 — evolução da taxa de cancelamento
    serie = d["churn_serie"]
    barras = ""
    if serie:
        vmax = max(v for _, v in serie) or 1
        for nome, v in serie:
            h = max(8, v / vmax * 200)
            barras += (f"<div style='display:flex;flex-direction:column;align-items:center;gap:7px'>"
                       f"<div class=num style='font-size:14px'>{v * 100:.1f}%</div>".replace(".", ",")
                       + f"<div style='width:56px;height:{h:.0f}px;border-radius:7px 7px 0 0;"
                       "background:linear-gradient(180deg,#ffc107,#8a6a00)'></div>"
                       f"<div style='font-size:12px;color:#9a9a9a;letter-spacing:.12em'>{nome}</div></div>")
    periodo_ev = (f"{serie[0][0].lower()} a {mes_nome.lower()}" if serie else mes_nome.lower())
    slides.append(_slide(
        "<div class=pad><div class=kicker>Retenção</div><h1 class=t>Evolução da taxa de cancelamento</h1>"
        f"<div class=sub>últimos meses | {periodo_ev}</div>"
        f"<div style='display:flex;align-items:flex-end;justify-content:center;gap:26px;margin-top:34px'>{barras or '<div class=sub>série indisponível</div>'}</div>"
        "<div style='color:#777;font-size:10px;margin-top:14px;text-align:center'>série = realizado lançado na planilha de "
        "planejamento (régua da gestão) — pode diferir da taxa recorrente do slide anterior enquanto a planilha incluir B1</div></div>",
        rodape))

    # 6 — metas do próximo mês
    churn_meta_txt = f"{d['churn_meta'] * 100:.0f}%" if d["churn_meta"] is not None else "5%"
    slides.append(_slide(
        f"<div class=pad><div class=kicker>Metas {_MESES[prox.month - 1].title()}</div>"
        "<h1 class=t>Fechamentos & Retenção</h1>"
        "<div style='display:flex;gap:26px;margin-top:44px;justify-content:center'>"
        f"<div class=card style='padding:34px 44px;text-align:center'><div class='num amarelo' style='font-size:52px'>{_fmt_brl0(d['meta_prox'])}</div>"
        "<div class=sub style='margin-top:8px'>meta do mês — comercial</div></div>"
        f"<div class=card style='padding:34px 44px;text-align:center'><div class='num amarelo' style='font-size:52px'>{churn_meta_txt}</div>"
        "<div class=sub style='margin-top:8px'>meta taxa de cancelamento</div></div></div></div>", rodape))

    # 7/8 — promovidos & destaques (manuais)
    if destaques:
        slides.append(_slide(
            f"<div class=pad style='display:flex;flex-direction:column;justify-content:center;height:100%'>"
            f"<img src='{estrela_b64}' style='width:64px;margin-bottom:14px'>"
            "<div class=kicker>Promovidos & Destaques do mês</div>"
            "<h1 class=t style='font-size:38px'>Celebrando conquistas</h1>"
            "<div style='color:#bbb;font-size:15.5px;max-width:560px;margin-top:12px'>Um momento para parabenizar aqueles que "
            "demonstraram evolução e elevaram o padrão de excelência da nossa equipe.</div>"
            f"<div style='display:flex;gap:12px;margin-top:22px'><span class=chipy>DEDICAÇÃO</span>"
            f"<span class=chipy>RESULTADOS</span><span class=chipy>CULTURA</span></div></div>", rodape))
        for dq in destaques:
            foto = (f"<img src='{dq['foto']}' style='width:230px;height:280px;object-fit:cover;border-radius:12px'>"
                    if dq.get("foto") else
                    f"<div style='width:230px;height:280px;border-radius:12px;background:#1a1a1a;display:flex;"
                    f"align-items:center;justify-content:center'><img src='{estrela_b64}' style='width:74px'></div>")
            slides.append(_slide(
                "<div class=pad style='display:flex;gap:44px;align-items:center;height:100%'>"
                f"{foto}<div>"
                "<div class=kicker>Destaques & Promoções</div>"
                f"<div style='margin:14px 0'><span class=chipy>{escape(dq['tipo'])}</span></div>"
                f"<h1 class=t style='font-size:40px'>{escape(dq['nome'])}</h1>"
                f"<div style='color:#ffc107;font-size:16px;letter-spacing:.2em;text-transform:uppercase;margin-top:8px'>{escape(dq['cargo'])}</div>"
                + (f"<div class=sub style='margin-top:10px'>{escape(dq['nivel'])}</div>" if dq.get("nivel") else "")
                + "</div></div>", rodape))

    # 9 — novos colaboradores (manual) — layout do deck: faixa de boas-vindas
    # com ícone em quadrado amarelo + barra lateral; cards de pergunta com
    # ícone, título branco e traço amarelo
    if novos:
        sub_nomes = (f"<div style='color:#ffc107;font-size:14.5px;margin-top:10px'>{escape(novos['nomes'])}</div>"
                     if novos.get("nomes") else "")
        perguntas = "".join(
            "<div class=card style='flex:1;padding:20px 20px 16px'>"
            "<div style='display:flex;align-items:center;gap:9px;margin-bottom:12px'>"
            f"<div style='width:30px;height:30px;border-radius:7px;background:#ffc107;display:flex;"
            f"align-items:center;justify-content:center;font-size:15px'>{ic}</div>"
            f"<div style='font-weight:800;font-size:14.5px;letter-spacing:.06em'>{t}</div></div>"
            f"<div style='color:#bbb;font-size:13.5px;line-height:1.55'>{q}</div>"
            "<div style='width:64px;height:6px;background:#ffc107;border-radius:3px;margin-top:18px'></div></div>"
            for ic, t, q in (("🪪", "NOME + EQUIPE", "Qual seu nome e equipe que está trabalhando?"),
                             ("💬", "PRIMEIROS DIAS", "Como está sendo seus primeiros dias aqui conosco?"),
                             ("🚀", "HOBBIES", "O que gosta de fazer nas horas vagas?")))
        slides.append(_slide(
            "<div class=pad><div class=kicker>Apresentação de novos colaboradores</div>"
            "<div style='display:flex;margin-top:14px'>"
            "<div style='width:8px;background:#ffc107;border-radius:2px'></div>"
            "<div class=card style='flex:1;display:flex;align-items:center;gap:22px;"
            "padding:24px 30px;border-radius:0 14px 14px 0'>"
            "<div style='width:58px;height:58px;border-radius:12px;background:#ffc107;display:flex;"
            "align-items:center;justify-content:center;font-size:30px'>🤝</div>"
            "<div><h1 class=t style='font-size:34px;margin:0'>Sejam bem-vindos<br>ao time!</h1>"
            + sub_nomes + "</div></div></div>"
            f"<div style='display:flex;gap:20px;margin-top:26px'>{perguntas}</div></div>", rodape))

    # 10 — orientações & novidades (manual) — layout do deck: cards centrados,
    # ícone amarelo em círculo escuro no topo, título BRANCO, texto embaixo
    if orientacoes:
        n_or = len(orientacoes)
        largura = "300px" if n_or >= 3 else "340px"
        cards = "".join(
            f"<div class=card style='width:{largura};padding:30px 26px;text-align:center'>"
            "<div style='width:88px;height:88px;border-radius:50%;margin:0 auto 20px;"
            "background:radial-gradient(circle,#242424 0%,#161616 100%);display:flex;"
            f"align-items:center;justify-content:center;font-size:40px'>{escape(o['icone'])}</div>"
            f"<div style='font-weight:800;font-size:19px;letter-spacing:.05em;text-transform:uppercase'>{escape(o['titulo'])}</div>"
            + (f"<div style='color:#bbb;font-size:14px;line-height:1.55;margin-top:12px'>{escape(o['texto'])}</div>"
               if o.get("texto") else "")
            + "</div>"
            for o in orientacoes)
        slides.append(_slide(
            "<div class=pad style='height:100%;display:flex;flex-direction:column'>"
            "<div class=kicker>Convivência e organização do espaço</div>"
            "<h1 class=t>Orientações & Novidades</h1>"
            "<div style='flex:1;display:flex;align-items:center;justify-content:center;"
            f"gap:26px;flex-wrap:wrap;padding-bottom:20px'>{cards}</div></div>", rodape))

    # slides EXTRAS (manual, 16/07): conteúdo livre no design do deck — cada
    # linha do texto vira um marcador; imagem opcional à direita
    for ex in (extras or []):
        linhas_ex = [ln.strip() for ln in (ex.get("texto") or "").splitlines() if ln.strip()]
        bullets = "".join(
            "<div style='display:flex;gap:14px;align-items:flex-start;margin:13px 0'>"
            "<div style='width:8px;height:8px;border-radius:50%;background:#ffc107;margin-top:8px;flex-shrink:0'></div>"
            f"<div style='color:#ddd;font-size:16.5px;line-height:1.55'>{escape(ln)}</div></div>"
            for ln in linhas_ex)
        corpo = (f"<div class=card style='flex:1;padding:22px 28px'>{bullets}</div>" if bullets else "")
        # imagem SEM corte (Otávio 16/07: banner paisagem saía cortado no
        # enquadramento fixo) — mantém a proporção original dentro do limite
        img_ex = (f"<img src='{ex['foto']}' style='max-width:46%;max-height:360px;width:auto;height:auto;"
                  f"object-fit:contain;border-radius:14px;flex-shrink:0'>" if ex.get("foto") else "")
        slides.append(_slide(
            "<div class=pad style='height:100%;display:flex;flex-direction:column'>"
            f"<div class=kicker>{escape(ex.get('kicker') or 'Novidades')}</div>"
            f"<h1 class=t>{escape(ex['titulo'])}</h1>"
            f"<div style='flex:1;display:flex;gap:30px;align-items:center;margin-top:14px'>{corpo}{img_ex}</div></div>",
            rodape))

    # 11 — fechamento
    slides.append(_slide(
        "<div style='position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;align-items:center;"
        "background:radial-gradient(ellipse at center,#1b1b1b 0%,#000 75%)'>"
        f"<img src='{estrela_b64}' style='width:70px;margin-bottom:20px'>"
        "<div style='font-size:46px;font-weight:800;letter-spacing:.14em'>ÓTIMO MÊS</div>"
        "<div style='font-size:46px;font-weight:800;letter-spacing:.14em;color:#ffc107'>PARA TODOS NÓS</div>"
        f"<div class=sub style='margin-top:16px'>{rodape}</div></div>", ""))

    oculto = _hidden_form(mes, destaques, novos, orientacoes, extras or [])
    return (f"<!doctype html><html lang=pt-br><head><meta charset=utf-8><title>All Hands · {mes_nome.title()} {mes.year}</title>"
            "<link href='https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;700;800&display=swap' rel=stylesheet>"
            f"<style>{_SLIDE_CSS}</style></head><body>"
            # toolbar: conferir na tela e SÓ ENTÃO exportar (PDF ou PPTX) ou
            # voltar a ajustar — o form oculto carrega tudo que foi digitado
            # multipart evita o inchaço do percent-encoding no base64 das fotos
            "<div class=toolbar><form method=post action='/allhands/editar' "
            "enctype='multipart/form-data' style='display:contents'>"
            + oculto +
            "<button type=button onclick='window.print()'>Exportar / Imprimir (PDF)</button>"
            "<button type=submit formaction='/allhands/pptx' "
            "style='background:#1a1a1a;color:#ffc107;border:1px solid #ffc107'>Baixar PPTX ↓</button>"
            "<button type=submit style='background:none;border:none;color:#ffc107;cursor:pointer;"
            "font-size:13px;font-family:inherit;padding:0 6px'>← ajustar conteúdo</button>"
            "</form><a href='/'>central</a>"
            "<span style='color:#777;font-size:12px'>PDF: orientação paisagem, 1 página por slide · "
            "PPTX: arquivo editável no PowerPoint · ajustar conteúdo mantém tudo preenchido</span></div>"
            + "".join(slides) + "</body></html>")


# o form oculto da página gerada devolve as FOTOS como campos de texto base64
# (p/ reeditar/baixar PPTX sem redigitar) — o limite padrão do Starlette é 1MB
# por campo e estourava com foto real ('Field exceeded maximum size of 1024KB',
# Otávio 16/07). 32MB cobre a maior foto aceita (8MB → ~10,7MB em base64).
_FORM_LIMITS = {"max_part_size": 32 * 1024 * 1024, "max_fields": 2000}


async def _parse_form(form) -> tuple:
    """Conteúdo manual do formulário — compartilhado entre a geração HTML e a
    exportação PPTX (mesmos campos, mesmos slides)."""
    try:
        mes = dt.date.fromisoformat(str(form.get("mes")))
    except (TypeError, ValueError):
        mes = _mes_fechado_default()

    destaques = []
    tipos = form.getlist("dq_tipo")
    nomes = form.getlist("dq_nome")
    cargos = form.getlist("dq_cargo")
    niveis = form.getlist("dq_nivel")
    fotos = form.getlist("dq_foto")
    fotos_b64 = form.getlist("dq_foto_b64")  # foto mantida de edição anterior
    for i, nome in enumerate(nomes):
        if not (nome or "").strip():
            continue
        foto_b64 = None
        if i < len(fotos) and getattr(fotos[i], "filename", ""):
            raw = await fotos[i].read()
            if raw and len(raw) < 8_000_000:
                mime = fotos[i].content_type or "image/jpeg"
                foto_b64 = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
        if foto_b64 is None and i < len(fotos_b64) and str(fotos_b64[i]).startswith("data:"):
            foto_b64 = str(fotos_b64[i])
        destaques.append({"tipo": (tipos[i] if i < len(tipos) else "DESTAQUE").strip() or "DESTAQUE",
                          "nome": nome.strip(),
                          "cargo": (cargos[i] if i < len(cargos) else "").strip(),
                          "nivel": (niveis[i] if i < len(niveis) else "").strip(),
                          "foto": foto_b64})

    novos = None
    if form.get("tem_novos"):
        novos = {"nomes": str(form.get("novos_nomes") or "").strip()}

    orientacoes = []
    for ic, t, tx in zip(form.getlist("or_icone"), form.getlist("or_titulo"), form.getlist("or_texto")):
        if (t or "").strip():
            orientacoes.append({"icone": (ic or "").strip() or "📌",
                                "titulo": t.strip(), "texto": (tx or "").strip()})

    # slides EXTRAS (Otávio 16/07): conteúdo livre — título + linhas + imagem
    extras = []
    sx_k, sx_t = form.getlist("sx_kicker"), form.getlist("sx_titulo")
    sx_x, sx_f = form.getlist("sx_texto"), form.getlist("sx_foto")
    for i, tit in enumerate(sx_t):
        if not (tit or "").strip():
            continue
        foto_b64 = None
        if i < len(sx_f) and getattr(sx_f[i], "filename", ""):
            raw = await sx_f[i].read()
            if raw and len(raw) < 8_000_000:
                mime = sx_f[i].content_type or "image/jpeg"
                foto_b64 = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
        sx_fb = form.getlist("sx_foto_b64")
        if foto_b64 is None and i < len(sx_fb) and str(sx_fb[i]).startswith("data:"):
            foto_b64 = str(sx_fb[i])
        extras.append({"kicker": (sx_k[i] if i < len(sx_k) else "").strip(),
                       "titulo": tit.strip(),
                       "texto": (sx_x[i] if i < len(sx_x) else "").strip(),
                       "foto": foto_b64})
    return mes, destaques, novos, orientacoes, extras


@router.post("/allhands/gerar", response_class=HTMLResponse)
async def allhands_gerar(request: Request):
    s, redir = _require_admin(request)
    if redir:
        return redir
    mes, destaques, novos, orientacoes, extras = await _parse_form(await request.form(**_FORM_LIMITS))
    A = _deps()
    with A._conn() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'generate',%s)",
                        (s[0], f"allhands/{mes:%Y-%m}"))
        dados = _dados_mes(c, mes)
    return HTMLResponse(_gerar_html(mes, dados, destaques, novos, orientacoes, extras))


@router.post("/allhands/pptx")
async def allhands_pptx(request: Request):
    """Exportação PPTX nativa (Otávio 16/07) — mesmo formulário, mesmos dados;
    o arquivo sai editável no PowerPoint."""
    s, redir = _require_admin(request)
    if redir:
        return redir
    mes, destaques, novos, orientacoes, extras = await _parse_form(await request.form(**_FORM_LIMITS))
    A = _deps()
    with A._conn() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,'generate',%s)",
                        (s[0], f"allhands-pptx/{mes:%Y-%m}"))
        dados = _dados_mes(c, mes)
    from fastapi.responses import Response
    from .allhands_pptx import gerar_pptx
    raw = gerar_pptx(mes, dados, destaques, novos, orientacoes, extras)
    return Response(
        raw, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="allhands_{mes:%Y-%m}.pptx"'})
