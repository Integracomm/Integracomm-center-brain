import { ExternalLink, FileText, Loader2, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useListaDaSessao } from "./usar-lista-sessao";
import { apiDelete, apiPost } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

// Relatório de Assessoria (Lote 6) — fluxo de GERAÇÃO sob demanda: seleciona N
// clientes + mês de referência → POST /api/reports/batch → lista os gerados.
//
// A lista "gerados nesta sessão" foi mantida (Otávio 23/07) e ganhou EXCLUIR:
// a geração é sob demanda e às vezes sai para o cliente ou o mês errado — sem
// excluir, o engano ficava no histórico para sempre.
//
// A lista SOBREVIVE AO RECARREGAR e morre ao sair da tela (Otávio 23/07) —
// ver `useListaDaSessao`. Recarregar por engano no meio de uma geração de 20
// clientes custava caro; sair da tela é uma decisão consciente.
//
// Falha de UMA conta não derruba o lote (o backend devolve status por item);
// os itens com erro aparecem na lista com o motivo, em vez de sumirem.

interface Conta { id: string; nome: string }
interface Gerado {
  chave: string;
  report_id?: string; conta: string; mes: string;
  status: "ok" | "erro"; erro?: string;
  excluindo?: boolean;
}

const mesLabel = (iso: string) => {
  const [a, m] = iso.split("-");
  return `${m}/${a}`;
};

