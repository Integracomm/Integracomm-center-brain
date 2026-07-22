import { AlertTriangle, ArrowRight } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { MetaBar } from "@/components/blocks/meta-bar";
import { TimeSeries } from "@/components/charts/time-series";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatBRL, formatNumber, formatPct } from "@/lib/format";

// Financeiro · Planejamento × Realizado (Lote 5) — /api/financeiro/visao
// embrulha o compute da tela HTML (planilha de planejamento + _funil_oficial
// ao vivo). Réguas preservadas: mês corrente = AO VIVO, passados = planilha,
// futuros = meta; verde/vermelho compara com o RITMO do mês, não com 100%.

interface Linha {
  rotulo: string; kind: string; valores: Array<number | null>;
  atual?: number | null; link?: { url: string; dica: string } | null;
}
interface Payload {
  sem_planilha: boolean;
  hoje: string; dia: number; mes_label: string; ritmo_pct: number;
  cards: Array<{ rotulo: string; real: number | null; meta: number | null; kind: string;
    pct: number | null; no_ritmo: boolean | null; fonte: string }>;
  desvios: Array<{ gap: number; texto: string; causa: string; url: string }>;
  recebimento: Array<{ mes: string; total: number | null; recorrente: number | null;
    pct_recorrente: number | null; projecao: boolean; atual: boolean }>;
  bookings_mes: Array<{ mes: string; real: number | null; meta: number | null;
    no_ritmo: boolean | null; sublabel: string; futuro: boolean; atual: boolean }>;
  saude: Array<{ mes: string; inadimplencia_pct: number | null; churn_pct: number | null; alvo: boolean }>;
  historico: { meses: string[]; linhas: Linha[]; destaque: string[] };
  metas: { meses: string[]; linhas: Linha[]; destaque: string[] };
}

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const numCls = "text-right tabular-nums";
const val = (v: number | null, kind: string) =>
  v == null ? "—" : kind === "brl" ? formatBRL(v) : kind === "pct" ? formatPct(v * 100, 1) : formatNumber(Math.round(v));

