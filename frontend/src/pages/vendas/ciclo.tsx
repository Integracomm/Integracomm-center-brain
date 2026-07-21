import { AlarmClock, CalendarRange, FolderOpen, Timer } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { SectionCard } from "@/components/blocks/section-card";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatBRL } from "@/lib/format";
import type { VendasCicloPayload } from "@/types/api";

// Vendas · Ciclo & Empacados (Lote 3) — tempo da 1ª reunião ao contrato
// (distribuição, não só média) + fila de destrave. Números prontos de
// /api/vendas/ciclo (mesmas queries da tela HTML — paridade checada).

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const numCls = "text-right tabular-nums";
const fd = (v: number | null) => (v != null ? `${v.toLocaleString("pt-BR")} d` : "—");

export function VendasCicloPage() {
  const hoje = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const [ini, setIni] = useState(iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)));
  const [fim, setFim] = useState(iso(hoje));
  const q = useApi<VendasCicloPayload>(`/api/vendas/ciclo?ini=${ini}&fim=${fim}`);
  const d = q.data;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Ciclo de Vendas<Hint area="vendas/ciclo" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Tempo da 1ª reunião ao fechamento · distribuição, não só média.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
        <CalendarRange className="h-4 w-4 text-muted-foreground" />
        <Input type="date" value={ini} onChange={(e) => setIni(e.target.value)} className="w-[160px]" />
        <span className="text-xs text-muted-foreground">até</span>
        <Input type="date" value={fim} onChange={(e) => setFim(e.target.value)} className="w-[160px]" />
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          o período filtra os GANHOS; abertos/empacados são a foto de hoje
          <Hint area="vendas/ciclo" titulo="Ciclo e distribuição" />
        </span>
      </div>

      {q.loading && <LoadingSkeleton rows={5} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && (
        <>
          <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
            <KpiCard icon={Timer} tone="primary" title="Ciclo mediano"
              value={fd(d.kpis.ciclo_mediano_d)}
              subtitle={`1ª reunião → contrato (${d.kpis.n_ganhos} ganhos)`} />
            <KpiCard icon={Timer} tone="muted" title="p25 – p75"
              value={`${fd(d.kpis.p25_d)} – ${fd(d.kpis.p75_d)}`}
              subtitle="metade dos casos fecha dentro desta faixa" />
            <KpiCard icon={FolderOpen} tone="accent" title="Deals abertos em Vendas"
              value={d.kpis.abertos.toLocaleString("pt-BR")} />
            <KpiCard icon={AlarmClock} tone={d.kpis.empacados ? "warning" : "success"} title="Empacados"
              value={d.kpis.empacados.toLocaleString("pt-BR")}
              subtitle={`sem movimento há mais de ${d.kpis.limiar_dias.toLocaleString("pt-BR")} dias`} />
          </div>

          <SectionCard hint={<Hint area="vendas/ciclo" titulo="Deals empacados" />}
            title="Deals empacados — lista de atenção"
            subtitle="sem movimento há mais de 2× a mediana (mín. 14 dias) — reativar com urgência ou limpar · top 20">
            {d.empacados.length ? (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className={thCls}>Deal</TableHead>
                      <TableHead className={thCls}>Dono</TableHead>
                      <TableHead className={thCls}>Plano</TableHead>
                      <TableHead className={`${thCls} text-right`}>Valor</TableHead>
                      <TableHead className={`${thCls} text-right`}>Parado há</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.empacados.map((e) => (
                      <TableRow key={e.deal_id}>
                        <TableCell className="font-medium">#{e.deal_id}</TableCell>
                        <TableCell>{e.dono}</TableCell>
                        <TableCell>{e.plano}</TableCell>
                        <TableCell className={numCls}>{e.valor != null ? formatBRL(e.valor) : "—"}</TableCell>
                        <TableCell className={`${numCls} font-semibold`}>{e.dias.toLocaleString("pt-BR")} d</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">nenhum deal empacado 🎉</p>
            )}
          </SectionCard>
        </>
      )}
    </div>
  );
}
