import { AlertTriangle } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { TimeSeries } from "@/components/charts/time-series";
import { formatBRL } from "@/lib/format";

// Financeiro · Saúde da Receita Recorrente (ISR + Quick Ratio) — /api/financeiro/receita
// EMBRULHA `receita_recorrente.carrega()` (parser isolado da planilha, migra ao
// Omie depois). Duas visões que NÃO se misturam: B2-B5 = sinal do modelo novo ·
// Consolidado = caixa com os planos antigos em runoff. As decisões de exibição
// (flag por mês, cor do ISR, ★ crossover, alerta de 2 meses) vêm do backend.

interface Linha {
  mes: string; base_b2b5: number | null; isr_b2b5: number | null;
  isr_ok: boolean | null; nova: number | null; perdida: number | null;
  qr: number | null; isr_consol: number | null; qr_consol: number | null;
  crossover: boolean; flag: string;
}
interface Payload {
  sem_planilha: boolean;
  kpi: { mes: string; base_b2b5: number | null; isr_b2b5: number | null;
    isr_ok: boolean; qr: number | null; isr_consol: number | null };
  kpi_defasado: boolean;
  mes_corrente: string;
  linhas: Linha[];
  serie: Array<{ mes: string; base_b2b5: number | null; antigos: number | null;
    consolidado: number | null }>;
  alerta: { mes: string; texto: string } | null;
  crossover_idx: number | null; crossover_mes: string | null;
}

const numCls = "text-right tabular-nums";
// f_(v, nd) do HTML: pt-BR, `nd` casas fixas
const dec = (v: number | null | undefined, nd = 0) =>
  v == null ? "—" : v.toLocaleString("pt-BR", { minimumFractionDigits: nd, maximumFractionDigits: nd });

function Kpi({ valor, rotulo, sub, cor }: {
  valor: string; rotulo: string; sub?: string; cor?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className={`font-display text-2xl font-bold tabular-nums ${cor ?? ""}`}>{valor}</div>
      <div className="mt-1 text-xs font-medium text-muted-foreground">{rotulo}</div>
      {sub && <div className="text-[11px] text-muted-foreground/70">{sub}</div>}
    </div>
  );
}

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";

