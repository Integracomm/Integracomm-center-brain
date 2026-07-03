"""Endpoints + página do RELATÓRIO MENSAL DE ASSESSORIA por cliente.

Camada fina sobre app.reports: autentica (mesma sessão do painel), audita e
serializa. A página /growth/report é uma casca leve — busca o JSON via fetch
(gera sob demanda com loading) e tem CSS de impressão (window.print = export).
"""
from __future__ import annotations

import re
from html import escape

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import reports as R

router = APIRouter()

_MONTH_RE = re.compile(r"^20\d\d-(0[1-9]|1[0-2])$")


def _deps():
    """Import tardio de api.py (evita import circular: api inclui este router)."""
    from . import api as A
    return A


def _month_or_400(month: str | None) -> str:
    if not month:
        return R.default_ref_month()
    if not _MONTH_RE.match(month):
        raise HTTPException(status_code=400, detail="month deve ser YYYY-MM")
    return month


@router.get("/api/accounts/{account_id}/report")
def api_account_report(account_id: str, request: Request, month: str = Query(None)):
    """Gera (sob demanda) e retorna o relatório mensal da conta."""
    A = _deps()
    user, _role = A._require_api(request)
    ref = _month_or_400(month)
    with A._conn() as c:
        try:
            rep = R.build_report(c, account_id, ref, generated_by=user)
        except LookupError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope, account_id) VALUES (%s,%s,%s,%s)",
                        (user, "report_generate", f"assessoria/{ref}", account_id))
    return rep


@router.get("/api/reports/sheet-data")
def api_sheet_data(request: Request, account_id: str = Query(...)):
    """Dados crus da planilha individual da conta (suporte/diagnóstico de match)."""
    A = _deps()
    A._require_api(request)
    with A._conn() as c, c.cursor() as cur:
        cur.execute("SELECT name FROM accounts WHERE id=%s", (account_id,))
        row = cur.fetchone()
    if not row:
        return JSONResponse({"error": "conta não encontrada"}, status_code=404)
    from .sources import nps_sheets as NPS
    master, note = NPS.find_master_row(row[0])
    if not master or not master["sheet_id"]:
        return {"account_name": row[0], "match_note": note, "master_row": master, "sheet": None}
    try:
        parsed = NPS.fetch_individual(master["sheet_id"], master["gid"])
    except Exception as e:  # noqa: BLE001 — diagnóstico devolve o erro, não 500
        return {"account_name": row[0], "match_note": note, "master_row": master,
                "sheet": None, "error": type(e).__name__}
    return {"account_name": row[0], "match_note": note, "master_row": master, "sheet": parsed}


@router.post("/api/reports/batch")
def api_reports_batch(request: Request, payload: dict = Body(...)):
    """Gera relatórios p/ várias contas: {account_ids: [uuid...], month?: YYYY-MM}.
    Falha de UMA conta não derruba o lote — vira item com status=erro."""
    A = _deps()
    user, _role = A._require_api(request)
    ids = payload.get("account_ids") or []
    if not isinstance(ids, list) or not ids:
        return JSONResponse({"error": "account_ids (lista) é obrigatório"}, status_code=400)
    if len(ids) > 50:
        return JSONResponse({"error": "máximo de 50 contas por lote"}, status_code=400)
    ref = _month_or_400(payload.get("month"))
    out = []
    with A._conn() as c:
        for aid in ids:
            try:
                rep = R.build_report(c, str(aid), ref, generated_by=user)
                out.append({"account_id": str(aid), "account_name": rep["header"]["account_name"],
                            "report_id": rep["report_id"], "status": "ok"})
            except Exception as e:  # noqa: BLE001 — lote resiliente; erro vai ao item
                out.append({"account_id": str(aid), "status": "erro", "error": type(e).__name__})
        with c.cursor() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, scope) VALUES (%s,%s,%s)",
                        (user, "report_batch", f"assessoria/{ref}:{len(ids)} contas"))
    return {"month": ref, "reports": out}


@router.get("/api/reports/{report_id}")
def api_report_get(report_id: str, request: Request):
    """Recupera um relatório já gerado (sem re-gerar)."""
    A = _deps()
    A._require_api(request)
    with A._conn() as c:
        rep = R.load_report(c, report_id)
    if not rep:
        return JSONResponse({"error": "relatório não encontrado"}, status_code=404)
    return rep


