import { Target } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { formatBRL, formatNumber, formatPct } from "@/lib/format";

// Vendas · Performance & Meta (Lote 6) — /api/vendas/forecast embrulha
// `sales.dados.vd_forecast_dados`. Mês corrente compara contra a fração
// decorrida (o traço vertical na barra); mês passado é meta × realizado.

interface Linha {
  plano: string; meta_q: number; meta_v: number; real_q: number; real_v: number;
  pct: number | null; gap: number; pipeline: number; oport_nec: number | null;
  no_ritmo: boolean; prioritario: boolean;
}
interface Payload {
  mes: string; corrente: boolean; frac: number;
  conv90: number; conv_lead90: number;
  linhas: Linha[];
  total: Linha & { oport: number; leads: number; pct: number | null; pipeline: number; no_ritmo: boolean };
  faltantes: Array<{ plano: string; gap: number; oport_nec: number | null;
    pipeline: number; suficiente: boolean | null }>;
  meses_disponiveis: string[];
}

const th = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const mesLabel = (iso: string) => {
  const [a, m] = iso.split("-");
  return `${m}/${a}`;
};

// barra de pacing: o traço vertical marca o ritmo esperado do mês
function Barra({ pct, frac, corrente }: { pct: number | null; frac: number; corrente: boolean }) {
  const v = Math.min(100, (pct ?? 0) * 100);
  return (
    <div className="relative h-2 w-full overflow-visible rounded bg-muted">
      <div className={cn("h-full rounded", (pct ?? 0) >= frac ? "bg-success" : "bg-destructive")}
        style={{ width: `${v}%` }} />
      {corrente && (
        <div className="absolute -top-0.5 -bottom-0.5 w-0.5 bg-muted-foreground"
          style={{ left: `${frac * 100}%` }} title={`ritmo esperado: ${(frac * 100).toFixed(0)}% do mês`} />
      )}
    </div>
  );
}

