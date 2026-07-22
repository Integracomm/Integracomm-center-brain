import { CalendarRange, MousePointerClick, Users, Wallet } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { SectionCard } from "@/components/blocks/section-card";
import { TimeSeries } from "@/components/charts/time-series";
import { Input } from "@/components/ui/input";
import { formatBRL, formatNumber } from "@/lib/format";

// Marketing · Mídia Paga (Lote 4) — /api/marketing/midia. Leads/CPL pelos
// DEALS do Pipedrive (batem com o CRM); gasto/CTR da plataforma.

interface Payload {
  periodo: { ini: string; fim: string };
  kpis: { gasto: number; leads: number; cpl: number | null; ctr_pct: number | null };
  dias: Array<{ dia: string; gasto: number; leads: number; cpl: number | null }>;
  criativos: Array<{ nome: string; thumb: string | null; tipo: string | null; gasto: number;
    leads: number; cpl: number | null; ctr_pct: number | null; bookings: number }>;
  criativos_aviso: string | null;
}

export function MktMidiaPage() {
  const hoje = new Date();
  const iso = (dt: Date) => dt.toISOString().slice(0, 10);
  const [ini, setIni] = useState(iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)));
  const [fim, setFim] = useState(iso(hoje));
  const q = useApi<Payload>(`/api/marketing/midia?ini=${ini}&fim=${fim}`);
  const d = q.data;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Mídia Paga<Hint area="marketing/midia" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Gasto/CTR da plataforma · leads e CPL pelos DEALS do Pipedrive (canais pagos) — números batem
          com o CRM · galeria de criativos.
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
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <KpiCard icon={Wallet} tone="primary" title="Gasto no período" value={formatBRL(d.kpis.gasto)} />
            <KpiCard icon={Users} tone="accent" title="Leads" value={formatNumber(d.kpis.leads)} />
            <KpiCard icon={Wallet} tone="muted" title="CPL médio"
              value={d.kpis.cpl != null ? formatBRL(d.kpis.cpl) : "—"} />
            <KpiCard icon={MousePointerClick} tone="muted" title="CTR médio"
              value={d.kpis.ctr_pct != null ? `${d.kpis.ctr_pct.toFixed(2)}%` : "—"} />
          </div>

          <SectionCard hint={<Hint area="marketing/midia" titulo="Gasto por dia" />}
            title="Gasto e leads por dia"
            subtitle="gasto (R$, eixo esquerdo) × leads (eixo direito) — Meta+Google">
            <TimeSeries data={d.dias} xKey="dia" height={260}
              series={[
                { key: "gasto", label: "Gasto/dia (R$)", color: "var(--chart-1)", kind: "area",
                  valueFormatter: (v) => formatBRL(v) },
                { key: "leads", label: "Leads/dia", color: "var(--chart-2)", yAxis: "right" },
              ]} />
          </SectionCard>

          <SectionCard hint={<Hint area="marketing/midia" titulo="CPL por dia" />}
            title="CPL por dia" subtitle="gasto ÷ leads dos deals atribuídos — dia sem lead fica sem ponto">
            <TimeSeries data={d.dias} xKey="dia" height={220}
              series={[{ key: "cpl", label: "CPL/dia (R$)", color: "var(--chart-4)",
                valueFormatter: (v) => formatBRL(v) }]} />
          </SectionCard>

          <SectionCard hint={<Hint area="marketing/midia" titulo="Criativos do período" />}
            title="Criativos do período" subtitle="top 12 por gasto, com métricas do ad-insightify">
            {d.criativos_aviso && <p className="text-sm text-muted-foreground">{d.criativos_aviso}</p>}
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(200px,1fr))" }}>
              {d.criativos.map((c) => (
                <div key={c.nome} className="rounded-xl border border-border bg-card p-3">
                  {c.thumb ? (
                    <img src={c.thumb} loading="lazy" alt=""
                      className="h-[110px] w-full rounded-lg bg-muted object-cover" />
                  ) : (
                    <div className="h-[110px] rounded-lg bg-muted" />
                  )}
                  <div className="mt-2 text-xs font-semibold leading-tight">{c.nome}</div>
                  <div className="mt-1 text-[11px] text-muted-foreground">
                    {c.tipo ?? ""} · gasto {formatBRL(c.gasto)} · {c.leads} leads · CPL{" "}
                    {c.cpl != null ? formatBRL(c.cpl) : "—"} · CTR{" "}
                    {c.ctr_pct != null ? `${c.ctr_pct.toFixed(2)}%` : "—"}
                    {c.bookings ? ` · ${c.bookings} bookings` : ""}
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}
