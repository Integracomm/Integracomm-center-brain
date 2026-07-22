import { useMemo } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { TimeSeries } from "@/components/charts/time-series";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

// Marketing · Tempo até Resultado (Lote 4) — /api/marketing/lag.
// Curva de acúmulo virou TimeSeries (%, 0-120 dias desde o lançamento).

interface Payload {
  stats: Array<{ canal: string; marco: string; campanhas: number; p25: number; mediana: number; p75: number }>;
  curvas: Array<{ canal: string; total_leads: number; pct_acumulado: number[] }>;
  campanhas: Array<{ campanha: string; leads: number; d_primeiro_lead: number | null;
    d_primeiro_booking: number | null; d_50pct_leads: number | null }>;
}

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const numCls = "text-right tabular-nums";
const fd = (v: number | null) => (v != null ? `${v.toFixed(0)}d` : "—");
const CORES = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)"];

export function MktLagPage() {
  const q = useApi<Payload>("/api/marketing/lag");
  const d = q.data;
  const curva = useMemo(() => {
    if (!d || !d.curvas.length) return null;
    const data = Array.from({ length: 121 }, (_, dia) => {
      const row: Record<string, number | string> = { dia: `${dia}` };
      for (const c of d.curvas) row[c.canal] = c.pct_acumulado[dia];
      return row;
    });
    return { data, series: d.curvas.map((c, i) => ({ key: c.canal, label: c.canal, color: CORES[i % 3],
      valueFormatter: (v: number) => `${v.toFixed(0)}%` })) };
  }, [d]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Tempo até Resultado<Hint area="marketing/lag" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Dias entre o lançamento da campanha e cada marco — a base do Planejador.
        </p>
      </header>
      {q.loading && <LoadingSkeleton rows={5} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && (
        <>
          <SectionCard hint={<Hint area="marketing/lag" titulo="Lag agregado por canal" />}
            title="Lag agregado por canal" subtitle="mediana com intervalo p25–p75 (recalculado semanalmente)">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className={thCls}>Canal</TableHead>
                  <TableHead className={thCls}>Marco</TableHead>
                  <TableHead className={`${thCls} text-right`}>Campanhas</TableHead>
                  <TableHead className={`${thCls} text-right`}>p25</TableHead>
                  <TableHead className={`${thCls} text-right`}>Mediana</TableHead>
                  <TableHead className={`${thCls} text-right`}>p75</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.stats.map((s) => (
                  <TableRow key={`${s.canal}-${s.marco}`}>
                    <TableCell className="font-medium">{s.canal}</TableCell>
                    <TableCell>{s.marco}</TableCell>
                    <TableCell className={numCls}>{s.campanhas}</TableCell>
                    <TableCell className={numCls}>{s.p25}d</TableCell>
                    <TableCell className={`${numCls} font-semibold`}>{s.mediana}d</TableCell>
                    <TableCell className={numCls}>{s.p75}d</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </SectionCard>

          <SectionCard hint={<Hint area="marketing/lag" titulo="Curva de acúmulo de leads" />}
            title="Curva de acúmulo de leads"
            subtitle="% acumulado de leads por dias desde o lançamento (até 120d) · só canais com 30+ leads">
            {curva ? (
              <TimeSeries data={curva.data} xKey="dia" series={curva.series} height={260}
                leftDomain={[0, 100]} leftTickFormatter={(v) => `${v}%`} />
            ) : (
              <p className="text-sm text-muted-foreground">Sem campanhas com volume suficiente.</p>
            )}
          </SectionCard>

          <SectionCard hint={<Hint area="marketing/lag" titulo="Por campanha" />}
            title="Por campanha" subtitle="as 20 maiores por volume — material de validação com o gestor">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Campanha</TableHead>
                    <TableHead className={`${thCls} text-right`}>Leads</TableHead>
                    <TableHead className={`${thCls} text-right`}>1º lead</TableHead>
                    <TableHead className={`${thCls} text-right`}>1º booking</TableHead>
                    <TableHead className={`${thCls} text-right`}>50% leads</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.campanhas.map((c) => (
                    <TableRow key={c.campanha}>
                      <TableCell className="font-medium">{c.campanha}</TableCell>
                      <TableCell className={numCls}>{c.leads}</TableCell>
                      <TableCell className={numCls}>{fd(c.d_primeiro_lead)}</TableCell>
                      <TableCell className={numCls}>{fd(c.d_primeiro_booking)}</TableCell>
                      <TableCell className={numCls}>{fd(c.d_50pct_leads)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}
