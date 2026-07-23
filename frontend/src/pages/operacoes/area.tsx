import { ExternalLink } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { useSearchParams } from "react-router-dom";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { TimeSeries } from "@/components/charts/time-series";
import { FiltroBar, fmtData, fmtVal, SEM_BG, SEM_BORDER, useYearQuarter } from "./comum";

// Operações · página de uma área — /api/operacoes/area embrulha MT.load_metas
// (KPIs com meta trimestral + meta mensal ADAPTATIVA) e grupos_dados (as
// iniciativas, mesma régua do HTML). Gráfico realizado × meta por KPI.

interface Kpi {
  key: string; label: string; unit: string; direction: string; auto: boolean;
  real_tri: number | null; meta_tri: number | null; pct: number | null; ok: boolean | null;
  meses_lbl: string[]; reais: Array<number | null>; metas: Array<number | null>;
}
interface Acao {
  acao: string; cor: string; rotulo: string; prazo: string | null; dep: boolean;
  progresso: number | null; notion_url: string | null; responsaveis: string[];
  subitems: Array<{ titulo: string; concluida: boolean }>;
}
interface Grupo {
  gestor: string;
  iniciativas: Array<{ nome: string; feitos: number; total: number;
    subs: Array<{ detalhamento: string; acoes: Acao[] }> }>;
}
interface Payload {
  slug: string; nome: string; gestor: string; year: number; quarter: number;
  kpis: Kpi[];
  iniciativas: { um_gestor: boolean; grupos: Grupo[] };
}

function GraficoKpi({ k }: { k: Kpi }) {
  const data = k.meses_lbl.map((m, i) => ({ mes: m, real: k.reais[i], meta: k.metas[i] }));
  return (
    <TimeSeries data={data} xKey="mes" height={180}
      series={[
        { key: "real", label: "realizado", color: "var(--chart-1)",
          valueFormatter: (v) => fmtVal(v, k.unit) },
        { key: "meta", label: "meta (adaptativa)", color: "var(--warning)", dashed: true,
          valueFormatter: (v) => fmtVal(v, k.unit) },
      ]} />
  );
}

function AcaoLinha({ a }: { a: Acao }) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 border-t border-border py-1.5">
        <span className={`h-2 w-2 shrink-0 rounded-full ${SEM_BG[a.cor]}`} />
        <span className="min-w-[200px] flex-1 text-sm">
          {a.acao}
          {a.notion_url && (
            <a href={a.notion_url} target="_blank" rel="noreferrer" title="abrir no Notion"
              className="ml-1 inline-flex text-muted-foreground hover:text-foreground">
              <ExternalLink className="inline h-3 w-3" />
            </a>
          )}
          {a.responsaveis.length > 0 && (
            <span className="text-[11px] text-muted-foreground"> · {a.responsaveis.join(", ")}</span>
          )}
        </span>
        {a.progresso != null && (
          <span className="flex items-center gap-1">
            <span className="inline-block h-1.5 w-[70px] overflow-hidden rounded bg-muted">
              <span className={`block h-full ${SEM_BG[a.cor]}`} style={{ width: `${a.progresso}%` }} />
            </span>
            <span className="text-[11px] text-muted-foreground">{a.progresso.toFixed(0)}%</span>
          </span>
        )}
        {a.prazo && (
          <span className={`rounded-full border px-2 py-0.5 text-[11px] ${SEM_BORDER[a.cor]}`}>{fmtData(a.prazo)}</span>
        )}
        {a.dep && (
          <span className="rounded-full border border-warning/40 px-2 py-0.5 text-[11px] text-warning">
            aguardando ação anterior atrasada
          </span>
        )}
        <span className={`rounded-full border px-2 py-0.5 text-[11px] ${SEM_BORDER[a.cor]}`}>{a.rotulo}</span>
      </div>
      {a.subitems.map((s, i) => (
        <div key={i} className="flex items-center gap-1.5 py-0.5 pl-7 text-xs text-muted-foreground">
          <span className={`h-2 w-2 rounded-full ${s.concluida ? "bg-success" : "bg-muted-foreground/50"}`} />
          {s.titulo}
        </div>
      ))}
    </>
  );
}