export function VendasForecastPage() {
  const [mes, setMes] = useState("");
  const q = useApi<Payload>(`/api/vendas/forecast${mes ? `?mes=${mes}` : ""}`);
  const d = q.data;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">
          Performance &amp; Meta{d && ` — ${mesLabel(d.mes)}`}
          <Hint area="vendas/forecast" titulo="_intro" />
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Metas da planilha financeira por plano · fechado no mês · pacing
          {d && (d.corrente
            ? ` · ritmo esperado: ${(d.frac * 100).toFixed(0)}% do mês`
            : " (mês encerrado)")}
          {d && ` · conversão 90d: ${formatPct(d.conv90 * 100, 1)} (oport→booking)`}
        </p>
      </header>

      {d && d.meses_disponiveis.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
          <Target className="h-4 w-4 text-muted-foreground" />
          <Select value={mes || d.mes.slice(0, 7)} onValueChange={setMes}>
            <SelectTrigger className="w-[150px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              {d.meses_disponiveis.map((m) => (
                <SelectItem key={m} value={m.slice(0, 7)}>{mesLabel(m)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {q.loading && <LoadingSkeleton rows={4} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && (
        <>
          <SectionCard hint={<Hint area="vendas/forecast" titulo="Meta realizado por plano" />}
            title="Meta × realizado por plano"
            subtitle="B3–B5 em destaque (prioridade da empresa) · o traço vertical na barra é o ritmo esperado do mês">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <TableHead className={th}>Plano</TableHead>
                    <TableHead className={`${th} text-right`}>Meta</TableHead>
                    <TableHead className={`${th} text-right`}>Meta R$</TableHead>
                    <TableHead className={`${th} text-right`}>Fechado</TableHead>
                    <TableHead className={`${th} text-right`}>Receita</TableHead>
                    <TableHead className={`${th} text-right`}>% meta</TableHead>
                    <TableHead className={`${th} min-w-[110px]`} />
                    <TableHead className={`${th} text-right`}>Gap</TableHead>
                    <TableHead className={`${th} text-right`}>Pipeline</TableHead>
                    <TableHead className={`${th} text-right`}>Oport. nec.</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.linhas.map((l) => (
                    <TableRow key={l.plano} className={cn(l.prioritario && "bg-primary/[0.04]")}>
                      <TableCell className="font-semibold">{l.plano}</TableCell>
                      <TableCell className="text-right tabular-nums">{l.meta_q.toFixed(0)}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatBRL(l.meta_v)}</TableCell>
                      <TableCell className="text-right font-semibold tabular-nums">{l.real_q}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatBRL(l.real_v)}</TableCell>
                      <TableCell className={cn("text-right tabular-nums",
                        l.pct == null ? "" : l.no_ritmo ? "text-success" : "text-destructive")}>
                        {l.pct != null ? formatPct(l.pct * 100, 1) : "—"}
                      </TableCell>
                      <TableCell><Barra pct={l.pct} frac={d.frac} corrente={d.corrente} /></TableCell>
                      <TableCell className="text-right tabular-nums">{l.gap.toFixed(0)}</TableCell>
                      <TableCell className="text-right tabular-nums">{l.pipeline}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {l.gap ? formatNumber(Math.round(l.oport_nec ?? 0)) : "✓"}
                      </TableCell>
                    </TableRow>
                  ))}
                  <TableRow className="border-t-2 border-border font-semibold">
                    <TableCell>TOTAL</TableCell>
                    <TableCell className="text-right tabular-nums">{d.total.meta_q.toFixed(0)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatBRL(d.total.meta_v)}</TableCell>
                    <TableCell className="text-right tabular-nums">{d.total.real_q}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatBRL(d.total.real_v)}</TableCell>
                    <TableCell className={cn("text-right tabular-nums",
                      d.total.no_ritmo ? "text-success" : "text-destructive")}>
                      {d.total.pct != null ? formatPct(d.total.pct * 100, 1) : "—"}
                    </TableCell>
                    <TableCell />
                    <TableCell className="text-right tabular-nums">{d.total.gap.toFixed(0)}</TableCell>
                    <TableCell className="text-right tabular-nums">{d.total.pipeline}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {d.total.gap ? formatNumber(Math.round(d.total.oport)) : "✓"}
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>
          </SectionCard>

          {d.corrente && d.faltantes.length > 0 && (
            <SectionCard hint={<Hint area="vendas/forecast" titulo="O que falta para bater as metas" />}
              title="O que falta para bater as metas"
              subtitle="gap por plano traduzido em oportunidades e leads necessários no ritmo de conversão dos últimos 90 dias">
              <div className="divide-y divide-border">
                {d.faltantes.map((f) => (
                  <div key={f.plano} className="py-2.5 text-sm leading-relaxed">
                    <b>{f.plano}</b>: faltam <b>{f.gap.toFixed(0)} bookings</b> → ≈{" "}
                    <b>{formatNumber(Math.round(f.oport_nec ?? 0))} oportunidades</b> no ritmo de
                    conversão 90d ({formatPct(d.conv90 * 100, 1)})
                    {f.oport_nec != null && (
                      <span className="text-muted-foreground">
                        {" "}(pipeline atual: {f.pipeline} abertas
                        {f.suficiente
                          ? " — suficiente se converter no ritmo"
                          : <b className="text-destructive"> — INSUFICIENTE</b>})
                      </span>
                    )}
                  </div>
                ))}
                <div className="py-2.5 text-sm leading-relaxed">
                  <b>Total</b>: {d.total.gap.toFixed(0)} bookings ≈{" "}
                  {formatNumber(Math.round(d.total.oport))} oportunidades ≈{" "}
                  <b>{formatNumber(Math.round(d.total.leads))} leads novos</b> (conversão
                  lead→booking 90d: {formatPct(d.conv_lead90 * 100, 1)}) — é o pedido concreto a
                  Pré-vendas e ao Marketing para fechar o mês.
                </div>
              </div>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}