export function FinanceiroReceitaPage() {
  const q = useApi<Payload>("/api/financeiro/receita");
  const d = q.data;
  const crossTxt = d?.crossover_mes
    ? `★ Crossover projetado: ${d.crossover_mes} — mês em que a base B2-B5 supera os planos antigos (o modelo novo passa a sustentar a receita sozinho).`
    : "Crossover B2-B5 × antigos ainda não ocorre em 2026.";

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">
          Receita Recorrente<Hint area="financeiro/receita" titulo="_intro" />
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          ISR · Quick Ratio · crossover B2-B5 × antigos — fonte: planilha de planejamento
          (parser isolado, migra ao Omie quando o Financeiro abrir).
        </p>
      </header>

      {q.loading && <LoadingSkeleton rows={5} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d?.sem_planilha && (
        <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
          Planilha de planejamento indisponível — recarregue em instantes (cache de 10 min).
        </p>
      )}

      {d && !d.sem_planilha && (
        <SectionCard
          hint={<Hint area="financeiro/receita" titulo="Saúde da Receita Recorrente" />}
          title="Saúde da Receita Recorrente"
          subtitle="ISR = base recorrente ÷ mês anterior ×100 (≥100 = crescendo) · Quick Ratio = nova ÷ perdida (≥1 = ganha mais do que perde) · duas visões que NÃO se misturam: B2-B5 = o sinal do modelo novo · Consolidado = caixa com antigos em runoff">

          {/* a planilha só é preenchida depois da virada do mês — sem este
              aviso os 4 KPIs ficavam "—" e a tela parecia quebrada (Otávio 24/07) */}
          {d.kpi_defasado && (
            <div className="mb-4 flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              <span>
                <b>{d.mes_corrente} ainda não preenchido</b> na planilha de planejamento —
                os indicadores abaixo são de <b>{d.kpi.mes}</b>, o último mês com dado.
                A tabela e o gráfico mostram a série completa.
              </span>
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi valor={dec(d.kpi.base_b2b5)}
              rotulo={`base recorrente B2-B5 (${d.kpi.mes}${d.kpi_defasado ? " · último com dado" : ""})`} />
            <Kpi valor={dec(d.kpi.isr_b2b5)} rotulo="ISR B2-B5" sub="≥100 = base crescendo"
              cor={d.kpi.isr_ok ? "text-success" : "text-destructive"} />
            <Kpi valor={dec(d.kpi.qr, 1)} rotulo="Quick Ratio B2-B5" sub="nova ÷ perdida" />
            <Kpi valor={dec(d.kpi.isr_consol, 1)} rotulo="ISR consolidado" sub="caixa (antigos em runoff)" />
          </div>

          {d.alerta && (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
              <span>
                <b>{d.alerta.texto}</b> (até {d.alerta.mes}) — o modelo recorrente não está se sustentando.
                Investigar:{" "}
                <a href="/growth?view=cancelamentos" className="text-primary hover:underline">Cancelamentos por bundle</a>{" · "}
                <a href="/marketing?view=ciclo" className="text-primary hover:underline">Ciclo de Vida</a>{" · "}
                <a href="/raiox" className="text-primary hover:underline">Raio-X por Bundle</a>
              </span>
            </div>
          )}

          {/* O bloco nunca teve gráfico (nem no HTML antigo, nem na migração) —
              o "recharts: 0" da varredura era esta lacuna, não o furo de julho.
              Mês sem dado fica como BURACO na linha: `connectNulls` off é o
              padrão do Recharts, então jul/26 não vira uma reta inventada. */}
          <div className="mt-5">
            <p className="mb-1 text-xs text-muted-foreground">
              Base recorrente <b>B2-B5</b> × <b>planos antigos</b> (em runoff) — o cruzamento das duas
              linhas é o mês em que o modelo novo passa a sustentar a receita sozinho.
            </p>
            <TimeSeries data={d.serie} xKey="mes" height={260}
              series={[
                { key: "base_b2b5", label: "Base B2-B5", color: "var(--chart-1)",
                  valueFormatter: (v) => formatBRL(v) },
                { key: "antigos", label: "Planos antigos", color: "var(--muted-foreground)",
                  dashed: true, valueFormatter: (v) => formatBRL(v) },
              ]}
              annotations={d.crossover_mes ? [{ x: d.crossover_mes, seriesKey: "base_b2b5",
                label: "★ crossover" }] : undefined} />
          </div>

          <div className="mt-4 overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className={thCls}>Mês</TableHead>
                  <TableHead className={`${thCls} text-right`}>Base B2-B5</TableHead>
                  <TableHead className={`${thCls} text-right`}>ISR</TableHead>
                  <TableHead className={`${thCls} text-right`}>Nova</TableHead>
                  <TableHead className={`${thCls} text-right`}>Perdida</TableHead>
                  <TableHead className={`${thCls} text-right`}>QR</TableHead>
                  <TableHead className={`${thCls} border-l border-border text-right`}>ISR consol.</TableHead>
                  <TableHead className={`${thCls} text-right`}>QR consol.</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.linhas.map((l) => (
                  <TableRow key={l.mes}>
                    <TableCell className="whitespace-nowrap font-medium">
                      {l.mes}
                      {l.crossover && <span className="text-primary"> ★</span>}
                      {l.flag && (
                        <span className="ml-1 text-[11px] text-muted-foreground/70">{l.flag}</span>
                      )}
                    </TableCell>
                    <TableCell className={numCls}>{dec(l.base_b2b5)}</TableCell>
                    <TableCell className={`${numCls} ${l.isr_ok == null ? "" : l.isr_ok ? "text-success" : "text-destructive"}`}>
                      {dec(l.isr_b2b5)}
                    </TableCell>
                    <TableCell className={numCls}>{dec(l.nova)}</TableCell>
                    <TableCell className={numCls}>{dec(l.perdida)}</TableCell>
                    <TableCell className={`${numCls} font-semibold`}>{dec(l.qr, 1)}</TableCell>
                    <TableCell className={`${numCls} border-l border-border`}>{dec(l.isr_consol, 1)}</TableCell>
                    <TableCell className={numCls}>{dec(l.qr_consol, 1)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">{crossTxt}</p>
        </SectionCard>
      )}
    </div>
  );
}