# --------------------------------------------------------------------------
# Página /growth/report — casca com loading; imprime/exporta via window.print
# --------------------------------------------------------------------------
@router.get("/growth/report", response_class=HTMLResponse)
def report_page(request: Request, account_id: str = Query(None),
                report_id: str = Query(None), month: str = Query(None)):
    A = _deps()
    s = A._session(request)
    if not s:
        return RedirectResponse("/login", status_code=302)
    if not account_id and not report_id:
        return RedirectResponse("/growth?view=relatorios", status_code=302)
    ref = _month_or_400(month)
    src = (f"/api/reports/{escape(report_id)}" if report_id
           else f"/api/accounts/{escape(account_id)}/report?month={ref}")
    html = _PAGE.replace("__TOKENS__", A._tokens_css()).replace("__SRC__", src)
    return HTMLResponse(html)


_PAGE = r"""<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Relatório de Assessoria — Integracomm IA</title>
<link rel=preconnect href="https://fonts.googleapis.com"><link rel=preconnect href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Poppins:wght@500;600;700&display=swap" rel=stylesheet>
<style>
__TOKENS__
*{box-sizing:border-box}
body{margin:0;background:var(--bg-app);color:var(--text);font-family:var(--font-body);font-size:var(--fs-base);-webkit-font-smoothing:antialiased}
a{color:inherit}
.wrap{max-width:860px;margin:0 auto;padding:26px 28px 60px}
.topbar{display:flex;align-items:center;gap:12px;margin-bottom:22px}
.topbar .back{font-size:var(--fs-sm);color:var(--text-muted);text-decoration:none}
.topbar .back:hover{color:var(--text)}
.topbar .actions{margin-left:auto;display:flex;gap:8px}
.btn{cursor:pointer;background:var(--brand);color:var(--brand-ink);border:none;border-radius:var(--radius-sm);font-family:var(--font-body);font-weight:600;font-size:var(--fs-sm);padding:8px 14px}
.btn.ghost{background:var(--surface-3);color:var(--text-2);border:1px solid var(--border-strong)}
h1{font-family:var(--font-display);font-weight:700;font-size:var(--fs-h1);letter-spacing:var(--tracking-tight);margin:0}
.sub{font-size:var(--fs-sm);color:var(--text-muted);margin-top:6px}
.hgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:16px}
.hcell{background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:12px 14px}
.hcell .l{font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:var(--tracking-label)}
.hcell .v{font-family:var(--font-display);font-weight:600;font-size:15px;margin-top:5px;word-break:break-word}
section{margin-top:var(--space-8)}
h2{font-family:var(--font-display);font-weight:600;font-size:var(--fs-lg);margin:0 0 4px}
.secsub{font-size:var(--fs-sm);color:var(--text-muted);margin:0 0 12px}
.card{background:var(--surface-1);border:1px solid var(--border-mid);border-radius:var(--radius-md);padding:16px 18px}
.chip{display:inline-flex;align-items:center;gap:6px;background:color-mix(in srgb,var(--c) 14%,transparent);color:var(--c);border:1px solid color-mix(in srgb,var(--c) 40%,transparent);border-radius:999px;font-size:var(--fs-xs);font-weight:var(--fw-semibold);padding:2px 10px;white-space:nowrap}
.chip .dot{width:6px;height:6px;border-radius:50%;background:var(--c)}
table{width:100%;border-collapse:collapse;font-size:var(--fs-sm)}
th{text-align:left;color:var(--text-muted);font-size:var(--fs-2xs);text-transform:uppercase;letter-spacing:var(--tracking-label);font-weight:var(--fw-semibold);padding:7px 8px;border-bottom:1px solid var(--border-strong)}
td{padding:8px;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums}
th.num,td.num{text-align:right}
tr.total td{font-weight:700;border-top:1px solid var(--border-strong)}
.pos{color:var(--status-baixo)} .neg{color:var(--status-critico)}
.cnpj-h{font-family:var(--font-display);font-weight:600;font-size:var(--fs-md);margin:14px 0 8px}
.cnpj-h:first-child{margin-top:0}
.warn{background:color-mix(in srgb,var(--status-medio) 8%,transparent);border:1px solid color-mix(in srgb,var(--status-medio) 30%,transparent);border-radius:var(--radius-sm);color:var(--text-2);font-size:var(--fs-sm);padding:9px 12px;line-height:1.5}
.grp-h{font-size:var(--fs-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:var(--tracking-label);margin:14px 0 6px}
.grp-h:first-child{margin-top:0}
.task{display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid var(--border);font-size:var(--fs-sm)}
.task .d{color:var(--text-faint);white-space:nowrap}
.motivos li{font-size:var(--fs-sm);color:var(--text-2);line-height:1.6}
.obs{font-size:var(--fs-md);line-height:1.7;color:var(--text-2)}
.sug{display:flex;gap:10px;align-items:flex-start;padding:9px 0;border-top:1px solid var(--border);font-size:var(--fs-sm);line-height:1.55;color:var(--text-2)}
.sug:first-child{border-top:none;padding-top:0}
.sug .b{color:var(--brand);flex-shrink:0;font-weight:700}
.meta{font-size:var(--fs-xs);color:var(--text-faint);margin-top:22px;line-height:1.6}
#loading{display:flex;flex-direction:column;align-items:center;gap:14px;padding:90px 0;color:var(--text-muted)}
.spin{width:26px;height:26px;border-radius:50%;border:3px solid var(--border-strong);border-top-color:var(--brand);animation:sp 0.9s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
@media print{
  body{background:#fff;color:#111}
  .topbar,.no-print{display:none!important}
  .wrap{max-width:none;padding:0}
  .card,.hcell{background:#fff;border-color:#ccc;break-inside:avoid}
  .hcell .l,.secsub,.grp-h,th{color:#555}
  .obs,.sug,.motivos li,.task,td{color:#111}
  .task .d{color:#555}
  td,.task{border-color:#ddd}
  .chip{border-color:#999;color:#111;background:none}
  .warn{border-color:#bbb;color:#333;background:none}
  .sub{color:#444}
  section{margin-top:20px}
}
</style></head><body>
<div class=wrap>
  <div class=topbar>
    <a class=back href="/growth?view=relatorios">← voltar aos relatórios</a>
    <div class=actions>
      <button class="btn ghost" onclick="location.reload()">Regerar</button>
      <button class=btn onclick="window.print()">Exportar / Imprimir</button>
    </div>
  </div>
  <div id=loading><div class=spin></div><div>Gerando relatório — buscando planilha, atividades e sinais…</div></div>
  <div id=report style="display:none"></div>
</div>
<script>
var BAND={critico:'--status-critico',alto:'--status-alto',medio:'--status-medio',baixo:'--status-baixo',sem_dados:'--status-semdados'};
var TOM={'crítico':'--status-critico','negativo':'--status-alto','atenção':'--status-medio','estável':'--status-baixo','sem dados':'--status-semdados'};
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function fmtD(s){var m=String(s||'').match(/^(\d{4})-(\d{2})-(\d{2})/);return m?(m[3]+'-'+m[2]+'-'+m[1]):(s?String(s):'—');}
function brl(v){if(v==null)return '<span style="color:var(--text-faint)">—</span>';
  return 'R$ '+v.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});}
function delta(r){if(r.delta_abs==null)return '—';
  var cls=r.delta_abs>=0?'pos':'neg', sign=r.delta_abs>=0?'+':'−';
  var pct=r.delta_pct==null?'':' ('+sign+Math.abs(r.delta_pct).toFixed(1)+'%)';
  return '<span class="'+cls+'">'+sign+'R$ '+Math.abs(r.delta_abs).toLocaleString('pt-BR',{minimumFractionDigits:2})+pct+'</span>';}
function chip(label,varname){return '<span class=chip style="--c:var('+varname+')"><span class=dot></span>'+esc(label)+'</span>';}

function render(d){
  var h=d.header, f=d.faturamento, a=d.atividades, s=d.saude, o=d.observacoes;
  var html='';
  html+='<h1>Relatório de Assessoria</h1>';
  html+='<div class=sub>'+esc(h.cliente)+' · mês de referência: <b style="color:var(--text)">'+esc(h.reference_month_label)+'</b></div>';
  var temSquad=d.equipe_squad&&d.equipe_squad.membros.length;
  html+='<div class=hgrid>'
      +'<div class=hcell><div class=l>Cliente</div><div class=v>'+esc(h.cliente)+'</div></div>'
      +'<div class=hcell><div class=l>Plano</div><div class=v>'+esc(h.plano||'—')+'</div></div>'
      // "GC responsável" só como fallback quando a composição do squad não foi encontrada
      +(temSquad?'':'<div class=hcell><div class=l>GC responsável</div><div class=v>'+esc(h.gc||'—')+'</div></div>')
      +'<div class=hcell><div class=l>Equipe</div><div class=v>'+esc(h.equipe||'—')+'</div></div>'
      +'</div>';
  if(temSquad){
    var mm=d.equipe_squad.membros.map(function(x){return '<span style="white-space:nowrap"><span style="color:var(--text-muted)">'+esc(x.funcao)+':</span> '+esc(x.nome)+'</span>';}).join('<span style="color:var(--text-faint)"> · </span>');
    html+='<div class=hcell style="margin-top:10px"><div class=l>Equipe que atende (squad '+esc(d.equipe_squad.squad)+')</div>'
        +'<div style="font-size:var(--fs-sm);line-height:1.8;margin-top:6px">'+mm+'</div></div>';
  }

  // --- faturamento ---
  html+='<section><h2>Faturamento nos marketplaces</h2>'
      +'<p class=secsub>'+esc(h.reference_month_label)+' vs '+esc(h.prev_month_label)+', por CNPJ</p><div class=card>';
  if(!f.available){ html+='<div class=warn>'+esc(f.aviso||'Planilha não disponível')+'</div>'; }
  else if(!f.comparativo.length){ html+='<div class=warn>'+esc(f.aviso||'Sem faturamento lançado no período.')+'</div>'; }
  else{
    f.comparativo.forEach(function(b,i){
      html+='<div class=cnpj-h>'+(b.cnpj?('CNPJ: '+esc(b.cnpj)):(f.comparativo.length>1?('CNPJ '+(i+1)):'Faturamento'))+'</div>';
      html+='<table><tr><th>Marketplace</th><th class=num>'+esc(h.prev_month_label)+'</th><th class=num>'+esc(h.reference_month_label)+'</th><th class=num>Variação</th></tr>';
      b.rows.forEach(function(r){
        html+='<tr><td>'+esc(r.marketplace)+'</td><td class=num>'+brl(r.prev)+'</td><td class=num>'+brl(r.ref)+'</td><td class=num>'+delta(r)+'</td></tr>';
      });
      var td=b.total_ref-b.total_prev, tp=b.total_prev?td/b.total_prev*100:null;
      var totRef=b.ref_lancado?brl(b.total_ref):brl(null);
      var totVar=b.ref_lancado?delta({delta_abs:td,delta_pct:tp}):'—';
      html+='<tr class=total><td>Total</td><td class=num>'+brl(b.total_prev)+'</td><td class=num>'+totRef+'</td><td class=num>'+totVar+'</td></tr></table>';
    });
    if(f.aviso) html+='<div class=warn style="margin-top:10px">'+esc(f.aviso)+'</div>';
  }
  if(f.match_note && f.match_note.indexOf('exato')<0) html+='<div class=meta>match da planilha: '+esc(f.match_note)+'</div>';
  html+='</div></section>';

  // --- atividades ---
  html+='<section><h2>Atividades realizadas</h2><p class=secsub>'+a.total+' tarefas concluídas no período (fonte: '+esc(a.source)+')</p><div class=card>';
  if(a.aviso) html+='<div class=warn style="margin-bottom:10px">'+esc(a.aviso)+'</div>';
  if(!a.grupos.length) html+='<div style="color:var(--text-muted);font-size:var(--fs-sm)">Nenhuma atividade concluída registrada no período.</div>';
  a.grupos.forEach(function(g){
    html+='<div class=grp-h>'+esc(g.categoria)+' ('+g.tarefas.length+')</div>';
    g.tarefas.forEach(function(t){
      html+='<div class=task><span>'+esc(t.nome)+(t.responsavel&&g.categoria!==t.responsavel?' <span style="color:var(--text-faint)">· '+esc(t.responsavel)+'</span>':'')+'</span><span class=d>'+fmtD(t.concluida_em)+'</span></div>';
    });
  });
  html+='</div></section>';

  // --- próximas atividades previstas ---
  var px=a.proximas||{tasks:[]};
  html+='<section><h2>Próximas atividades previstas</h2><p class=secsub>em aberto com vencimento a partir de '+(px.geradas_em?fmtD(px.geradas_em):'hoje')+' — insumo para a reunião com o cliente</p><div class=card>';
  if(px.aviso) html+='<div class=warn style="margin-bottom:10px">'+esc(px.aviso)+'</div>';
  if(!px.tasks.length) html+='<div style="color:var(--text-muted);font-size:var(--fs-sm)">Nenhuma atividade futura com vencimento agendado no ClickUp.</div>';
  px.tasks.forEach(function(t){
    html+='<div class=task><span>'+esc(t.nome)+(t.responsavel?' <span style="color:var(--text-faint)">· '+esc(t.responsavel)+'</span>':'')
        +(t.status?' <span style="color:var(--text-faint)">· '+esc(t.status)+'</span>':'')
        +'</span><span class=d>vence '+fmtD(t.vence_em)+'</span></div>';
  });
  html+='</div></section>';

  // --- saúde ---
  html+='<section><h2>Saúde do relacionamento</h2><p class=secsub>score do agente de Growth + tom das conversas</p><div class=card>';
  html+='<div style="display:flex;gap:26px;flex-wrap:wrap;align-items:center">';
  html+='<div><div class=grp-h style="margin:0 0 4px">Score</div><span style="font-family:var(--font-display);font-weight:700;font-size:30px">'+(s.score!=null&&s.evaluable?s.score.toFixed(1):'s/ dados')+'</span></div>';
  html+='<div><div class=grp-h style="margin:0 0 6px">Faixa</div>'+chip(s.faixa||'sem dados',BAND[s.faixa]||'--status-semdados')+'</div>';
  html+='<div><div class=grp-h style="margin:0 0 4px">Estágio</div><div style="font-size:var(--fs-md)">'+esc(s.estagio||'—')+'</div></div>';
  html+='<div><div class=grp-h style="margin:0 0 4px">Trajetória</div><div style="font-size:var(--fs-md)">'+esc(s.trajetoria||'—')+'</div></div>';
  html+='<div><div class=grp-h style="margin:0 0 6px">Tom das conversas</div>'+chip(s.tom.rotulo,TOM[s.tom.rotulo]||'--status-semdados')+'</div>';
  if(s.exec_score!=null) html+='<div><div class=grp-h style="margin:0 0 4px">Execução (ClickUp)</div><div style="font-size:var(--fs-md)">'+s.exec_score.toFixed(0)+'/100</div></div>';
  html+='</div>';
  if(s.motivos.length){ html+='<div class=grp-h style="margin-top:16px">Principais motivos do score</div><ul class=motivos style="margin:4px 0 0;padding-left:18px">';
    s.motivos.forEach(function(m){html+='<li>'+esc(m)+'</li>';}); html+='</ul>'; }
  html+='<div class=meta>'+esc(s.tom.detalhe)+(s.score_computado_em?' · score computado em '+fmtD(s.score_computado_em):'')
      +(s.sinais_do_mes?'':' · sinais mais recentes disponíveis (sem série completa dentro do mês)')+'</div>';
  html+='</div></section>';

  // --- observações ---
  html+='<section><h2>Observações e próximos passos</h2><p class=secsub>síntese sobre os dados acima + sugestões para o GC</p><div class=card>';
  html+='<div class=obs>'+esc(o.texto)+'</div>';
  if(o.sugestoes.length){ html+='<div class=grp-h style="margin-top:16px">Sugestões de ação</div>';
    o.sugestoes.forEach(function(x){html+='<div class=sug><span class=b>→</span><span>'+esc(x)+'</span></div>';}); }
  html+='<div class=meta>'+esc(o.gerado_por)+'</div>';
  html+='</div></section>';

  html+='<p class=meta>Relatório '+esc(d.report_id||'')+' · gerado em '+fmtD(d.generated_at)+' '+esc((d.generated_at||'').slice(11,16))
      +(d.generated_by?(' por '+esc(d.generated_by)):'')+' · Integracomm IA — dados derivados; a decisão é sempre do gestor.</p>';
  document.getElementById('report').innerHTML=html;
  document.getElementById('loading').style.display='none';
  document.getElementById('report').style.display='';
  document.title='Relatório '+h.cliente+' — '+h.reference_month_label;
}
fetch('__SRC__').then(function(r){return r.json().then(function(j){return [r.ok,j];});})
 .then(function(x){ if(!x[0]) throw new Error(x[1].error||x[1].detail||'falha'); render(x[1]); })
 .catch(function(e){ document.getElementById('loading').innerHTML=
   '<div class=warn>Falha ao gerar o relatório: '+esc(e.message)+'</div>'; });
</script>
</body></html>"""
