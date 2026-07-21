import { CalendarRange, Clock, PhoneMissed, Target, Timer, Users } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { CaveatChip } from "@/components/caveat";
import { SectionCard } from "@/components/blocks/section-card";
import { Funnel } from "@/components/charts/funnel";
import { BarListH } from "@/components/charts/bar-list-h";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatPct } from "@/lib/format";
import type { PrevendasPayload } from "@/types/api";

// Pré-vendas — Funil de Qualificação + Speed-to-Lead numa página (desenho do
// redesenho aprovado). Régua OFICIAL do funil (bate com o Pipedrive); TODO
// agregado vem de /api/prevendas — o frontend só formata.

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const thR = `${thCls} text-right`;

function Det({ resumo, children }: { resumo: string; children: React.ReactNode }) {
  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-xs font-medium text-primary">{resumo}</summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

export function PrevendasPage() {
  const hoje = new Date();
  const iniMes = new Date(hoje.getFullYear(), hoje.getMonth(), 1);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const [ini, setIni] = useState(iso(iniMes));
  const [fim, setFim] = useState(iso(hoje));
  const q = useApi<PrevendasPayload>(`/api/prevendas?ini=${ini}&fim=${fim}`);
  const d = q.data;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Qualificação & Speed-to-Lead<Hint area="prevendas/funil" titulo="_intro" /><Hint area="prevendas/speed" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Régua oficial do dashboard do time — os números batem com o Pipedrive. O trabalho de
          Pré-vendas vai do Lead ao SQL; Oportunidade e Booking mostram o destino final.
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
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
            <KpiCard icon={Users} tone="primary" title="Leads" value={d.kpis.leads.toLocaleString("pt-BR")} />
            <KpiCard icon={Target} tone="accent" title="SQL"
              value={d.kpis.sql.toLocaleString("pt-BR")}
              subtitle={d.kpis.taxa_lead_sql_pct != null ? `${formatPct(d.kpis.taxa_lead_sql_pct, 1)} dos leads` : undefined} />
            <KpiCard icon={Timer} tone={d.kpis.speed_mediano_min != null && d.kpis.speed_mediano_min <= 15 ? "success" : "warning"}
              title="1º contato mediano"
              value={d.kpis.speed_mediano_min != null ? `${Math.round(d.kpis.speed_mediano_min)} min` : "—"}
              subtitle="referência de mercado: <15 min" />
            <KpiCard icon={Clock} tone="muted" title="Dentro de 15 min"
              value={d.kpis.pct_15min != null ? `${d.kpis.pct_15min}%` : "—"} />
            <KpiCard icon={Clock} tone="muted" title="p75"
              value={d.kpis.p75_min != null ? `${Math.round(d.kpis.p75_min)} min` : "—"} />
            <KpiCard icon={PhoneMissed} tone="destructive" title="Sem contato"
              value={d.kpis.sem_contato.toLocaleString("pt-BR")}
              subtitle="fila a zerar — lead não tocado esfria" />
          </div>

          <SectionCard hint={<Hint area="prevendas/funil" titulo="Funil completo" />} title="Funil completo (Lead → Booking)"
            subtitle={`régua oficial · conversão total ${d.funil.conversao_total_pct != null ? formatPct(d.funil.conversao_total_pct, 1) : "—"} (vem do payload) · pílula = conversão sobre a etapa anterior`}>
            <Funnel etapas={d.funil.etapas.map((e) => ({
              key: e.key, label: e.label, volume: e.volume,
              conversao_da_anterior_pct: e.conversao_da_anterior_pct,
            }))} />
          </SectionCard>

          <div className="grid gap-6 lg:grid-cols-2">
            <SectionCard hint={<Hint area="prevendas/funil" titulo="Conversão por dia de chegada do lead" />} title="Conversão por dia de chegada do lead"
              subtitle="taxa de agendamento pelo dia em que o lead entrou (coorte) — cor E rótulo marcam melhor/pior">
              <BarListH
                height={Math.max(200, d.dias.length * 40)}
                width={130}
                data={d.dias.map((x) => ({
                  label: x.dia_label + (x.best ? " (melhor)" : x.worst ? " (pior)" : ""),
                  value: x.taxa_pct ?? 0, _x: x,
                }))}
                itemColor={(it) => (it as { _x: { best: boolean; worst: boolean } })._x.best
                  ? "var(--success)" : (it as { _x: { worst: boolean } })._x.worst ? "var(--destructive)" : undefined}
                color="var(--chart-2)"
                valueLabel={(v) => formatPct(v, 1)}
                tooltipFormatter={(v, it) => {
                  const x = (it as { _x: { leads: number; agendaram: number } })._x;
                  return [`${x.agendaram}/${x.leads} leads`, formatPct(v, 1)];
                }}
              />
            </SectionCard>

            <SectionCard hint={<Hint area="prevendas/funil" titulo="Qualidade do lead por origem" />} title="Qualidade do lead por origem"
              subtitle="taxa lead→reunião por canal — realimenta a segmentação do Marketing · mínimo 5 leads">
              <BarListH
                height={Math.max(200, d.origens.length * 40)}
                width={170}
                data={[...d.origens].sort((a, b) => b.taxa_pct - a.taxa_pct).map((o) => ({
                  label: o.origem + (o.amostra_pequena ? " *" : ""), value: o.taxa_pct, _o: o,
                }))}
                valueLabel={(v) => formatPct(v, 1)}
                tooltipFormatter={(v, it) => {
                  const o = (it as { _o: { reunioes: number; leads: number; amostra_pequena: boolean } })._o;
                  return [`${o.reunioes}/${o.leads} leads${o.amostra_pequena ? " · amostra pequena" : ""}`, formatPct(v, 1)];
                }}
              />
              {d.origens.some((o) => o.amostra_pequena) && (
                <div className="mt-2"><CaveatChip text="* = menos de 8 leads — amostra pequena, interpretar com cautela" /></div>
              )}
            </SectionCard>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <SectionCard hint={<Hint area="prevendas/speed" titulo="Velocidade do 1º contato × conversão" />} title="Velocidade do 1º contato × conversão"
              subtitle="a prova com dado próprio de quanto custa lead esperando (coorte do período)">
              {d.tem_first_touch ? (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-muted/40 hover:bg-muted/40">
                        <TableHead className={thCls}>1º contato em</TableHead>
                        <TableHead className={thR}>Leads</TableHead>
                        <TableHead className={thR}>Agendaram</TableHead>
                        <TableHead className={thR}>Taxa</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {d.velocidade.faixas.map((f) => (
                        <TableRow key={f.ordem}>
                          <TableCell className="font-medium">{f.faixa}</TableCell>
                          <TableCell className="text-right tabular-nums">{f.leads}</TableCell>
                          <TableCell className="text-right tabular-nums">{f.agendaram}</TableCell>
                          <TableCell className="text-right tabular-nums">{f.taxa_pct != null ? formatPct(f.taxa_pct, 1) : "—"}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {d.velocidade.razao_15min_vs_24h != null && d.velocidade.razao_15min_vs_24h > 1.2 && (
                    <p className="mt-2 text-sm text-muted-foreground">
                      Lead contatado em até 15 min agenda <b className="text-foreground">{d.velocidade.razao_15min_vs_24h}× mais</b>{" "}
                      que lead que esperou 24h+ — a fila sem contato é a maior alavanca da área.
                    </p>
                  )}
                </>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Dados de 1º contato chegam na próxima rodada de coleta — esta visão acende sozinha.
                </p>
              )}
            </SectionCard>

            <SectionCard hint={<Hint area="prevendas/funil" titulo="Motivos de desqualificação" />} title="Motivos de desqualificação"
              subtitle={`perdidos antes do handoff — Pareto · ${d.sem_motivo_desq} sem motivo preenchido`}>
              {d.desq.length ? (
                <BarListH
                  height={Math.max(200, d.desq.length * 44)}
                  width={230}
                  data={d.desq.map((m) => ({ label: m.motivo, value: m.deals }))}
                  color="var(--destructive)"
                />
              ) : (
                <p className="text-sm text-muted-foreground">Sem perdas no período.</p>
              )}
              {d.sem_motivo_desq > 0 && (
                <div className="mt-2"><CaveatChip text={`${d.sem_motivo_desq} desqualificação(ões) sem motivo — cobrar o registro no Pipedrive`} /></div>
              )}
            </SectionCard>
          </div>

          <SectionCard title="Evolução mensal (6 meses)"
            subtitle="taxa lead→SQL (régua oficial; retroativa — meses antigos são mais confiáveis) e mediana do 1º contato ('—' = mês anterior à coleta) · a trajetória, não a foto">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableHead className={thCls}>Mês</TableHead>
                  <TableHead className={thR}>Leads</TableHead>
                  <TableHead className={thR}>SQL</TableHead>
                  <TableHead className={thR}>Lead→SQL</TableHead>
                  <TableHead className={thR}>Speed (med.)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.evolucao.map((m) => (
                  <TableRow key={m.mes}>
                    <TableCell className="font-medium">{m.mes}</TableCell>
                    <TableCell className="text-right tabular-nums">{m.leads}</TableCell>
                    <TableCell className="text-right tabular-nums">{m.sql}</TableCell>
                    <TableCell className="text-right tabular-nums">{m.taxa_pct != null ? formatPct(m.taxa_pct, 1) : "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{m.speed_min != null ? `${Math.round(m.speed_min)} min` : "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </SectionCard>

          <SectionCard hint={<Hint area="prevendas/funil" titulo="Diagnóstico do especialista" />}
            title="Diagnóstico do especialista"
            subtitle={`${d.diagnostico.persona} · regras determinísticas — hipóteses para investigar, não veredito`}>
            {d.diagnostico.itens.length ? (
              <ul className="space-y-2">
                {d.diagnostico.itens.map((i, ix) => (
                  <li key={ix} className="border-t border-border pt-2 text-sm leading-relaxed first:border-t-0 first:pt-0">→ {i}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Sem sinal forte no período.</p>
            )}
          </SectionCard>

          <SectionCard title="Abordagem e pessoas"
            subtitle="taxa por tipo de 1º contato (mín. 5 leads) · speed por responsável e por origem (mín. 3 leads)">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableHead className={thCls}>Tipo de 1º contato</TableHead>
                  <TableHead className={thR}>Leads</TableHead>
                  <TableHead className={thR}>Agendaram</TableHead>
                  <TableHead className={thR}>Taxa</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.tipos_contato.map((t) => (
                  <TableRow key={t.tipo}>
                    <TableCell className="font-medium">{t.tipo}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.leads}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.agendaram}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.taxa_pct != null ? formatPct(t.taxa_pct, 1) : "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Det resumo="ver speed por responsável do 1º contato e por origem">
              {[{ t: "Por responsável", rows: d.por_responsavel }, { t: "Por origem", rows: d.por_origem_speed }].map((g) => (
                <div key={g.t} className="mb-4">
                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{g.t}</div>
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-muted/40 hover:bg-muted/40">
                        <TableHead className={thCls}>{g.t.replace("Por ", "")}</TableHead>
                        <TableHead className={thR}>Leads</TableHead>
                        <TableHead className={thR}>Mediana</TableHead>
                        <TableHead className={thR}>≤15 min</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {g.rows.map((r) => (
                        <TableRow key={r.nome}>
                          <TableCell>{r.nome}</TableCell>
                          <TableCell className="text-right tabular-nums">{r.leads}</TableCell>
                          <TableCell className="text-right tabular-nums">{Math.round(r.mediana_min)} min</TableCell>
                          <TableCell className="text-right tabular-nums">{r.pct_15min}%</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ))}
            </Det>
          </SectionCard>
        </>
      )}
    </div>
  );
}
