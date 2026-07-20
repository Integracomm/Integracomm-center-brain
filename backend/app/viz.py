"""Helpers VISUAIS compartilhados (Redesenho Parte A, 17/07) — tabela → visual
onde o dado é comparação/proporção/matriz, no design system (design-tokens).

Regras seguidas: rótulo de VALOR sempre visível (não só hover); cor + rótulo
(acessível a daltônicos); 1 ideia por visual; nada de pizza/3D. São divs/CSS
(mesma linguagem das barras já usadas em Vendas por plano/All Hands) — nenhuma
biblioteca nova. A tabela original, quando substituída, vai para um <details>
'ver tabela completa' logo abaixo: NENHUM dado some.
"""
from __future__ import annotations

from html import escape


def _fmt_default(v) -> str:
    return f"{v:,.0f}".replace(",", ".")


def barras_h(itens: list[tuple], fmt=None, cor: str = "var(--brand)",
             cores: list[str] | None = None, largura_rotulo: int = 170,
             largura_valor: int = 120) -> str:
    """Barras HORIZONTAIS ordenadas (comparar categorias): itens =
    [(rotulo, valor, sublabel|None)]; ordem = a passada pelo chamador.
    Layout em 3 colunas FIXAS — rótulo | trilha da barra | valor+sublabel —
    p/ o valor NUNCA sair da área do gráfico (correção 20/07)."""
    fmt = fmt or _fmt_default
    vals = [v for _r, v, *_ in itens if v is not None]
    vmax = max(vals) if vals else 1
    rows = ""
    for i, item in enumerate(itens):
        rot, v = item[0], item[1]
        sub = item[2] if len(item) > 2 and item[2] else ""
        c = (cores[i] if cores and i < len(cores) else cor)
        w = (v / vmax * 100) if (v and vmax) else 0
        sub_html = (f"<div style='font-size:var(--fs-2xs);color:var(--text-muted);line-height:1.3'>"
                    f"{escape(str(sub))}</div>" if sub else "")
        rows += (
            "<div style='display:flex;align-items:center;gap:10px;margin:8px 0'>"
            f"<div style='width:{largura_rotulo}px;flex-shrink:0;text-align:right;font-size:var(--fs-sm);"
            f"line-height:1.25'>{escape(str(rot))}</div>"
            "<div style='flex:1;min-width:60px;height:18px;background:var(--surface-3);"
            "border-radius:4px;overflow:hidden'>"
            f"<div style='height:100%;width:{max(w, 1.2):.1f}%;background:{c};"
            "border-radius:4px 0 0 4px' title='" + escape(str(rot)) + "'></div></div>"
            f"<div style='width:{largura_valor}px;flex-shrink:0'>"
            f"<div style='font-variant-numeric:tabular-nums;font-size:var(--fs-sm);font-weight:600'>"
            f"{fmt(v) if v is not None else '—'}</div>{sub_html}</div>"
            "</div>")
    return f"<div>{rows or '<span class=note>sem dados</span>'}</div>"