function Tabela({ meses, linhas, destaque, comAtual }: {
  meses: string[]; linhas: Linha[]; destaque: string[]; comAtual?: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className={thCls}>Métrica</TableHead>
            {comAtual && <TableHead className={`${thCls} text-right`}>Realizado (ao vivo)</TableHead>}
            {meses.map((m) => <TableHead key={m} className={`${thCls} text-right`}>{m}</TableHead>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          {linhas.map((l) => (
            <TableRow key={l.rotulo} className={destaque.includes(l.rotulo) ? "bg-muted/30" : undefined}>
              <TableCell className={destaque.includes(l.rotulo) ? "font-semibold" : "font-medium"}>
                {l.link ? (
                  <a href={l.link.url} title={l.link.dica} className="text-primary hover:underline">{l.rotulo}</a>
                ) : l.rotulo}
              </TableCell>
              {comAtual && (
                <TableCell className={`${numCls} font-semibold`}>{val(l.atual ?? null, l.kind)}</TableCell>
              )}
              {l.valores.map((v, i) => (
                <TableCell key={`${l.rotulo}-${i}`} className={numCls}>{val(v, l.kind)}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function FinanceiroVisaoPage() {
  const q = useApi<Payload>("/api/financeiro/visao");
  const d = q.data;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Financeiro<Hint area="financeiro/visao" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Planejamento × realizado — planilha de planejamento + Pipedrive ao vivo.
          {d && !d.sem_planilha && ` Hoje é dia ${d.dia} — ${d.ritmo_pct.toFixed(0)}% de ${d.mes_label} decorrido (o verde/vermelho compara com esse ritmo).`}
        </p>
      </header>

      {q.loading && <LoadingSkeleton rows={6} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d?.sem_planilha && (
        <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
          Planilha de planejamento indisponível no momento — recarregue em instantes (cache de 10 min).
        </p>
      )}
      {d && !d.sem_planilha && (
        <>
          <SectionCard hint={<Hint area="financeiro/visao" titulo="Mês em tempo real × meta" />}
            title={`${d.mes_label} em tempo real × meta`}
            subtitle="funil e bookings ao vivo do espelho do Pipedrive (régua oficial, defasagem ≤10 min) · recebimento e inadimplência não têm fonte em tempo real até o Omie entrar">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {d.cards.map((c) => (
                <MetaBar key={c.rotulo} value={c.real ?? 0} target={c.meta ?? 0}
                  valueLabel={`${c.rotulo}: ${val(c.real, c.kind)}`}
                  targetLabel={`meta ${val(c.meta, c.kind)}${c.pct != null ? ` · ${formatPct(c.pct, 0)}` : ""}`}
                  pacePct={d.ritmo_pct} />
              ))}
            </div>
          </SectionCard>

          {d.desvios.length > 0 && (
            <SectionCard hint={<Hint area="financeiro/visao" titulo="O que mais afasta da meta" />}
              title="O que mais afasta da meta este mês"
              subtitle="os 3 maiores desvios em R$ (vs o ritmo do mês) com a causa provável — cada um abre o diagnóstico; estimativas indicativas, não promessas">
              <div className="space-y-1">
                {d.desvios.map((x) => (
                  <a key={x.texto} href={x.url}
                    className="flex items-start gap-3 border-t border-border py-2 text-sm first:border-t-0 hover:bg-muted/40">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                    <span className="flex-1">
                      <b>{x.texto}</b>
                      <br />
                      <span className="text-xs text-muted-foreground">causa provável: {x.causa} — clique para investigar</span>
                    </span>
                    <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                  </a>
                ))}
              </div>
            </SectionCard>
          )}

          <SectionCard hint={<Hint area="financeiro/visao" titulo="Recebimento mês a mês" />}
            title="Recebimento mês a mês"
            subtitle={`total × parte recorrente · ${d.mes_label} (atual) e seguintes ainda são PROJEÇÃO — recebimento não tem fonte em tempo real até o Omie entrar`}>
            <TimeSeries data={d.recebimento} xKey="mes" height={260}
              series={[
                { key: "total", label: "Recebimento total", color: "var(--chart-1)", kind: "area",
                  valueFormatter: (v) => formatBRL(v) },
                { key: "recorrente", label: "Recorrente", color: "var(--success)",
                  valueFormatter: (v) => formatBRL(v) },
              ]}
              caveats={{ total: d.recebimento.filter((r) => r.projecao).map((r) => r.mes),
                         recorrente: d.recebimento.filter((r) => r.projecao).map((r) => r.mes) }} />
          </SectionCard>

          <SectionCard hint={<Hint area="financeiro/visao" titulo="Bookings × meta mês a mês" />}
            title="Bookings × meta mês a mês"
            subtitle={`meses fechados vêm da planilha · ${d.mes_label} (atual) = realizado AO VIVO do Pipedrive · meses futuros = meta`}>
            <TimeSeries data={d.bookings_mes} xKey="mes" height={260}
              series={[
                { key: "real", label: "Receita de bookings", color: "var(--chart-2)",
                  valueFormatter: (v) => formatBRL(v) },
                { key: "meta", label: "Meta", color: "var(--muted-foreground)", dashed: true,
                  valueFormatter: (v) => formatBRL(v) },
              ]}
              caveats={{ real: d.bookings_mes.filter((b) => b.atual).map((b) => b.mes) }} />
            <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
              {d.bookings_mes.filter((b) => b.sublabel).map((b) => (
                <span key={b.mes} className={b.atual ? "font-semibold text-foreground" : undefined}>
                  {b.mes}: {b.sublabel}
                  {b.no_ritmo != null && (
                    <span className={b.no_ritmo ? "text-success" : "text-destructive"}> {b.no_ritmo ? "✓" : "✗"}</span>
                  )}
                </span>
              ))}
            </div>
          </SectionCard>

          <SectionCard hint={<Hint area="financeiro/visao" titulo="Inadimplência e churn" />}
            title="Inadimplência e churn"
            subtitle={`inadimplência: verde ≤4% · amarelo ≤8% — churn: verde ≤5% · amarelo ≤9% · ${d.mes_label} e seguintes = ALVO (sem fonte em tempo real até o Omie)`}>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Métrica</TableHead>
                    {d.saude.map((s) => (
                      <TableHead key={s.mes} className={`${thCls} text-right ${s.alvo ? "opacity-60" : ""}`}>{s.mes}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {([["Inadimplência", "inadimplencia_pct", 4, 8],
                     ["Cancelamento", "churn_pct", 5, 9]] as const).map(([rot, chave, verde, amarelo]) => (
                    <TableRow key={rot}>
                      <TableCell className="font-medium">{rot}</TableCell>
                      {d.saude.map((s) => {
                        const v = s[chave] as number | null;
                        const cor = v == null ? "" : v <= verde ? "text-success" : v <= amarelo ? "text-warning" : "text-destructive";
                        return (
                          <TableCell key={s.mes} className={`${numCls} ${cor} ${s.alvo ? "opacity-60" : ""}`}>
                            {v != null ? `${v.toFixed(1)}%` : "—"}
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </SectionCard>

          <SectionCard hint={<Hint area="financeiro/visao" titulo="Metas — mês corrente e próximos" />}
            title="Metas — mês corrente e próximos"
            subtitle={`plano da planilha × realizado AO VIVO do mês (coluna à esquerda) · verde no ritmo de ${d.ritmo_pct.toFixed(0)}% · recebimento/inadimplência/churn seguem só como projeção`}>
            <Tabela meses={d.metas.meses} linhas={d.metas.linhas} destaque={d.metas.destaque} comAtual />
          </SectionCard>

          <SectionCard hint={<Hint area="financeiro/visao" titulo="Histórico realizado" />}
            title="Histórico realizado — detalhe"
            subtitle="meses fechados, direto da planilha de planejamento">
            <Tabela meses={d.historico.meses} linhas={d.historico.linhas} destaque={d.historico.destaque} />
          </SectionCard>

          <p className="text-xs text-muted-foreground">
            A <b>Saúde da Receita Recorrente</b> (ISR, Quick Ratio, crossover B2-B5 × antigos) tem aba
            própria: <a href="/financeiro?view=receita" className="text-primary hover:underline">Receita Recorrente</a>.
            Fonte: planilha Planejamento_Receita_2026 (cache 10 min) + espelho do Pipedrive (≤10 min).
          </p>
        </>
      )}
    </div>
  );
}
