import { AlertTriangle, ArrowRight, Target, TrendingUp, Users, Wallet } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { SectionCard } from "@/components/blocks/section-card";
import { MetaBar } from "@/components/blocks/meta-bar";
import { Badge } from "@/components/ui/badge";
import { formatBRL, formatNumber, formatPct } from "@/lib/format";

// Central (hub do admin) — /api/central COMPÕE as mesmas funções da tela HTML
// (_hub_stats/_hub_*_stats, _hub_impactos, _hub_lags, _hub_mudancas_itens) e
// os objetivos da semana com o impacto em R$ de cada um. Nenhuma régua nova.

interface Impacto { faixa: [number, number] | null; janela: string | null; premissa: string }
interface Payload {
  stats: { monitored: number; evaluable: number; sev: Record<string, number>;
    mrr_risk: number; mrr_crit: number; non_eval: number };
  marketing: { mes: string; leads: number; leads_meta: number | null; gasto: number;
    cpl: number | null; cpl_alvo: number | null; oport: number; oport_meta: number | null;
    book: number; book_meta: number | null; cac: number | null; verba: number | null; frac: number } | null;
  vendas: { book: number; book_meta: number | null; receita: number; receita_meta: number | null;
    reunioes: number; taxa: number | null; taxa_ant: number | null; pipeline: number;
    leads: number; speed_med: number | null; sem_toque: number; tem_touch: boolean } | null;
  operacoes: { quarter: string; year: number; total: number; ok: number; prog: number;
    atras: number; progresso: number } | null;
  impactos: Record<string, { faixa?: [number, number] | null; premissa?: string } | null>;
  lags: { lead_book: number | null; oport_book: number | null; book_churn: number | null;
    n_lead: number; n_oport: number; n_churn: number };
  mudancas: Array<{ texto: string; url: string }>;
  fontes_paradas: string[];
  prioridades: Array<{ titulo: string; racional: string | null; metric: string | null;
    impacto: Impacto | null;
    acoes: Array<{ team: string; team_label: string; manchete: string; detalhe: string }> }>;
}

const brl = (v: number | null | undefined) => (v == null ? "—" : formatBRL(v));
const faixaBRL = (f: [number, number] | null | undefined) =>
  f ? `${formatBRL(f[0])} – ${formatBRL(f[1])}` : null;