function Grupos({ dados }: { dados: Payload["iniciativas"] }) {
  if (!dados.grupos.length) {
    return (
      <p className="rounded-lg border border-border bg-muted/30 p-3 text-sm text-muted-foreground">
        nenhuma iniciativa sincronizada — configure a URL do Notion em Configurações e clique em Sincronizar.
      </p>
    );
  }
  return (
    <div className="space-y-6">
      {dados.grupos.map((g) => (
        <div key={g.gestor} className="space-y-3">
          {!dados.um_gestor && <h3 className="font-display text-sm font-semibold">{g.gestor}</h3>}
          {g.iniciativas.map((inic) => (
            <div key={inic.nome} className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-baseline justify-between gap-2">
                <b className="text-sm">{inic.nome}</b>
                <span className="shrink-0 text-xs text-muted-foreground">{inic.feitos}/{inic.total} concluídas</span>
              </div>
              {inic.subs.map((sub, si) => (
                <div key={si}>
                  {sub.detalhamento && (
                    <div className="mt-2.5 text-[11px] uppercase tracking-wide text-muted-foreground">{sub.detalhamento}</div>
                  )}
                  {sub.acoes.map((a, ai) => <AcaoLinha key={ai} a={a} />)}
                </div>
              ))}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export function OperacoesAreaPage() {
  const { year, quarter } = useYearQuarter();
  const [params] = useSearchParams();
  const slug = params.get("view") ?? "";
  const q = useApi<Payload>(`/api/operacoes/area?slug=${slug}&year=${year}&quarter=${quarter}`);
  const d = q.data;
  const comGrafico = d?.kpis.filter((k) => k.meta_tri != null || k.reais.some((v) => v != null)) ?? [];

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">
            {d?.nome ?? "Operações"}<Hint area="operacoes/iniciativas" titulo="_intro" />
          </h1>
          {d && (
            <p className="mt-1 text-sm text-muted-foreground">Gestor(a): <b>{d.gestor}</b> · Q{d.quarter} {d.year}</p>
          )}
        </div>
        <FiltroBar area={slug} onSynced={q.refetch} />
      </header>

      {q.loading && <LoadingSkeleton rows={4} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}

      {d && (
        <>
          {d.kpis.length > 0 ? (
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(200px,1fr))" }}>
              {d.kpis.map((k) => (
                <div key={k.key} className="rounded-xl border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                      {k.label}{!k.auto && <span className="text-muted-foreground/60"> (manual)</span>}
                    </div>
                    {k.pct != null && (
                      <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] ${
                        k.ok ? "border-success/40 text-success" : "border-destructive/40 text-destructive"}`}>
                        {k.pct.toFixed(0)}%
                      </span>
                    )}
                  </div>
                  <div className="my-1 font-display text-2xl font-bold">{fmtVal(k.real_tri, k.unit)}</div>
                  <div className="text-[11px] text-muted-foreground">
                    Meta: {fmtVal(k.meta_tri, k.unit)}{k.direction === "max" ? " (teto)" : ""}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="rounded-lg border border-border bg-muted/30 p-3 text-sm text-muted-foreground">
              área sem KPIs de meta definidos — as iniciativas ficam abaixo
            </p>
          )}

          {comGrafico.length > 0 && (
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(340px,1fr))" }}>
              {comGrafico.map((k) => (
                <SectionCard key={k.key} title={`${k.label} · evolução mensal`}>
                  <GraficoKpi k={k} />
                </SectionCard>
              ))}
            </div>
          )}

          <section>
            <h2 className="font-display mb-3 text-lg font-semibold">Iniciativas</h2>
            <Grupos dados={d.iniciativas} />
          </section>
        </>
      )}
    </div>
  );
}
