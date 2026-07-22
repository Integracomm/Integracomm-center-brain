import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { MetaBar } from "@/components/blocks/meta-bar";
import { formatBRL, formatNumber, formatPct } from "@/lib/format";

// Marketing · Visão Geral (Lote 4) — /api/marketing/visao embrulha o compute
// da tela HTML (ranking_canais + mkt_goals + funil vs meta). Paridade checada.

interface Kpi { label: string; valor: number | null; kind: string; var_pct: number | null; inverso: boolean }
interface Payload {
  periodo: { ini: string; fim: string };
  kpis: Kpi[];
  funil_vs_meta: { mes: string; ritmo_pct: number;
    etapas: Array<{ etapa: string; real: number; meta: number | null; pct_meta: number | null }> } | null;
  progresso: Array<{ plano: string; real: number; meta: number; pct: number | null; destaque: boolean }>;
  gap: Array<{ plano: string; faltam_bookings: number; leads_necessarios: number }>;
  conv_lead_booking_pct: number | null;
}

const fmt = (v: number | null, kind: string) =>
  v == null ? "—" : kind === "brl" ? formatBRL(v) : formatNumber(Math.round(v));

export function MktVisaoPage() {
  const q = useApi<Payload>("/api/marketing/visao");
  const d = q.data;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Visão Geral<Hint area="marketing/visao" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">Mês atual (até hoje) vs mês anterior.</p>
      </header>
      {q.loading && <LoadingSkeleton rows={6} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
            {d.kpis.map((k) => {
              const bom = k.var_pct != null && Math.abs(k.var_pct) >= 1
                ? (k.var_pct > 0) !== k.inverso : null;
              return (
                <div key={k.label} className="rounded-xl border border-border bg-card p-4">
                  <div className="font-display text-xl font-bold tabular-nums">{fmt(k.valor, k.kind)}</div>
                  <div className="text-xs text-muted-foreground">{k.label}</div>
                  {k.var_pct != null && (
                    <div className={`mt-1 text-xs font-medium ${bom == null ? "text-muted-foreground" : bom ? "text-success" : "text-destructive"}`}>
                      {k.var_pct >= 0 ? "+" : ""}{k.var_pct.toFixed(0)}% vs mês ant.
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {d.funil_vs_meta && (
            <SectionCard hint={<Hint area="marketing/visao" titulo="Funil do mês vs meta" />}
              title={`Funil do mês vs meta (${d.funil_vs_meta.mes})`}
              subtitle={`metas de volume da planilha do Marketing · marcador = ritmo esperado (${d.funil_vs_meta.ritmo_pct.toFixed(0)}% do mês decorrido)`}>
              <div className="space-y-4">
                {d.funil_vs_meta.etapas.map((e) => (
                  <MetaBar key={e.etapa} value={e.real} target={e.meta ?? 0}
                    valueLabel={`${e.etapa}: ${formatNumber(e.real)}`}
                    targetLabel={`meta ${formatNumber(Math.round(e.meta ?? 0))}${e.pct_meta != null ? ` · ${formatPct(e.pct_meta, 0)}` : ""}`}
                    pacePct={d.funil_vs_meta!.ritmo_pct} />
                ))}
              </div>
            </SectionCard>
          )}

          <SectionCard hint={<Hint area="marketing/visao" titulo="Progresso vs meta do mês" />}
            title="Progresso vs meta do mês"
            subtitle="metas da planilha financeira · bookings fechados no Pipedrive · B3-B5 em destaque">
            <div className="space-y-4">
              {d.progresso.map((p) => (
                <MetaBar key={p.plano} value={p.real} target={p.meta}
                  valueLabel={`${p.plano}${p.destaque ? " ★" : ""}: ${p.real}`}
                  targetLabel={`meta ${p.meta.toFixed(0)}${p.pct != null ? ` · ${formatPct(p.pct, 0)}` : ""}`} />
              ))}
            </div>
          </SectionCard>

          {d.gap.length > 0 && (
            <SectionCard hint={<Hint area="marketing/visao" titulo="Gap para a meta (B3-B5)" />}
              title="Gap para a meta (B3-B5)"
              subtitle={`quantos leads ainda são necessários no ritmo de conversão do mês (${d.conv_lead_booking_pct != null ? formatPct(d.conv_lead_booking_pct, 1) : "—"})`}>
              <ul className="space-y-1.5 text-sm">
                {d.gap.map((g) => (
                  <li key={g.plano} className="border-t border-border pt-1.5 first:border-t-0 first:pt-0">
                    <b>{g.plano}</b>: faltam {g.faltam_bookings.toFixed(0)} bookings ≈{" "}
                    <b>{formatNumber(g.leads_necessarios)} leads</b> no ritmo atual
                  </li>
                ))}
                <li className="border-t border-border pt-1.5 text-muted-foreground">
                  Alavancas Q3: Indicações convertem sem custo de mídia (aba Origem de Leads); LinkedIn é o
                  canal natural do público B3-B5 — padronizar utm_source=linkedin antes de ativar.
                </li>
              </ul>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}
