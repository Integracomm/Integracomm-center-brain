import { CalendarRange } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { SectionCard } from "@/components/blocks/section-card";
import { Funnel } from "@/components/charts/funnel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Target, TrendingUp } from "lucide-react";
import { formatNumber, formatPct } from "@/lib/format";

// Marketing · Funil de Prospecção (Lote 4) — /api/marketing/funil embrulha a
// régua OFICIAL (_funil_oficial). Metas de taxa editáveis: POST no MESMO
// endpoint da tela HTML (/marketing/funil-metas) e refetch.

interface Etapa {
  etapa: string; definicao: string; n: number; meta_qtde: number | null;
  taxa_pct: number | null; delta_pp: number | null; meta_taxa_pct: number | null;
}
interface Payload {
  periodo: { ini: string; fim: string; prev_ini: string; prev_fim: string };
  mes_ref: string; mes_ref_iso: string;
  funil: { etapas: Array<{ key: string; label: string; volume: number; conversao_da_anterior_pct: number | null }>;
    receita_bookings: number | null; conversao_total_pct: number | null };
  etapas: Etapa[]; leads: number; bookings: number;
  kpis: { conv_lead_booking_pct: number | null; conv_necessaria_pct: number | null;
    meta_bookings_mes: number; taxa_mql_booking_pct: number | null;
    meta_mql_booking_pct: number | null; mql: number };
  metas_taxa_pct: Record<string, number>;
  sugestoes: string[];
}

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const numCls = "text-right tabular-nums";
const ETAPAS_META = ["MQL", "SAL", "SQL", "Oportunidade", "Booking"];

