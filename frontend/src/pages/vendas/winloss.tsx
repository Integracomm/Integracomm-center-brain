import { CalendarRange, HelpCircle, TrendingDown, Wallet } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { CaveatChip } from "@/components/caveat";
import { SectionCard } from "@/components/blocks/section-card";
import { BarListH } from "@/components/charts/bar-list-h";
import { Heatmap } from "@/components/charts/heatmap";
import { TimeSeries } from "@/components/charts/time-series";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatBRL, formatPct } from "@/lib/format";
import type { WinLossPayload } from "@/types/api";

// Vendas · Win/Loss — Pareto de motivos + cards por bundle + heatmaps
// motivo×origem e motivo×closer (pedido do plano). Números prontos de
// /api/vendas/winloss (mesmas queries da tela HTML — paridade checada).

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";

function Det({ resumo, children }: { resumo: string; children: React.ReactNode }) {
  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-xs font-medium text-primary">{resumo}</summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

const CHART_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];

export function VendasWinLossPage() {
  const hoje = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const [ini, setIni] = useState(iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)));
  const [fim, setFim] = useState(iso(hoje));
  const q = useApi<WinLossPayload>(`/api/vendas/winloss?ini=${ini}&fim=${fim}`);
  const d = q.data;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Win/Loss — Análise de Perdas<Hint area="vendas/winloss" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Perdas na fase de Vendas (da reunião em diante), por motivo e valor.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
        <CalendarRange className="h-4 w-4 text-muted-foreground" />
        <Input type="date" value={ini} onChange={(e) => setIni(e.target.value)} className="w-[160px]" />
        <span className="text-xs text-muted-foreground">até</span>
        <Input type="date" value={fim} onChange={(e) => setFim(e.target.value)} className="w-[160px]" />
      </div>

      {q.loading && <LoadingSkeleton rows={6} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
            <KpiCard icon={TrendingDown} tone="destructive" title="Deals perdidos"
              value={d.kpis.deals_perdidos.toLocaleString("pt-BR")} subtitle="da reunião em diante" />
            <KpiCard icon={Wallet} tone="warning" title="MRR perdido"
              value={formatBRL(d.kpis.mrr_perdido)} />
            <KpiCard icon={HelpCircle} tone="muted" title="Motivo nº 1"
              value={d.kpis.motivo_top ?? "—"}
              caveat={d.sem_motivo > 0 ? `${d.sem_motivo} perda(s) sem motivo preenchido no Pipedrive` : undefined} />
          </div>

          {d.diagnostico && (
            <SectionCard hint={<Hint area="vendas/winloss" titulo="Diagnóstico dominante" />} title="Diagnóstico dominante"
              subtitle={`gerado por ${d.diagnostico.fonte} — hipótese para investigar, não veredito`}>
              <p className="text-sm leading-relaxed">
                → Motivo nº 1: <b>“{d.diagnostico.motivo}”</b> ({d.diagnostico.deals} deals). Leitura:{" "}
                {d.diagnostico.leitura}
                {d.diagnostico.concentracao && (
                  <span className="text-warning"> ATENÇÃO: {d.diagnostico.concentracao}</span>
                )}
              </p>
            </SectionCard>
          )}

          <SectionCard hint={<Hint area="vendas/winloss" titulo="Motivos de perda" />} title="Motivos de perda (Pareto)"
            subtitle={`por frequência · ${d.sem_motivo} sem motivo preenchido no período`}>
            {d.motivos_perda.length ? (
              <BarListH
                height={Math.max(240, Math.min(10, d.motivos_perda.length) * 46)}
                width={240}
                data={d.motivos_perda.slice(0, 10).map((m) => ({ label: m.motivo, value: m.deals, _m: m }))}
                color="var(--destructive)"
                tooltipFormatter={(v, it) => {
                  const m = (it as { _m: { mrr_perdido: number | null } })._m;
                  return [`MRR perdido: ${formatBRL(m.mrr_perdido)}`, `${v} deals`];
                }}
              />
            ) : (
              <p className="text-sm text-muted-foreground">Sem perdas no período.</p>
            )}
            {d.sem_motivo > 0 && (
              <div className="mt-2"><CaveatChip text={`${d.sem_motivo} perda(s) sem motivo — sem registro não há aprendizado`} /></div>
            )}
            <Det resumo="ver tabela (deals e MRR por motivo)">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <TableHead className={thCls}>Motivo</TableHead>
                    <TableHead className={`${thCls} text-right`}>Deals</TableHead>
                    <TableHead className={`${thCls} text-right`}>MRR perdido</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.motivos_perda.map((m) => (
                    <TableRow key={m.motivo}>
                      <TableCell>{m.motivo}</TableCell>
                      <TableCell className="text-right tabular-nums">{m.deals}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatBRL(m.mrr_perdido)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Det>
          </SectionCard>

          {d.evolucao.meses.length >= 2 && d.evolucao.series.length > 0 && (
            <SectionCard hint={<Hint area="vendas/winloss" titulo="Evolução dos motivos" />} title="Evolução dos motivos (6 meses)"
              subtitle="perdas por mês do fechamento, top 5 motivos · o mês corrente é PARCIAL — não conclua por ele">
              <TimeSeries
                height={260}
                data={d.evolucao.meses.map((mes, i) => {
                  const row: Record<string, string | number> = { mes };
                  d.evolucao.series.forEach((s) => { row[s.motivo] = s.valores[i]; });
                  return row;
                })}
                xKey="mes"
                series={d.evolucao.series.map((s, i) => ({
                  key: s.motivo, label: s.motivo, color: CHART_COLORS[i % CHART_COLORS.length],
                }))}
              />
            </SectionCard>
          )}

          <SectionCard hint={<Hint area="vendas/winloss" titulo="Principais motivos de perda por bundle" />} title="Principais motivos por bundle"
            subtitle="concentrado num bundle = preço/produto · espalhado por todos = abordagem">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {d.por_bundle.map((b) => (
                <div key={b.bundle} className="rounded-xl border border-border p-4">
                  <div className="flex items-baseline justify-between">
                    <span className="font-display font-bold">{b.bundle}</span>
                    <span className="text-xs text-muted-foreground">
                      {b.perdas} perda(s) · {formatBRL(b.mrr_perdido)}
                    </span>
                  </div>
                  {b.motivos.map((m) => (
                    <div key={m.motivo} className="mt-2">
                      <div className="flex justify-between gap-2 text-xs">
                        <span className={m.motivo === "(sem motivo)" ? "text-muted-foreground/70" : "text-muted-foreground"}>
                          {m.motivo}
                        </span>
                        <span className="whitespace-nowrap tabular-nums"><b>{m.deals}</b> · {m.pct}%</span>
                      </div>
                      <div className="mt-1 h-1.5 overflow-hidden rounded bg-muted">
                        <div className="h-full rounded bg-warning" style={{ width: `${m.pct}%` }} />
                      </div>
                    </div>
                  ))}
                  {b.outros_motivos > 0 && (
                    <div className="mt-2 text-[11px] text-muted-foreground">+ {b.outros_motivos} outro(s) motivo(s)</div>
                  )}
                </div>
              ))}
            </div>
          </SectionCard>

          <div className="grid gap-6 xl:grid-cols-2">
            <SectionCard hint={<Hint area="vendas/winloss" titulo="Origem × motivo" />} title="Origem × motivo"
              subtitle="eixos INVERTIDOS a pedido: cada linha é uma origem; célula = % das perdas DELA por motivo — responde 'essa origem perde por quê'">
              <Heatmap rows={d.heatmap_origem_x_motivo.rows} cols={d.heatmap_origem_x_motivo.cols}
                cells={d.heatmap_origem_x_motivo.cells} valueLabel={(v) => formatPct(v)}
                legendLabel="% das perdas da origem" rowLabelWidth={120} dense rowScale
                tooltipLabel={(c) => `${c.row} × ${(c as { col_full?: string }).col_full ?? c.col}: ${formatPct(c.value ?? 0)} (${c.n} deal(s))${c.amostra_pequena ? " · amostra pequena" : ""}`} />
            </SectionCard>
            <SectionCard hint={<Hint area="vendas/winloss" titulo="Closer × motivo" />} title="Closer × motivo"
              subtitle="cada linha é um closer; célula = % das perdas DELE por motivo · concentrado num motivo = treino individual">
              <Heatmap rows={d.heatmap_closer_x_motivo.rows} cols={d.heatmap_closer_x_motivo.cols}
                cells={d.heatmap_closer_x_motivo.cells} valueLabel={(v) => formatPct(v)}
                legendLabel="% das perdas do closer" rowLabelWidth={120} dense rowScale
                tooltipLabel={(c) => `${c.row} × ${(c as { col_full?: string }).col_full ?? c.col}: ${formatPct(c.value ?? 0)} (${c.n} deal(s))${c.amostra_pequena ? " · amostra pequena" : ""}`} />
            </SectionCard>
          </div>
        </>
      )}
    </div>
  );
}
