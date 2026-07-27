import React from "react";

// Markdown mínimo para as respostas do assistente — construído como nós React
// (nunca dangerouslySetInnerHTML: a resposta pode ecoar texto digitado por
// terceiros em campos livres). Cobre o que o system prompt permite ao modelo:
// títulos, negrito, itálico, código inline, listas, tabelas e links INTERNOS.

function inline(texto: string, chave: number): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  // links [rotulo](/rota) — só rotas internas; qualquer outra vira texto puro
  const re = /\[([^\]]+)\]\((\/[^)\s]*)\)|\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`/g;
  let i = 0, m: RegExpExecArray | null, k = 0;
  while ((m = re.exec(texto)) !== null) {
    if (m.index > i) out.push(texto.slice(i, m.index));
    if (m[1] !== undefined) {
      out.push(<a key={`${chave}-${k++}`} href={m[2]} className="text-primary underline underline-offset-2">{m[1]}</a>);
    } else if (m[3] !== undefined) {
      out.push(<strong key={`${chave}-${k++}`}>{m[3]}</strong>);
    } else if (m[4] !== undefined) {
      out.push(<em key={`${chave}-${k++}`}>{m[4]}</em>);
    } else if (m[5] !== undefined) {
      out.push(<code key={`${chave}-${k++}`} className="rounded bg-muted px-1 py-0.5 text-[0.85em]">{m[5]}</code>);
    }
    i = m.index + m[0].length;
  }
  if (i < texto.length) out.push(texto.slice(i));
  return out;
}

function ehLinhaTabela(l: string): boolean {
  const t = l.trim();
  return t.startsWith("|") && t.endsWith("|") && t.length > 2;
}

function celulas(l: string): string[] {
  return l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

export function Md({ texto }: { texto: string }) {
  const linhas = texto.split("\n");
  const blocos: React.ReactNode[] = [];
  let i = 0, k = 0;
  while (i < linhas.length) {
    const l = linhas[i];
    const t = l.trim();
    if (!t) { i++; continue; }

    const h = /^(#{1,4})\s+(.*)$/.exec(t);
    if (h) {
      blocos.push(
        <p key={k++} className={`font-display font-semibold ${h[1].length <= 2 ? "text-sm" : "text-xs uppercase tracking-wide text-muted-foreground"} mt-3 mb-1`}>
          {inline(h[2], k)}
        </p>);
      i++; continue;
    }

    if (ehLinhaTabela(t)) {
      const corpo: string[][] = [];
      let cab: string[] | null = null;
      while (i < linhas.length && ehLinhaTabela(linhas[i].trim())) {
        const cs = celulas(linhas[i]);
        if (cs.every((c) => /^:?-{2,}:?$/.test(c))) { cab = corpo.pop() ?? null; }
        else corpo.push(cs);
        i++;
      }
      blocos.push(
        <div key={k++} className="my-2 overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            {cab && (
              <thead><tr>{cab.map((c, j) => (
                <th key={j} className="border-b border-border px-2 py-1 text-left font-semibold">{inline(c, k * 100 + j)}</th>
              ))}</tr></thead>
            )}
            <tbody>{corpo.map((linha, r) => (
              <tr key={r}>{linha.map((c, j) => (
                <td key={j} className="border-b border-border/50 px-2 py-1 tabular-nums">{inline(c, k * 1000 + r * 10 + j)}</td>
              ))}</tr>
            ))}</tbody>
          </table>
        </div>);
      continue;
    }

    const li = /^[-•]\s+(.*)$/.exec(t) || /^(\d+)[.)]\s+(.*)$/.exec(t);
    if (li) {
      const itens: React.ReactNode[] = [];
      const numerada = /^\d/.test(t);
      while (i < linhas.length) {
        const it = linhas[i].trim();
        const m2 = numerada ? /^(\d+)[.)]\s+(.*)$/.exec(it) : /^[-•]\s+(.*)$/.exec(it);
        if (!m2) break;
        itens.push(<li key={itens.length} className="ml-4 list-outside" style={{ listStyleType: numerada ? "decimal" : "disc" }}>{inline(numerada ? m2[2] : m2[1], k * 50 + itens.length)}</li>);
        i++;
      }
      blocos.push(<ul key={k++} className="my-1.5 space-y-0.5">{itens}</ul>);
      continue;
    }

    // parágrafo: junta linhas contíguas que não são bloco especial
    const par: string[] = [t];
    i++;
    while (i < linhas.length) {
      const p = linhas[i].trim();
      if (!p || ehLinhaTabela(p) || /^#{1,4}\s/.test(p) || /^[-•]\s/.test(p) || /^\d+[.)]\s/.test(p)) break;
      par.push(p); i++;
    }
    blocos.push(<p key={k++} className="my-1.5 leading-relaxed">{inline(par.join(" "), k)}</p>);
  }
  return <div className="text-sm">{blocos}</div>;
}