export function MktFunilPage() {
  const hoje = new Date();
  const iso = (dt: Date) => dt.toISOString().slice(0, 10);
  const [ini, setIni] = useState(iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)));
  const [fim, setFim] = useState(iso(hoje));
  const q = useApi<Payload>(`/api/marketing/funil?ini=${ini}&fim=${fim}`);
  const d = q.data;
  const [metas, setMetas] = useState<Record<string, string> | null>(null);
  const [salvando, setSalvando] = useState(false);
  const metasAtuais = metas ?? Object.fromEntries(
    ETAPAS_META.map((e) => [e, d?.metas_taxa_pct[e] != null ? String(d.metas_taxa_pct[e]) : ""]));

  const salvarMetas = async () => {
    if (!d) return;
    setSalvando(true);
    const body = new URLSearchParams({ mes: d.mes_ref_iso, ini, fim });
    ETAPAS_META.forEach((e, i) => body.set(`meta_${i}`, metasAtuais[e] ?? ""));
    await fetch("/marketing/funil-metas", { method: "POST", body, credentials: "same-origin" });
    setSalvando(false); setMetas(null); q.refetch();
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Funil de Prospecção<Hint area="marketing/funil" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Régua OFICIAL do dashboard do time · Lead = criados no período · MQL/SAL descontam
          desqualificados · SQL = na mão de closer · Oportunidade = Dia Oportunidade (não é coorte) ·
          Booking = ganhos.
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
          {d.kpis.conv_necessaria_pct != null && (
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <KpiCard icon={TrendingUp} tone="primary" title="Conversão lead→booking"
                value={d.kpis.conv_lead_booking_pct != null ? formatPct(d.kpis.conv_lead_booking_pct, 1) : "—"} />
              <KpiCard icon={Target}
                tone={(d.kpis.conv_lead_booking_pct ?? 0) >= d.kpis.conv_necessaria_pct ? "success" : "destructive"}
                title="Necessária p/ a meta"
                value={formatPct(d.kpis.conv_necessaria_pct, 1)}
                subtitle={`meta: ${d.kpis.meta_bookings_mes.toFixed(0)} bookings/mês`} />
              <KpiCard icon={TrendingUp}
                tone={d.kpis.meta_mql_booking_pct == null ? "muted"
                  : (d.kpis.taxa_mql_booking_pct ?? 0) >= d.kpis.meta_mql_booking_pct ? "success" : "destructive"}
                title="MQL → Booking (composta)"
                value={d.kpis.taxa_mql_booking_pct != null ? formatPct(d.kpis.taxa_mql_booking_pct, 1) : "—"}
                subtitle={d.kpis.meta_mql_booking_pct != null ? `meta ${formatPct(d.kpis.meta_mql_booking_pct, 1)}` : `${d.bookings}/${d.kpis.mql} MQLs`} />
              <KpiCard icon={Target} tone="accent" title="Bookings · Leads"
                value={`${d.bookings} · ${formatNumber(d.leads)}`} subtitle="coorte do período" />
            </div>
          )}

          <SectionCard hint={<Hint area="marketing/funil" titulo="Funil" />}
            title="Funil"
            subtitle={`largura proporcional ao volume · pílula = conversão sobre a etapa anterior · conversão total ${d.funil.conversao_total_pct != null ? formatPct(d.funil.conversao_total_pct, 1) : "—"}`}>
            <Funnel etapas={d.funil.etapas} conversaoTotalPct={d.funil.conversao_total_pct ?? undefined} />
          </SectionCard>

          <SectionCard hint={<Hint area="marketing/funil" titulo="Taxas por etapa" />}
            title="Taxas por etapa"
            subtitle={`vs período anterior equivalente · “Meta qtde” = volume planejado do mês (${d.mes_ref})`}>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Etapa</TableHead>
                    <TableHead className={`${thCls} text-right`}>Deals</TableHead>
                    <TableHead className={`${thCls} text-right`}>Meta qtde (mês)</TableHead>
                    <TableHead className={`${thCls} text-right`}>Conversão da etapa</TableHead>
                    <TableHead className={`${thCls} text-right`}>Meta taxa</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.etapas.map((e) => (
                    <TableRow key={e.etapa} title={e.definicao}>
                      <TableCell className="font-medium">{e.etapa}</TableCell>
                      <TableCell className={numCls}>{formatNumber(e.n)}</TableCell>
                      <TableCell className={`${numCls} text-muted-foreground`}>{e.meta_qtde != null ? e.meta_qtde.toFixed(0) : "—"}</TableCell>
                      <TableCell className={numCls}>
                        {e.taxa_pct != null ? formatPct(e.taxa_pct, 1) : "—"}
                        {e.delta_pp != null && (
                          <span className={`ml-1 text-[10px] ${e.delta_pp >= 0 ? "text-success" : "text-destructive"}`}>
                            ({e.delta_pp >= 0 ? "+" : ""}{e.delta_pp.toFixed(1)}pp)
                          </span>
                        )}
                      </TableCell>
                      <TableCell className={`${numCls} ${e.meta_taxa_pct != null && e.taxa_pct != null ? (e.taxa_pct >= e.meta_taxa_pct ? "text-success" : "text-destructive") : ""}`}>
                        {e.meta_taxa_pct != null ? formatPct(e.meta_taxa_pct, 1) : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                  <TableRow className="border-t-2">
                    <TableCell className="font-semibold" title="taxa fim a fim: de todo MQL, quantos viram contrato">
                      MQL → Booking <span className="text-[10px] font-normal text-muted-foreground">(composta)</span>
                    </TableCell>
                    <TableCell className={numCls}>{d.bookings}<span className="text-muted-foreground">/{d.kpis.mql}</span></TableCell>
                    <TableCell className={`${numCls} text-muted-foreground`}>—</TableCell>
                    <TableCell className={`${numCls} font-semibold`}>
                      {d.kpis.taxa_mql_booking_pct != null ? formatPct(d.kpis.taxa_mql_booking_pct, 1) : "—"}
                    </TableCell>
                    <TableCell className={`${numCls} ${d.kpis.meta_mql_booking_pct != null && d.kpis.taxa_mql_booking_pct != null ? (d.kpis.taxa_mql_booking_pct >= d.kpis.meta_mql_booking_pct ? "text-success" : "text-destructive") : ""}`}>
                      {d.kpis.meta_mql_booking_pct != null ? formatPct(d.kpis.meta_mql_booking_pct, 1) : "—"}
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>
          </SectionCard>

          <SectionCard hint={<Hint area="marketing/funil" titulo="Metas de taxa do mês" />}
            title={`Metas de taxa do mês (${d.mes_ref})`}
            subtitle="conversão-alvo por etapa, em % — pré-preenchidas pela planilha; o que salvar aqui prevalece">
            <div className="flex flex-wrap items-end gap-3">
              {ETAPAS_META.map((e) => (
                <label key={e} className="text-xs text-muted-foreground">
                  {e}
                  <Input type="number" step="0.1" min="0" max="100" className="mt-1 w-[90px]"
                    value={metasAtuais[e] ?? ""} placeholder="%"
                    onChange={(ev) => setMetas({ ...metasAtuais, [e]: ev.target.value })} />
                </label>
              ))}
              <Button onClick={salvarMetas} disabled={salvando}>{salvando ? "Salvando…" : "Salvar metas"}</Button>
            </div>
          </SectionCard>

          {d.sugestoes.length > 0 && (
            <SectionCard hint={<Hint area="marketing/funil" titulo="Como alcançar a meta" />}
              title="Como alcançar a meta"
              subtitle="sugestões determinísticas sobre a etapa de maior perda — hipótese, não veredito">
              <div className="space-y-2">
                {d.sugestoes.map((s) => (
                  <p key={s} className="border-t border-border pt-2 text-sm leading-relaxed first:border-t-0 first:pt-0">→ {s}</p>
                ))}
              </div>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}