export function RelatorioAssessoria({ contas, mesPadrao }: {
  contas: Conta[]; mesPadrao: string;
}) {
  const [busca, setBusca] = useState("");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [mes, setMes] = useState(mesPadrao);
  const [gerando, setGerando] = useState(false);
  const [msg, setMsg] = useState("");
  const [gerados, setGerados] = useListaDaSessao<Gerado>("assessoria:gerados", []);

  const visiveis = useMemo(() => {
    const q = busca.toLowerCase().trim();
    return q ? contas.filter((c) => c.nome.toLowerCase().includes(q)) : contas;
  }, [contas, busca]);

  function alterna(id: string) {
    setSel((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  }
  const marcarVisiveis = (v: boolean) => setSel((s) => {
    const n = new Set(s);
    for (const c of visiveis) v ? n.add(c.id) : n.delete(c.id);
    return n;
  });

  async function gerar() {
    if (!sel.size) { setMsg("selecione ao menos um cliente."); return; }
    if (!mes) { setMsg("informe o mês de referência."); return; }
    setGerando(true);
    setMsg(`gerando ${sel.size} relatório(s)… (busca planilha + ClickUp + sinais; `
      + "pode levar alguns segundos por cliente)");
    try {
      const r = await apiPost<{ month: string; reports: Array<{
        account_id: string; account_name?: string; report_id?: string;
        status: string; error?: string }> }>(
        "/api/reports/batch", { account_ids: [...sel], month: mes });
      const ok = r.reports.filter((x) => x.status === "ok").length;
      setMsg(`${ok} de ${r.reports.length} relatório(s) gerado(s) para ${mesLabel(r.month)}.`);
      const novos: Gerado[] = r.reports.map((x, i) => ({
        chave: x.report_id ?? `${x.account_id}-${i}-${Date.now()}`,
        report_id: x.report_id,
        conta: x.account_name ?? x.account_id,
        mes: r.month,
        status: x.status === "ok" ? "ok" : "erro",
        erro: x.error,
      }));
      setGerados([...novos, ...gerados]);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "falha na geração");
    } finally {
      setGerando(false);
    }
  }

  async function excluir(g: Gerado) {
    if (!g.report_id) { setGerados(gerados.filter((x) => x.chave !== g.chave)); return; }
    if (!confirm(`Excluir o relatório de ${g.conta} (${mesLabel(g.mes)})? `
      + "O relatório sai do histórico; a conta e os dados de origem não são afetados.")) return;
    setGerados(gerados.map((x) => x.chave === g.chave ? { ...x, excluindo: true } : x));
    try {
      await apiDelete(`/api/reports/${g.report_id}`);
      setGerados(gerados.filter((x) => x.chave !== g.chave));
      setMsg(`relatório de ${g.conta} excluído.`);
    } catch (e) {
      setGerados(gerados.map((x) => x.chave === g.chave ? { ...x, excluindo: false } : x));
      setMsg(e instanceof Error ? e.message : "falha ao excluir");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start gap-5">
        <div className="min-w-[280px] flex-1">
          <label className="mb-1.5 block text-[10px] uppercase tracking-wide text-muted-foreground">
            clientes
          </label>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={busca} onChange={(e) => setBusca(e.target.value)}
              placeholder="filtrar por nome…" className="pl-8" />
          </div>
          <div className="mt-1.5 max-h-[230px] overflow-y-auto rounded-lg border border-border bg-muted/20">
            {visiveis.map((c) => (
              <label key={c.id}
                className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-muted/60">
                <input type="checkbox" checked={sel.has(c.id)} onChange={() => alterna(c.id)}
                  className="accent-primary" />
                <span className="truncate" title={c.nome}>{c.nome}</span>
              </label>
            ))}
            {visiveis.length === 0 && (
              <p className="px-3 py-4 text-center text-xs text-muted-foreground">
                nenhum cliente com esse nome
              </p>
            )}
          </div>
          <div className="mt-1.5 text-xs text-muted-foreground">
            <button onClick={() => marcarVisiveis(true)} className="hover:underline">marcar visíveis</button>
            {" · "}
            <button onClick={() => marcarVisiveis(false)} className="hover:underline">desmarcar todos</button>
            {" · "}<span>{sel.size} selecionados</span>
          </div>
        </div>

        <div>
          <label className="mb-1.5 block text-[10px] uppercase tracking-wide text-muted-foreground">
            mês de referência
          </label>
          <Input type="month" value={mes} max={mesPadrao}
            onChange={(e) => setMes(e.target.value)} className="w-[160px]" />
          <Button onClick={gerar} disabled={gerando} className="mt-3 w-full">
            {gerando && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            {gerando ? "Gerando…" : "Gerar Relatório(s)"}
          </Button>
          {msg && (
            <p className="mt-2.5 max-w-[240px] text-xs leading-relaxed text-muted-foreground">{msg}</p>
          )}
        </div>
      </div>

      {gerados.length > 0 && (
        <div>
          <div className="mb-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
            relatórios gerados nesta sessão
            <span className="ml-1.5 normal-case tracking-normal text-muted-foreground/70">
              (a lista sobrevive a um recarregar; sai da tela e ela zera — os relatórios seguem
              no histórico)
            </span>
          </div>
          <ul className="divide-y divide-border rounded-lg border border-border">
            {gerados.map((g) => (
              <li key={g.chave}
                className={cn("flex flex-wrap items-center justify-between gap-3 px-3 py-2 text-sm",
                  g.excluindo && "opacity-50")}>
                <span className="min-w-0 truncate">
                  <FileText className="mr-1.5 inline h-3.5 w-3.5 text-muted-foreground" />
                  {g.conta} · {mesLabel(g.mes)}
                </span>
                {g.status === "ok" ? (
                  <span className="flex shrink-0 items-center gap-3">
                    <a href={`/growth/report?report_id=${g.report_id}`} target="_blank" rel="noopener"
                      className="font-semibold text-primary hover:underline">
                      visualizar <ExternalLink className="inline h-3 w-3" />
                    </a>
                    <span className="text-xs text-muted-foreground" title="abra e use Exportar/Imprimir">
                      exportar pelo navegador
                    </span>
                    <button onClick={() => excluir(g)} disabled={g.excluindo}
                      className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-destructive"
                      title="excluir este relatório do histórico">
                      <Trash2 className="h-3.5 w-3.5" /> excluir
                    </button>
                  </span>
                ) : (
                  <span className="shrink-0 text-xs text-destructive">
                    erro: {g.erro || "falha"}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