export function CentralPage() {
  const q = useApi<Payload>("/api/central");
  const d = q.data;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-2xl font-bold tracking-tight">Central</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          O estado da empresa numa tela: as prioridades da semana com o impacto estimado, o placar de
          cada área e o que mudou desde ontem.
        </p>
      </header>

      {q.loading && <LoadingSkeleton rows={6} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && (
        <>
          {d.fontes_paradas.length > 0 && (
            <div className="flex items-start gap-2 rounded-xl border border-warning/40 bg-card p-4 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              <span>
                <b>Fonte de dados parada:</b> {d.fontes_paradas.slice(0, 3).join(" · ")} — diagnósticos
                podem estar desatualizados.{" "}
                <a href="/admin" className="text-primary hover:underline">ver Saúde das integrações</a>
              </span>
            </div>
          )}

          {d.prioridades.length > 0 && (
            <SectionCard title="Prioridades da semana"
              subtitle="objetivos confirmados da empresa, o impacto estimado em R$ de cada um e o que cada área faz por ele · estimativas indicativas, não promessas">
              <div className="space-y-4">
                {d.prioridades.map((p, i) => (
                  <div key={p.titulo} className="rounded-xl border border-border p-4">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <b className="text-sm">{i + 1}. {p.titulo}</b>
                      {p.impacto?.faixa ? (
                        <Badge variant="outline" className="border-primary/50 text-primary">
                          impacto {faixaBRL(p.impacto.faixa)}
                        </Badge>
                      ) : (
                        // Otávio 22/07: o card sem estimativa PERDEU essa
                        // informação — ausência de número não é ausência de item
                        <Badge variant="outline" className="text-muted-foreground">
                          impacto não estimado
                        </Badge>
                      )}
                    </div>
                    {p.racional && <p className="mt-1 text-sm text-muted-foreground">{p.racional}</p>}
                    {p.impacto?.premissa && (
                      <details className="mt-1">
                        <summary className="cursor-pointer text-xs text-primary">como estimamos o valor</summary>
                        <p className="mt-1 text-xs text-muted-foreground">{p.impacto.premissa}</p>
                      </details>
                    )}
                    {p.acoes.length > 0 && (
                      <div className="mt-2 space-y-1.5">
                        {p.acoes.map((a, j) => (
                          <div key={`${p.titulo}-${j}`} className="border-t border-border pt-1.5 text-sm">
                            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{a.team_label}</span>
                            <div className="font-medium">{a.manchete}</div>
                            {a.detalhe && <div className="text-xs text-muted-foreground">{a.detalhe}</div>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs text-muted-foreground">
                <a href="/semana" className="text-primary hover:underline">ver Ações da Semana →</a>
              </p>
            </SectionCard>
          )}

          <SectionCard title="Growth / Assessoria"
            subtitle="carteira monitorada, risco e MRR exposto — a régua do MRR é a de contas COM ALERTA ABERTO">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <KpiCard icon={Users} tone="muted" title="Contas monitoradas"
                value={formatNumber(d.stats.monitored)}
                subtitle={`${d.stats.evaluable} avaliáveis${d.stats.non_eval ? ` · ${d.stats.non_eval} sem cobertura` : ""}`} />
              <KpiCard icon={AlertTriangle} tone="destructive" title="Alertas críticos"
                value={formatNumber(d.stats.sev?.critico ?? 0)}
                subtitle={`${d.stats.sev?.alto ?? 0} alto · ${d.stats.sev?.atencao ?? 0} atenção`} />
              <KpiCard icon={Wallet} tone="warning" title="MRR com alerta aberto"
                value={brl(d.stats.mrr_risk)} />
              <KpiCard icon={Wallet} tone="destructive" title="MRR em risco crítico"
                value={brl(d.stats.mrr_crit)} />
            </div>
            <p className="mt-3 text-xs">
              <a href="/growth?view=alertas" className="text-primary hover:underline">fila de retenção →</a>
            </p>
          </SectionCard>

          {d.marketing && (
            <SectionCard title={`Marketing — ${d.marketing.mes}`}
              subtitle={`ritmo do mês: ${(d.marketing.frac * 100).toFixed(0)}% decorrido`}>
              <div className="grid gap-4 md:grid-cols-2">
                <MetaBar value={d.marketing.leads} target={d.marketing.leads_meta ?? 0}
                  valueLabel={`Leads: ${formatNumber(d.marketing.leads)}`}
                  targetLabel={`meta ${formatNumber(d.marketing.leads_meta ?? 0)}`}
                  pacePct={d.marketing.frac * 100} />
                <MetaBar value={d.marketing.oport} target={d.marketing.oport_meta ?? 0}
                  valueLabel={`Oportunidades: ${formatNumber(d.marketing.oport)}`}
                  targetLabel={`meta ${formatNumber(d.marketing.oport_meta ?? 0)}`}
                  pacePct={d.marketing.frac * 100} />
              </div>
              <div className="mt-3 grid gap-4 md:grid-cols-3">
                <KpiCard icon={Wallet} tone="muted" title="Gasto de mídia" value={brl(d.marketing.gasto)}
                  subtitle={d.marketing.verba ? `verba ${brl(d.marketing.verba)}` : undefined} />
                <KpiCard icon={Target} tone={d.marketing.cpl_alvo && d.marketing.cpl && d.marketing.cpl <= d.marketing.cpl_alvo ? "success" : "warning"}
                  title="CPL" value={brl(d.marketing.cpl)}
                  subtitle={d.marketing.cpl_alvo ? `alvo ${brl(d.marketing.cpl_alvo)}` : undefined} />
                <KpiCard icon={Wallet} tone="muted" title="CAC" value={brl(d.marketing.cac)} />
              </div>
              <p className="mt-3 text-xs">
                <a href="/marketing?view=visao" className="text-primary hover:underline">abrir Marketing →</a>
              </p>
            </SectionCard>
          )}

          {d.vendas && (
            <SectionCard title="Pré-vendas e Vendas"
              subtitle="do lead à reunião e da reunião ao contrato — régua oficial do funil">
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <KpiCard icon={Users} tone="muted" title="Reuniões" value={formatNumber(d.vendas.reunioes)}
                  subtitle={d.vendas.tem_touch && d.vendas.speed_med != null
                    ? `1º contato mediano ${d.vendas.speed_med.toFixed(0)} min` : undefined}
                  caveat={d.vendas.sem_toque ? `${d.vendas.sem_toque} lead(s) sem 1º contato registrado` : undefined} />
                <KpiCard icon={TrendingUp}
                  tone={d.vendas.taxa != null && d.vendas.taxa_ant != null && d.vendas.taxa >= d.vendas.taxa_ant ? "success" : "warning"}
                  title="Oportunidade → Booking"
                  value={d.vendas.taxa != null ? formatPct(d.vendas.taxa * 100, 1) : "—"}
                  subtitle={d.vendas.taxa_ant != null ? `mês anterior ${formatPct(d.vendas.taxa_ant * 100, 1)}` : undefined} />
                <KpiCard icon={Target} tone="primary" title="Bookings"
                  value={formatNumber(d.vendas.book)}
                  subtitle={d.vendas.book_meta ? `meta ${formatNumber(d.vendas.book_meta)}` : undefined} />
                <KpiCard icon={Wallet} tone="accent" title="Receita"
                  value={brl(d.vendas.receita)}
                  subtitle={d.vendas.receita_meta ? `meta ${brl(d.vendas.receita_meta)}` : undefined} />
              </div>
              <p className="mt-3 text-xs">
                <a href="/vendas?view=funil" className="text-primary hover:underline">Funil de Fechamento →</a>
                {" · "}
                <a href="/vendas?view=ponte" className="text-primary hover:underline">Ponte PV → Vendas →</a>
              </p>
            </SectionCard>
          )}

          {d.operacoes && (
            <SectionCard title={`Operações — ${d.operacoes.quarter} ${d.operacoes.year}`}
              subtitle="iniciativas do trimestre sincronizadas do Notion">
              <MetaBar value={d.operacoes.ok} target={d.operacoes.total}
                valueLabel={`${d.operacoes.ok} concluída(s) de ${d.operacoes.total}`}
                targetLabel={`${d.operacoes.prog} em andamento · ${d.operacoes.atras} atrasada(s)`} />
              <p className="mt-3 text-xs">
                <a href="/operacoes" className="text-primary hover:underline">abrir Operações →</a>
              </p>
            </SectionCard>
          )}

          {d.mudancas.length > 0 && (
            <SectionCard hint={<Hint area="growth/contas" titulo="Contas por risco" />}
              title="O que mudou desde ontem"
              subtitle="deltas das últimas 24h / última rodada — clique para abrir a área">
              <div className="space-y-1">
                {d.mudancas.map((m) => (
                  <a key={m.texto} href={m.url}
                    className="flex items-start gap-2 border-t border-border py-2 text-sm first:border-t-0 hover:bg-muted/40">
                    <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                    <span>{m.texto}</span>
                  </a>
                ))}
              </div>
            </SectionCard>
          )}

          <SectionCard title="Defasagens medidas"
            subtitle="quanto tempo uma correção numa área leva para aparecer na outra — medianas do histórico; sem base suficiente, a tela diz">
            <div className="grid gap-4 md:grid-cols-3 text-sm">
              {([["Lead → booking", d.lags.lead_book, d.lags.n_lead],
                 ["Oportunidade → booking", d.lags.oport_book, d.lags.n_oport],
                 ["Booking → churn", d.lags.book_churn, d.lags.n_churn]] as const).map(([rot, v, n]) => (
                <div key={rot} className="rounded-lg border border-border p-3">
                  <div className="font-display text-xl font-bold tabular-nums">
                    {v != null ? `${v.toFixed(0)} d` : "sem base"}
                  </div>
                  <div className="text-xs text-muted-foreground">{rot}{n ? ` · ${n} casos` : ""}</div>
                </div>
              ))}
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}
