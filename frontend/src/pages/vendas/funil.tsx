import { CalendarRange, Handshake, Target, Users, Wallet } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { SectionCard } from "@/components/blocks/section-card";
import { Funnel } from "@/components/charts/funnel";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatBRL, formatPct } from "@/lib/format";
import type { VendasFunilPayload } from "@/types/api";

// Vendas · Funil de Fechamento (Lote 3) — view PADRÃO da área. Números
// prontos de /api/vendas/funil (mesmas queries da tela HTML — paridade
// checada). A conversão Oportunidade→Booking (meta 15%) é o win rate
// OFICIAL da área — o Win/Loss referencia esta régua, não inventa outra.

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const numCls = "text-right tabular-nums";

export function VendasFunilPage() {
  const hoje = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const [ini, setIni] = useState(iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)));
  const [fim, setFim] = useState(iso(hoje));
  const q = useApi<VendasFunilPayload>(`/api/vendas/funil?ini=${ini}&fim=${fim}`);
  const d = q.data;
  const naMeta = (d?.kpis.conv_oport_booking_pct ?? 0) >= (d?.kpis.meta_pct ?? 15);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Funil de Fechamento<Hint area="vendas/funil" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Da reunião agendada ao contrato · régua por evento no período (BRT) · funil completo =
          régua OFICIAL do dashboard do time.
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
          <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
            <KpiCard icon={Users} tone="muted" title="Reuniões agendadas"
              value={d.kpis.reunioes.toLocaleString("pt-BR")} subtitle="recebidas da Pré-vendas" />
            <KpiCard icon={Handshake} tone="primary" title="Oportunidades"
              value={d.kpis.oportunidades.toLocaleString("pt-BR")} subtitle="compareceu (Negociação)" />
            <KpiCard icon={Wallet} tone="accent" title="Bookings"
              value={d.kpis.bookings.toLocaleString("pt-BR")}
              subtitle={d.kpis.receita != null ? formatBRL(d.kpis.receita) : undefined} />
            <KpiCard icon={Target} tone={naMeta ? "success" : "destructive"}
              title="Oportunidade → Booking"
              value={d.kpis.conv_oport_booking_pct != null ? formatPct(d.kpis.conv_oport_booking_pct, 1) : "—"}
              subtitle={`métrica central · meta ${formatPct(d.kpis.meta_pct, 0)}`} />
          </div>

          <SectionCard hint={<Hint area="vendas/funil" titulo="Funil completo" />}
            title="Funil completo (Lead → Booking)"
            subtitle="régua oficial do dashboard do time — os mesmos números de Marketing e Pré-vendas · Oportunidade não é coorte, pode superar SQL">
            <Funnel etapas={d.funil.etapas} conversaoTotalPct={d.funil.conversao_total_pct ?? undefined} />
          </SectionCard>

          <div className="grid gap-6 xl:grid-cols-2">
            <SectionCard hint={<Hint area="vendas/funil" titulo="Oportunidades por bundle" />}
              title="Oportunidades por bundle"
              subtitle="oportunidades novas e contratos fechados no período, por plano — planos antigos/exceções pelo nome">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className={thCls}>Bundle</TableHead>
                      <TableHead className={`${thCls} text-right`}>Oportunidades</TableHead>
                      <TableHead className={`${thCls} text-right`}>% do mix</TableHead>
                      <TableHead className={`${thCls} text-right`}>Bookings</TableHead>
                      <TableHead className={`${thCls} text-right`}>Oport→Booking</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.por_bundle.map((b) => (
                      <TableRow key={b.bundle}>
                        <TableCell className="font-medium">{b.bundle}</TableCell>
                        <TableCell className={numCls}>{b.oportunidades}</TableCell>
                        <TableCell className={numCls}>{formatPct(b.mix_pct, 1)}</TableCell>
                        <TableCell className={numCls}>{b.bookings}</TableCell>
                        <TableCell className={numCls}>{b.conv_pct != null ? formatPct(b.conv_pct, 1) : "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </SectionCard>

            <SectionCard hint={<Hint area="vendas/funil" titulo="Tendência Oportunidade → Booking" />}
              title="Tendência Oportunidade → Booking"
              subtitle="6 meses · verde = na meta de 15% · o mês corrente é parcial">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Mês</TableHead>
                    <TableHead className={`${thCls} text-right`}>Oportunidades</TableHead>
                    <TableHead className={`${thCls} text-right`}>Bookings</TableHead>
                    <TableHead className={`${thCls} text-right`}>Conversão</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.tendencia.map((t) => (
                    <TableRow key={t.mes}>
                      <TableCell className="font-medium">{t.mes}</TableCell>
                      <TableCell className={numCls}>{t.oportunidades}</TableCell>
                      <TableCell className={numCls}>{t.bookings}</TableCell>
                      <TableCell className={`${numCls} font-semibold ${t.na_meta ? "text-success" : "text-destructive"}`}>
                        {t.conv_pct != null ? formatPct(t.conv_pct, 1) : "—"} {t.na_meta ? "· na meta" : "· abaixo"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </SectionCard>
          </div>

          <SectionCard hint={<Hint area="vendas/funil" titulo="Conversões por origem × plano" />}
            title="Conversões por origem × plano"
            subtitle="bookings do período por origem do lead e bundle fechado · TX = bookings ÷ leads da origem criados no período">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Origem</TableHead>
                    {d.origem_x_plano.planos.map((p) => (
                      <TableHead key={p} className={`${thCls} text-right`}>{p}</TableHead>
                    ))}
                    <TableHead className={`${thCls} text-right`}>Total</TableHead>
                    <TableHead className={`${thCls} text-right`}>TX lead→booking</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.origem_x_plano.linhas.map((l) => (
                    <TableRow key={l.origem}>
                      <TableCell className="font-medium">{l.origem}</TableCell>
                      {d.origem_x_plano.planos.map((p) => (
                        <TableCell key={p} className={numCls}>{l.por_plano[p] || ""}</TableCell>
                      ))}
                      <TableCell className={`${numCls} font-semibold`}>{l.total}</TableCell>
                      <TableCell className={numCls}>
                        {l.tx_lead_booking_pct != null ? formatPct(l.tx_lead_booking_pct, 1) : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </SectionCard>

          <SectionCard hint={<Hint area="vendas/funil" titulo="Diagnóstico do especialista" />}
            title="Diagnóstico do especialista"
            subtitle={`${d.diagnostico.persona} · gerado por ${d.diagnostico.fonte} — hipótese, não veredito`}>
            <div className="space-y-2">
              {d.diagnostico.itens.map((i) => (
                <p key={i} className="border-t border-border pt-2 text-sm leading-relaxed first:border-t-0 first:pt-0">→ {i}</p>
              ))}
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}
