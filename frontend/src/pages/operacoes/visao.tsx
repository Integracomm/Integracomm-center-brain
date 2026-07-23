import { AlertTriangle } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { FiltroBar, fmtData, useYearQuarter } from "./comum";

// Operações · Visão Geral — /api/operacoes/visao embrulha _contagem/_semaforo
// sobre as iniciativas do Notion. Cards por área (contagem + progresso) e a
// fila das iniciativas atrasadas (prazo vencido), a mais antiga primeiro.

interface AreaCard {
  slug: string; nome: string; gestor: string;
  total: number; ok: number; prog: number; atras: number; ni: number; progresso: number;
}
interface Payload {
  year: number; quarter: number; progresso_total: number;
  areas: AreaCard[];
  atrasadas: Array<{ iniciativa: string; area_nome: string; acao: string; prazo: string | null }>;
}

const NUMS: Array<[keyof AreaCard, string, string]> = [
  ["total", "total", "text-foreground"],
  ["ok", "ok", "text-success"],
  ["prog", "prog.", "text-warning"],
  ["atras", "atras.", "text-destructive"],
  ["ni", "n/i", "text-muted-foreground"],
];

export function OperacoesVisaoPage() {
  const { year, quarter } = useYearQuarter();
  const q = useApi<Payload>(`/api/operacoes/visao?year=${year}&quarter=${quarter}`);
  const d = q.data;
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">
            Operações<Hint area="operacoes/iniciativas" titulo="_intro" />
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Metas e iniciativas estratégicas por área · iniciativas do Notion (somente leitura) ·
            meta mensal adaptativa: o que faltou/sobrou num mês redistribui nos seguintes.
          </p>
        </div>
        <FiltroBar onSynced={q.refetch} />
      </header>

      {q.loading && <LoadingSkeleton rows={4} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}

      {d && (
        <>
          <div className="flex justify-end">
            <div className="min-w-[230px]">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Progresso real das iniciativas</span><span>{d.progresso_total.toFixed(0)}%</span>
              </div>
              <div className="mt-1 h-2 overflow-hidden rounded bg-muted">
                <div className="h-full bg-primary" style={{ width: `${d.progresso_total}%` }} />
              </div>
            </div>
          </div>

          <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(215px,1fr))" }}>
            {d.areas.map((a) => (
              <a key={a.slug} href={`/operacoes?view=${a.slug}&year=${year}&quarter=${quarter}`}
                className="block rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40">
                <b className="text-sm">{a.nome}</b>
                <div className="text-[11px] text-muted-foreground">Gestor(a): {a.gestor}</div>
                <div className="my-3 flex justify-between gap-1.5">
                  {NUMS.map(([key, lbl, cor]) => (
                    <div key={lbl} className="text-center">
                      <div className={`font-display text-lg font-bold ${cor}`}>{a[key] as number}</div>
                      <div className="text-[9px] uppercase text-muted-foreground">{lbl}</div>
                    </div>
                  ))}
                </div>
                <div className="flex justify-between text-[11px] text-muted-foreground">
                  <span>Progresso</span><span>{a.progresso.toFixed(0)}%</span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded bg-muted">
                  <div className="h-full bg-primary" style={{ width: `${a.progresso}%` }} />
                </div>
              </a>
            ))}
          </div>

          <section className="rounded-xl border border-border bg-card p-4">
            <h2 className="font-display mb-2 flex items-center gap-1.5 text-sm font-semibold">
              <AlertTriangle className="h-4 w-4 text-destructive" /> Iniciativas atrasadas
            </h2>
            {d.atrasadas.length === 0 ? (
              <p className="text-sm text-muted-foreground">nenhuma iniciativa atrasada 🎉</p>
            ) : (
              <div>
                {d.atrasadas.map((r, i) => (
                  <div key={i} className="flex items-center justify-between gap-3 border-t border-border py-2 first:border-t-0">
                    <div className="min-w-0">
                      <div className="truncate text-sm">{r.iniciativa}</div>
                      <div className="text-[11px] text-muted-foreground">{r.area_nome} · {r.acao}</div>
                    </div>
                    <span className="shrink-0 rounded-full border border-destructive/40 px-2 py-0.5 text-xs text-destructive">
                      {fmtData(r.prazo)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
