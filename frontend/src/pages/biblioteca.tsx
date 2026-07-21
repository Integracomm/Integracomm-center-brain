import { AlertTriangle, PhoneCall, TrendingDown, Wallet } from "lucide-react";
import { KpiCard } from "@/components/kpi-card";
import { CaveatChip } from "@/components/caveat";
import { SectionCard } from "@/components/blocks/section-card";
import { WaitBadge } from "@/components/blocks/wait-badge";
import { MetaBar } from "@/components/blocks/meta-bar";
import { BarListH, BarListHGrouped } from "@/components/charts/bar-list-h";
import { Funnel } from "@/components/charts/funnel";
import { Heatmap } from "@/components/charts/heatmap";
import { StackedBarH } from "@/components/charts/stacked-bar-h";
import { TimeSeries } from "@/components/charts/time-series";
import { EmptyState, ErrorState, LoadingSkeleton } from "@/components/states";
import { formatBRL, formatPct } from "@/lib/format";

// Vitrine do Lote 0 — exercita TODOS os primitivos com dados DE EXEMPLO
// (rotulados como tal). Serve para validar: renderização, dark mode,
// hachura de amostra pequena, caveats como array, e os 2 primitivos novos.
export function BibliotecaPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="font-display text-2xl font-bold">Biblioteca de visuais — Lote 0</h1>
        <p className="text-sm text-muted-foreground">
          Todos os dados desta página são <b>de exemplo</b> (fixos no código) — a vitrine valida a
          fundação: primitivos, tema claro/escuro, ressalvas e os dois componentes novos.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiCard title="MRR em risco" value={formatBRL(177873)} icon={Wallet} tone="destructive"
          subtitle="risk_band alto/médio" caveat="3 contas em risco sem MRR cadastrado" />
        <KpiCard title="Críticos" value="10" icon={AlertTriangle} tone="warning" subtitle="alertas abertos" />
        <KpiCard title="Ligações/dia" value="204" icon={PhoneCall} tone="primary" />
        <KpiCard title="Churn precoce" value="21%" icon={TrendingDown} tone="muted"
          caveat="coorte com 14 clientes — amostra pequena" />
      </div>

      <SectionCard title="MetaBar (novo)" subtitle="realizado vs meta com marcador de ritmo — 3 estados">
        <div className="space-y-5">
          <MetaBar value={61} target={96} valueLabel="61 bookings" targetLabel="meta 96" pacePct={65} />
          <MetaBar value={98} target={96} valueLabel="98 bookings" targetLabel="meta 96" pacePct={65} />
          <MetaBar value={30} target={96} valueLabel="30 bookings" targetLabel="meta 96" pacePct={65} />
        </div>
      </SectionCard>

      <SectionCard title="BarListH" subtitle="comparar categorias / Pareto — rótulo sempre visível">
        <BarListH
          height={220}
          data={[
            { label: "Preço/orçamento", value: 34 },
            { label: "Sem resposta", value: 21 },
            { label: "Fechou com concorrente", value: 12 },
            { label: "Timing", value: 8 },
          ]}
        />
      </SectionCard>

      <SectionCard title="BarListHGrouped (novo)" subtitle="duas medidas por categoria — ex.: CAC vs CAC ajustado pela retenção">
        <BarListHGrouped
          height={220}
          data={[
            { label: "Meta Ads", cac: 890, cac_aj: 2070 },
            { label: "Google Ads", cac: 1240, cac_aj: 1550 },
            { label: "Prospecção", cac: 310, cac_aj: 390 },
          ]}
          series={[
            { key: "cac", label: "CAC", color: "var(--chart-2)" },
            { key: "cac_aj", label: "CAC ajustado", color: "var(--destructive)" },
          ]}
          valueLabel={(v) => formatBRL(v)}
        />
      </SectionCard>

      <SectionCard title="Funnel" subtitle="etapas com conversão da anterior — conversão total vem do payload">
        <Funnel
          etapas={[
            { key: "lead", label: "Lead", volume: 1506, conversao_da_anterior_pct: null },
            { key: "contatado", label: "1º contato", volume: 918, conversao_da_anterior_pct: 61 },
            { key: "qualificado", label: "Qualificado", volume: 402, conversao_da_anterior_pct: 44 },
            { key: "oportunidade", label: "Oportunidade", volume: 197, conversao_da_anterior_pct: 49 },
          ]}
        />
      </SectionCard>

      <SectionCard title="StackedBarH" subtitle="proporção de um todo — safra em maturação vem marcada (hachura + legenda)">
        <StackedBarH
          height={220}
          data={[
            { label: "mar/26", ativa: 24, precoce: 6, tardio: 2 },
            { label: "abr/26", ativa: 31, precoce: 4, tardio: 1 },
            { label: "mai/26", ativa: 28, precoce: 3, tardio: 0, maturacao: true },
            { label: "jun/26", ativa: 33, precoce: 1, tardio: 0, maturacao: true },
          ]}
          segments={[
            { key: "ativa", label: "Ativa", color: "var(--success)" },
            { key: "precoce", label: "Churn precoce (≤3m)", color: "var(--destructive)" },
            { key: "tardio", label: "Churn tardio", color: "var(--warning)" },
          ]}
        />
      </SectionCard>

      <SectionCard title="Heatmap" subtitle="duas dimensões — célula com amostra pequena ganha hachura VISÍVEL nos dois temas (correção do Lote 0)">
        <Heatmap
          rows={["Preço/orçamento", "Sem resposta", "Concorrente"]}
          cols={["B1", "B2", "B3", "B4"]}
          cells={[
            { row: "Preço/orçamento", col: "B1", value: 42, n: 18 },
            { row: "Preço/orçamento", col: "B2", value: 28, n: 12 },
            { row: "Preço/orçamento", col: "B3", value: 12, n: 4, amostra_pequena: true },
            { row: "Sem resposta", col: "B1", value: 22, n: 9 },
            { row: "Sem resposta", col: "B2", value: 31, n: 14 },
            { row: "Sem resposta", col: "B4", value: 9, n: 2, amostra_pequena: true },
            { row: "Concorrente", col: "B2", value: 18, n: 7 },
            { row: "Concorrente", col: "B3", value: null },
          ]}
          valueLabel={(v) => formatPct(v)}
          legendLabel="% das perdas"
        />
      </SectionCard>

      <SectionCard title="TimeSeries" subtitle="referência (ISR=100), anotação (crossover) e caveats como ARRAY do payload (pontos ocos)">
        <TimeSeries
          height={260}
          data={[
            { mes: "fev", isr: 82, quick: 0.8 },
            { mes: "mar", isr: 94, quick: 1.1 },
            { mes: "abr", isr: 103, quick: 1.4 },
            { mes: "mai", isr: 97, quick: 0.9 },
            { mes: "jun", isr: 112, quick: 1.6 },
            { mes: "jul", isr: 121, quick: 1.9 },
          ]}
          xKey="mes"
          series={[
            { key: "isr", label: "ISR", color: "var(--chart-1)" },
            { key: "quick", label: "Quick Ratio", color: "var(--accent)", yAxis: "right", dashed: true },
          ]}
          references={[{ value: 100, label: "ISR = 100" }]}
          annotations={[{ x: "abr", seriesKey: "isr", label: "crossover" }]}
          caveats={{ isr: ["fev", "jul"] }}
        />
      </SectionCard>

      <SectionCard title="WaitBadge + CaveatChip" subtitle="escalas vêm do chamador, nunca fixas no componente">
        <div className="flex flex-wrap items-center gap-3">
          <WaitBadge value={6} thresholds={[{ gte: 24, tone: "warning" }, { gte: 48, tone: "destructive" }]} />
          <WaitBadge value={31} thresholds={[{ gte: 24, tone: "warning" }, { gte: 48, tone: "destructive" }]} />
          <WaitBadge value={117} unit="d" thresholds={[{ gte: 7, tone: "warning" }, { gte: 30, tone: "destructive" }]} />
          <CaveatChip text="Amostra pequena — interpretar com cautela" />
        </div>
      </SectionCard>

      <div className="grid gap-4 lg:grid-cols-3">
        <SectionCard title="Loading" subtitle="skeleton">
          <LoadingSkeleton rows={2} />
        </SectionCard>
        <SectionCard title="Vazio" subtitle="estado honesto">
          <EmptyState title="Nenhum alerta aberto" description="A carteira está em dia." />
        </SectionCard>
        <SectionCard title="Erro" subtitle="com retry">
          <ErrorState message="Exemplo de falha de rede." onRetry={() => {}} />
        </SectionCard>
      </div>
    </div>
  );
}
