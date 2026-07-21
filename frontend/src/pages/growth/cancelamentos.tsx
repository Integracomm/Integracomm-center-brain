import { useMemo, useState } from "react";
import { CalendarRange, HeartHandshake, TrendingDown, Undo2, Wallet } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { CaveatChip } from "@/components/caveat";
import { SectionCard } from "@/components/blocks/section-card";
import { BarListH } from "@/components/charts/bar-list-h";
import { TimeSeries } from "@/components/charts/time-series";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatBRL, formatPct } from "@/lib/format";
import type { CancelamentosPayload, CancTaxaBundle } from "@/types/api";

// Growth · Cancelamentos — de 7 tabelas para 1 tabela nominal + visuais
// (meta do redesenho). TODO número vem pronto de /api/growth/cancelamentos
// (mesma _cancel_dados da tela antiga — paridade garantida na fonte).
// Tabelas completas preservadas em <details> — nenhum dado sai da tela.

function Det({ resumo, children }: { resumo: string; children: React.ReactNode }) {
  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-xs font-medium text-primary">{resumo}</summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";

export function GrowthCancelamentosPage() {
  const [ini, setIni] = useState("");
  const [fim, setFim] = useState("");
  const qs = new URLSearchParams();
  if (ini) qs.set("ini", ini);
  if (fim) qs.set("fim", fim);
  const q = useApi<CancelamentosPayload>(`/api/growth/cancelamentos${qs.size ? `?${qs}` : ""}`);
  const d = q.data;

  const taxaData = useMemo(() => {
    if (!d) return [];
    // GERAL primeiro e destacado; B1 fora do GRÁFICO (não entra no cálculo —
    // Otávio 21/07); ele continua na tabela completa, nenhum dado some.
    return [d.taxa_geral, ...d.taxa_bundle.filter((b) => b.bundle !== "B1")]
      .filter((b) => b.taxa_clientes_pct != null)
      .map((b) => ({
        label: b.bundle.startsWith("GERAL") ? "GERAL (sem B1)" : b.bundle,
        value: b.taxa_clientes_pct as number,
        _b: b,
      }));
  }, [d]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-2xl font-bold tracking-tight">Cancelamentos</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Churn realizado (planilhas do time — fonte oficial) + pipeline de retenção.
        </p>
      </header>

      {q.loading && <LoadingSkeleton rows={5} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && (
        <>
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
            <CalendarRange className="h-4 w-4 text-muted-foreground" />
            <Select value={ini || d.periodo.ini} onValueChange={setIni}>
              <SelectTrigger className="w-[140px]"><SelectValue placeholder="de (mês)" /></SelectTrigger>
              <SelectContent>
                {d.meses_disponiveis.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}
              </SelectContent>
            </Select>
            <span className="text-xs text-muted-foreground">até</span>
            <Select value={fim || d.periodo.fim} onValueChange={setFim}>
              <SelectTrigger className="w-[140px]"><SelectValue placeholder="até (mês)" /></SelectTrigger>
              <SelectContent>
                {d.meses_disponiveis.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}
              </SelectContent>
            </Select>
            <span className="ml-auto text-xs text-muted-foreground">
              período {d.periodo.ini} → {d.periodo.fim}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
            <KpiCard icon={TrendingDown} tone="destructive" title="Saídas no mês"
              value={d.kpis.saidas_mes.toLocaleString("pt-BR")} subtitle="formalizadas nas planilhas" />
            <KpiCard icon={Wallet} tone="warning" title="MRR perdido no mês"
              value={formatBRL(d.kpis.mrr_perdido_mes)} subtitle="soma das mensalidades" />
            <KpiCard icon={HeartHandshake} tone="warning" title="Em tratativa"
              value={d.kpis.em_tratativa.toLocaleString("pt-BR")} subtitle="pipeline de retenção — agir antes de formalizar" />
            <KpiCard icon={Undo2} tone="success" title="Revertidos"
              value={d.kpis.revertidos.toLocaleString("pt-BR")} subtitle="intenção contornada — não contam como saída" />
            <KpiCard icon={CalendarRange} tone="muted" title="Tempo de casa (mediana)"
              value={d.kpis.tempo_casa_mediano != null ? `${d.kpis.tempo_casa_mediano.toFixed(0)} m` : "—"}
              subtitle={`na saída · ${d.kpis.tempo_casa_n} c/ dado`} />
          </div>

          <SectionCard
            title="Taxa de cancelamento por plano"
            subtitle={`saídas/mês ÷ base ATUAL de contas · janela de ${d.taxa_geral.janela_meses} mês(es) · B1 fica fora (semestral, não recorrente) — aparece na tabela completa`}
          >
            <BarListH
              height={Math.max(220, taxaData.length * 44)}
              data={taxaData}
              color="var(--destructive)"
              itemColor={(it) => (it.label.startsWith("GERAL") ? "var(--chart-1)" : undefined)}
              valueLabel={(v) => `${formatPct(v, 1)}/mês`}
              tooltipFormatter={(v, item) => {
                const b = (item as { _b: CancTaxaBundle })._b;
                return [
                  `${b.saidas} saída(s) em ${b.janela_meses}m · base atual ${b.base_atual}`
                  + (b.taxa_faturamento_pct != null
                    ? ` · faturamento: ${b.mrr_base_estimado ? "≈ " : ""}${formatPct(b.taxa_faturamento_pct, 1)}/mês` : "")
                  + (b.aviso ? ` · ⚠ ${b.aviso}` : ""),
                  `${formatPct(v, 1)}/mês`,
                ];
              }}
            />
            <div className="mt-2 flex flex-wrap gap-2">
              {[...d.taxa_bundle, d.taxa_geral].filter((b) => b.aviso).map((b) => (
                <CaveatChip key={b.bundle} text={`${b.bundle}: ${b.aviso}`} />
              ))}
            </div>
            <Det resumo="ver tabela completa (base, MRR da base, taxa por clientes e por faturamento)">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    {["Plano", "Base atual", "MRR base", "Saídas", "MRR perdido", "Taxa (clientes)", "Taxa (faturamento)"]
                      .map((h, i) => <TableHead key={h} className={`${thCls}${i > 0 ? " text-right" : ""}`}>{h}</TableHead>)}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[...d.taxa_bundle, d.taxa_geral].map((b) => (
                    <TableRow key={b.bundle} className={b.bundle.startsWith("GERAL") ? "font-semibold" : ""}>
                      <TableCell>{b.bundle}{!b.recorrente && <span className="ml-2 text-xs text-muted-foreground">não recorrente</span>}</TableCell>
                      <TableCell className="text-right tabular-nums">{b.base_atual || "—"}</TableCell>
                      <TableCell className="text-right tabular-nums" title={b.mrr_base_estimado
                        ? `estimado: média das contas com MRR lançado × total (${b.mrr_base_com_valor} de ${b.base_atual} têm valor)` : undefined}>
                        {b.mrr_base != null ? `${b.mrr_base_estimado ? "≈ " : ""}${formatBRL(b.mrr_base)}` : "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{b.saidas}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatBRL(b.mrr_perdido)}</TableCell>
                      <TableCell className="text-right tabular-nums">{b.taxa_clientes_pct != null ? `${formatPct(b.taxa_clientes_pct, 1)}/mês` : "—"}</TableCell>
                      <TableCell className="text-right tabular-nums">{b.taxa_faturamento_pct != null ? `${b.mrr_base_estimado ? "≈ " : ""}${formatPct(b.taxa_faturamento_pct, 1)}/mês` : "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Det>
          </SectionCard>

          <SectionCard title="Evolução mensal"
            subtitle="saídas por mês — total e separado por planos novos (bundles) × antigos/ADS · MRR perdido no eixo direito">
            <TimeSeries
              height={280}
              data={d.por_mes.map((m) => ({
                mes: m.mes_label, saidas: m.saidas, novos: m.saidas_novos,
                antigos: m.saidas_antigos, mrr: m.mrr_perdido,
              }))}
              xKey="mes"
              series={[
                { key: "saidas", label: "Total", color: "var(--destructive)" },
                { key: "novos", label: "Planos novos (bundles)", color: "var(--chart-1)" },
                { key: "antigos", label: "Antigos/ADS", color: "var(--muted-foreground)" },
                { key: "mrr", label: "MRR perdido", color: "var(--chart-2)", yAxis: "right", dashed: true,
                  valueFormatter: (v) => formatBRL(v) },
              ]}
              rightTickFormatter={(v) => formatBRL(v, { compact: true })}
            />
            <Det resumo="ver tabela completa (ticket médio, tempo de casa, términos START)">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    {["Mês", "Saídas", "MRR perdido", "Ticket médio", "Tempo casa (med.)", "Términos START"]
                      .map((h, i) => <TableHead key={h} className={`${thCls}${i > 0 ? " text-right" : ""}`}>{h}</TableHead>)}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.por_mes.map((m) => (
                    <TableRow key={m.mes}>
                      <TableCell className="font-medium">{m.mes_label}</TableCell>
                      <TableCell className="text-right tabular-nums">{m.saidas}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatBRL(m.mrr_perdido)}</TableCell>
                      <TableCell className="text-right tabular-nums">{m.ticket_medio != null ? formatBRL(m.ticket_medio) : "—"}</TableCell>
                      <TableCell className="text-right tabular-nums">{m.tempo_casa_mediano != null ? `${m.tempo_casa_mediano.toFixed(0)} m` : "—"}</TableCell>
                      <TableCell className="text-right tabular-nums">{m.terminos_start || "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Det>
          </SectionCard>

          <div className="grid gap-6 lg:grid-cols-2">
            <SectionCard title="Motivos (Pareto)"
              subtitle={`onde atacar primeiro · ${d.sem_motivo} saída(s) SEM motivo preenchido no período`}>
              {d.motivos.length ? (
                <BarListH height={Math.max(240, d.motivos.length * 52)} width={250}
                  data={d.motivos.map((m) => ({ label: m.motivo, value: m.saidas }))} />
              ) : (
                <p className="text-sm text-muted-foreground">Nenhum motivo preenchido no período.</p>
              )}
              {d.sem_motivo > 0 && (
                <div className="mt-2"><CaveatChip text={`${d.sem_motivo} cancelamento(s) sem motivo — sem registro não há aprendizado; cobrar no formalizar.`} /></div>
              )}
              <Det resumo="ver casos recentes com motivo (cliente a cliente)">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/40 hover:bg-muted/40">
                      {["Mês", "Cliente", "Plano", "Motivo"].map((h) => <TableHead key={h} className={thCls}>{h}</TableHead>)}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.casos_com_motivo.map((c, i) => (
                      <TableRow key={i}>
                        <TableCell className="whitespace-nowrap tabular-nums">{c.mes}</TableCell>
                        <TableCell className="max-w-[200px] truncate font-medium">{c.cliente}</TableCell>
                        <TableCell>{c.plano ?? "—"}</TableCell>
                        <TableCell className="max-w-[260px] text-sm text-muted-foreground">{c.motivo}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Det>
            </SectionCard>

            <SectionCard title="Saídas por plano e por equipe" subtitle="todo o período filtrado — top 8 de cada">
              <div className="grid gap-4">
                <BarListH height={Math.max(220, Math.min(8, d.por_plano.length) * 44)} width={235}
                  data={d.por_plano.slice(0, 8).map((p) => ({ label: p.nome, value: p.saidas }))}
                  color="var(--chart-2)" />
                <BarListH height={Math.max(220, Math.min(8, d.por_equipe.length) * 44)} width={235}
                  data={d.por_equipe.slice(0, 8).map((p) => ({ label: p.nome, value: p.saidas }))}
                  color="var(--chart-4)" />
              </div>
              <Det resumo="ver tabelas completas (MRR e tempo de casa)">
                {[{ t: "Por plano", rows: d.por_plano }, { t: "Por equipe", rows: d.por_equipe }].map((g) => (
                  <div key={g.t} className="mb-4">
                    <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{g.t}</div>
                    <Table>
                      <TableHeader>
                        <TableRow className="bg-muted/40 hover:bg-muted/40">
                          {[g.t.replace("Por ", ""), "Saídas", "MRR", "Tempo (med.)"]
                            .map((h, i) => <TableHead key={h} className={`${thCls}${i > 0 ? " text-right" : ""}`}>{h}</TableHead>)}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {g.rows.map((r) => (
                          <TableRow key={r.nome}>
                            <TableCell>{r.nome}</TableCell>
                            <TableCell className="text-right tabular-nums">{r.saidas}</TableCell>
                            <TableCell className="text-right tabular-nums">{formatBRL(r.mrr_perdido)}</TableCell>
                            <TableCell className="text-right tabular-nums">{r.tempo_casa_mediano != null ? `${r.tempo_casa_mediano.toFixed(0)} m` : "—"}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                ))}
              </Det>
            </SectionCard>
          </div>

          <SectionCard title="Fila de retenção (tratativas do mês)"
            subtitle="lista nominal acionável — mantém tabela por regra do guia">
            {d.tratativas.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nenhuma tratativa aberta no mês.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    {["Cliente", "GC/Squad", "Plano", "Situação"].map((h) => <TableHead key={h} className={thCls}>{h}</TableHead>)}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.tratativas.map((t, i) => (
                    <TableRow key={i}>
                      <TableCell className="max-w-[260px] truncate font-medium">{t.cliente}</TableCell>
                      <TableCell>{t.gc ?? "—"}</TableCell>
                      <TableCell>{t.plano ?? "—"}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{t.situacao}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </SectionCard>
        </>
      )}
    </div>
  );
}