def empilhada(itens: list[tuple], segmentos: list[tuple[str, str]],
              largura_rotulo: int = 170) -> str:
    """Barra EMPILHADA por categoria (proporção de um todo): itens =
    [(rotulo, {seg: valor})]; segmentos = [(nome, cor)] na ordem de empilhar.
    Cada fatia mostra o % quando cabe; legenda com cor+nome (acessível)."""
    legenda = "".join(
        f"<span style='display:inline-flex;align-items:center;gap:5px;margin-right:14px;"
        f"font-size:var(--fs-2xs);color:var(--text-muted)'>"
        f"<span style='width:10px;height:10px;border-radius:3px;background:{c};display:inline-block'></span>"
        f"{escape(nome)}</span>" for nome, c in segmentos)
    rows = ""
    for rot, vals in itens:
        total = sum(vals.get(n, 0) for n, _c in segmentos) or 1
        fatias = ""
        for nome, c in segmentos:
            v = vals.get(nome, 0)
            if not v:
                continue
            pct = v / total * 100
            txt = (f"<span style='font-size:10.5px;font-weight:700;color:var(--brand-ink);"
                   f"mix-blend-mode:normal'>{pct:.0f}%</span>" if pct >= 12 else "")
            fatias += (f"<div title='{escape(nome)}: {v} ({pct:.0f}%)' "
                       f"style='width:{pct:.1f}%;background:{c};display:flex;align-items:center;"
                       f"justify-content:center;overflow:hidden'>{txt}</div>")
        rows += (
            "<div style='display:flex;align-items:center;gap:10px;margin:8px 0'>"
            f"<div style='width:{largura_rotulo}px;flex-shrink:0;text-align:right;"
            f"font-size:var(--fs-sm)'>{escape(str(rot))}</div>"
            f"<div style='flex:1;min-width:60px;display:flex;height:20px;border-radius:4px;overflow:hidden;"
            f"background:var(--surface-3)'>{fatias}</div>"
            f"<div style='width:64px;flex-shrink:0;font-size:var(--fs-xs);color:var(--text-muted);"
            f"font-variant-numeric:tabular-nums'>{total if total != 1 else ''} saída(s)</div>"
            "</div>")
    return f"<div style='margin-bottom:6px'>{legenda}</div>{rows}" if rows else "<span class=note>sem dados</span>"


def heatmap(colunas: list[str], linhas: list[tuple], fmt=None,
            cor_rgb: str = "245,197,24", largura_rotulo: int = 170) -> str:
    """HEATMAP (duas dimensões cruzadas): linhas = [(rotulo, [valores])] na
    ordem das colunas; None = célula vazia. Intensidade da cor + o NÚMERO na
    célula (não depende só de cor)."""
    fmt = fmt or _fmt_default
    todos = [v for _r, vs in linhas for v in vs if v is not None]
    vmax = max(todos) if todos else 1
    ths = "".join(f"<th style='padding:5px 7px;font-size:var(--fs-2xs);color:var(--text-muted);"
                  f"text-transform:uppercase;text-align:center;min-width:56px'>{escape(c)}</th>" for c in colunas)
    trs = ""
    for rot, vs in linhas:
        tds = ""
        for v in vs:
            if v is None:
                tds += ("<td style='padding:5px 7px;text-align:center;color:var(--text-faint);"
                        "font-size:var(--fs-xs);min-width:56px'>—</td>")
                continue
            alpha = 0.12 + 0.68 * (v / vmax if vmax else 0)
            tds += (f"<td style='padding:5px 7px;text-align:center;background:rgba({cor_rgb},{alpha:.2f});"
                    f"font-size:var(--fs-xs);font-weight:600;font-variant-numeric:tabular-nums;"
                    f"border-radius:4px;min-width:56px'>{fmt(v)}</td>")
        trs += (f"<tr><td style='padding:5px 9px;font-size:var(--fs-sm);text-align:right;"
                f"width:{largura_rotulo}px'>{escape(str(rot))}</td>{tds}</tr>")
    return ("<div style='overflow-x:auto'><table style='border-collapse:separate;border-spacing:3px;width:100%'>"
            f"<tr><th></th>{ths}</tr>{trs}</table></div>")


def data_bar(v, vmax, cor: str = "var(--brand)", largura: int = 64) -> str:
    """Mini-barra p/ dentro de célula de tabela (data bar) — o número continua
    visível ao lado; a barra só acelera a comparação."""
    w = (v / vmax * largura) if (v and vmax) else 0
    return (f"<span style='display:inline-block;vertical-align:middle;margin-left:8px;height:6px;"
            f"width:{max(w, 1):.0f}px;background:{cor};border-radius:3px'></span>")


def detalhe_tabela(tabela_html: str, rotulo: str = "ver tabela completa") -> str:
    """Preserva a tabela original recolhida sob o visual — NENHUM dado some."""
    return (f"<details style='margin-top:8px'><summary style='cursor:pointer;font-size:var(--fs-2xs);"
            f"color:var(--text-muted)'>▸ {escape(rotulo)}</summary>"
            f"<div style='margin-top:8px'>{tabela_html}</div></details>")
