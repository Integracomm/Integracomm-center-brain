import { AlertTriangle, Presentation, Users, ShoppingCart, TrendingDown, Megaphone } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { KpiCard } from "@/components/kpi-card";
import { BarListH } from "@/components/charts/bar-list-h";
import { Funnel } from "@/components/charts/funnel";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { formatBRL, formatNumber } from "@/lib/format";

// All Hands · Dados do mês — /api/allhands/dados EMBRULHA _dados_mes (o MESMO
// cálculo dos slides da apresentação). É o fechamento por área que os
// coordenadores montavam à mão; sem fonte automática = lacuna marcada (⚠),
// nunca zero inventado.

interface Payload {
  mes: string; mes_label: string; meses: string[];
  marketing: { leads: number; mqls: number; sals: number; sqls: number;
    oportunidades: number; vendas: number };
  vendas: { por_plano: Array<{ plano: string; qtde: number; receita: number }>;
    total: number; receita: number };
  assessoria: { clientes_plano: Array<{ plano: string; qtde: number }>;
    total: number; leitura_tardia: boolean;
    reunioes: {
      por_gc: Array<{ gc: string; reunioes: number; agendadas: number;
        satisfacao: number | null; com_nota: number }>;
      realizadas: number; agendadas: number;
      satisfacao_geral: number | null; com_nota: number } | null };
  estrategia: { clientes: number };
  saidas: { por_plano: Array<{ plano: string; qtde: number }>; total: number;
    sem_plano: number; taxa_recorrentes: number | null; saidas_rec: number; base_rec: number };
  lacunas: Record<string, string[]>;
}

const mesLabel = (iso: string) => {
  const [y, m] = iso.split("-");
  const nomes = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
  return `${nomes[Number(m) - 1]} / ${y}`;
};

function Linha({ rot, val, sub, bold }: { rot: string; val: string; sub?: string; bold?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border py-2 last:border-b-0">
      <div className={bold ? "font-semibold" : undefined}>
        {rot}
        {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
      </div>
      <div className={`whitespace-nowrap tabular-nums ${bold ? "font-bold" : "font-semibold"}`}>{val}</div>
    </div>
  );
}

function Lacuna({ txt }: { txt: string }) {
  return (
    <div className="flex items-start gap-2 border-b border-border py-2 text-xs text-warning last:border-b-0">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{txt} — sem fonte automática ainda; segue com o coordenador</span>
    </div>
  );
}

export function AllHandsDadosPage() {
  const params = new URLSearchParams(window.location.search);
  const [mes, setMes] = useState(params.get("mes") ?? "");
  const q = useApi<Payload>(`/api/allhands/dados${mes ? `?mes=${mes}` : ""}`);
  const d = q.data;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            Dados do mês{d && <span className="text-primary"> · {d.mes_label}</span>}
          </h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            O fechamento que os coordenadores montam à mão, nas mesmas réguas do painel (funil
            oficial, vendas por produto, clientes ativos as-of no fim do mês, cancelamentos da
            planilha oficial). Itens com ⚠ ainda não têm fonte automática.
          </p>
        </div>
        {d && (
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            mês
            <Select value={d.mes} onValueChange={setMes}>
              <SelectTrigger className="w-[150px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                {d.meses.map((m) => <SelectItem key={m} value={m}>{mesLabel(m)}</SelectItem>)}
              </SelectContent>
            </Select>
          </label>
        )}
      </header>

      {q.loading && !d && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <LoadingSkeleton rows={1} /><LoadingSkeleton rows={1} />
            <LoadingSkeleton rows={1} /><LoadingSkeleton rows={1} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <LoadingSkeleton rows={3} /><LoadingSkeleton rows={3} />
          </div>
        </>
      )}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}

      {d && (
        <>
        {/* Faixa de KPIs: os 4 números que abrem a reunião. Antes cada um vivia
            dentro de um card de área diferente e o olho tinha de caçá-los
            (Otávio 27/07: "um monte de dados jogados na página"). */}
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard icon={Megaphone} tone="primary" title="Leads gerados"
            value={formatNumber(d.marketing.leads)}
            subtitle={`${formatNumber(d.marketing.oportunidades)} oportunidades`}
            caveat="Oportunidades seguem régua retroativa: o número se move enquanto a fila é qualificada." />
          <KpiCard icon={ShoppingCart} tone="success" title="Vendas no mês"
            value={formatNumber(d.vendas.total)} subtitle={formatBRL(d.vendas.receita)} />
          <KpiCard icon={Users} tone="accent" title="Clientes ativos"
            value={formatNumber(d.assessoria.total)}
            subtitle={`as-of fim de ${d.mes_label}`} />
          <KpiCard icon={TrendingDown} tone="destructive" title="Saídas no mês"
            value={formatNumber(d.saidas.total)}
            subtitle={d.saidas.taxa_recorrentes != null
              ? `${(d.saidas.taxa_recorrentes * 100).toFixed(1)}% dos recorrentes`
              : "taxa indisponível"} />
        </div>

        <div className="grid items-start gap-4 lg:grid-cols-2">
          <SectionCard title="Pré-vendas · funil do mês" headerClassName="min-h-[46px]"
            subtitle="mesma régua do funil oficial de Marketing — as duas áreas fecham com os mesmos números por definição">
            <Funnel etapas={[
              { key: "lead", label: "Leads", volume: d.marketing.leads, conversao_da_anterior_pct: null },
              { key: "mql", label: "MQLs", volume: d.marketing.mqls,
                conversao_da_anterior_pct: d.marketing.leads ? (d.marketing.mqls / d.marketing.leads) * 100 : null },
              { key: "sal", label: "SALs", volume: d.marketing.sals,
                conversao_da_anterior_pct: d.marketing.mqls ? (d.marketing.sals / d.marketing.mqls) * 100 : null },
              { key: "sql", label: "SQLs", volume: d.marketing.sqls,
                conversao_da_anterior_pct: d.marketing.sals ? (d.marketing.sqls / d.marketing.sals) * 100 : null },
              { key: "oport", label: "Oportunidades", volume: d.marketing.oportunidades,
                conversao_da_anterior_pct: d.marketing.sqls ? (d.marketing.oportunidades / d.marketing.sqls) * 100 : null },
            ]} />
          </SectionCard>

          <SectionCard title="Vendas · bookings por plano" headerClassName="min-h-[46px]"
            subtitle={`${d.vendas.total} contrato(s) · ${formatBRL(d.vendas.receita)} no mês`}>
            <BarListH
              data={d.vendas.por_plano.map((v) => ({ label: v.plano, value: v.qtde, receita: v.receita }))}
              height={Math.max(120, d.vendas.por_plano.length * 44)} width={190}
              color="var(--chart-2)"
              valueLabel={(v, it) => `${v}${it.receita ? ` · ${formatBRL(it.receita as number)}` : ""}`} />
            {d.lacunas.marketing?.map((l) => <Lacuna key={l} txt={l} />)}
          </SectionCard>
        </div>

        <div className="grid items-start gap-4 lg:grid-cols-2">
          {/* Estratégia NÃO tem card próprio: seu nº de clientes já é uma barra
              deste gráfico (Otávio 27/07). A lacuna do faturamento vem junto. */}
          <SectionCard title="Assessoria · clientes ativos por plano" headerClassName="min-h-[46px]"
            subtitle={`${formatNumber(d.assessoria.total)} clientes as-of fim de ${d.mes_label} — inclui Estratégia`}>
            <BarListH
              data={d.assessoria.clientes_plano.map((c) => ({ label: c.plano, value: c.qtde }))}
              height={Math.max(140, d.assessoria.clientes_plano.length * 40)} width={150}
              color="var(--chart-1)" valueLabel={(v) => formatNumber(v)} />
            {d.assessoria.leitura_tardia && (
              <Lacuna txt="leitura tardia: a contagem retroativa SUBCONTA (cancelados desde o fechamento saem da lista Clientes Ativos) — o número oficial é o do deck gerado logo após o mês virar" />
            )}
            {d.lacunas.assessoria?.map((l) => <Lacuna key={l} txt={l} />)}
            {d.lacunas.estrategia?.map((l) => <Lacuna key={l} txt={`Estratégia: ${l}`} />)}
          </SectionCard>

          {/* Reuniões de GC + satisfação: eram lacuna ⚠ até o Otávio apontar a
              fonte (27/07) — subtarefas "Reunião GC" e o campo `satisfação`. */}
          {d.assessoria.reunioes && (
            <SectionCard title="Assessoria · reuniões por gerente de contas" headerClassName="min-h-[46px]"
              subtitle={`quem conduziu as reuniões de ${d.mes_label} e como o cliente avaliou`}>
              <BarListH
                data={d.assessoria.reunioes.por_gc.map((g) => ({
                  label: g.gc, value: g.reunioes, satisfacao: g.satisfacao, n: g.com_nota,
                }))}
                height={Math.max(140, d.assessoria.reunioes.por_gc.length * 40)} width={210}
                color="var(--chart-4)"
                valueLabel={(v, it) =>
                  `${v}${it.satisfacao != null
                    ? ` · ★ ${(it.satisfacao as number).toLocaleString("pt-BR")} (${it.n})`
                    : ""}`} />
              {/* TOTAL DA EMPRESA (Otávio 27/07): as barras por GC não somam de
                  cabeça — o consolidado é o número que abre a conversa no All
                  Hands. Vem do backend, não de soma no frontend (uma reunião com
                  2 responsáveis conta para os dois GCs, mas UMA vez no total). */}
              <div className="mt-3 border-t border-border pt-1">
                <Linha rot="Integracomm · total do mês"
                  val={`${formatNumber(d.assessoria.reunioes.realizadas)} reunião(ões)${
                    d.assessoria.reunioes.satisfacao_geral != null
                      ? ` · ★ ${d.assessoria.reunioes.satisfacao_geral.toLocaleString("pt-BR")}`
                      : ""}`}
                  sub={`${formatNumber(d.assessoria.reunioes.agendadas)} agendadas no total${
                    d.assessoria.reunioes.satisfacao_geral != null
                      ? ` · satisfação média de 1 a 5, sobre ${d.assessoria.reunioes.com_nota} avaliada(s)`
                      : " · nenhuma avaliada"}`}
                  bold />
              </div>
              {/* honestidade sobre a base: a nota cobre ~40% das reuniões e
                  satura em 5 — serve de cobertura/exceção, não de variação */}
              <p className="mt-2 text-xs text-muted-foreground">
                ★ = satisfação média (escala de 1 a 5 do campo do ClickUp, não a escala de NPS);
                entre parênteses, quantas reuniões têm nota. Só {d.assessoria.reunioes.com_nota} das{" "}
                {d.assessoria.reunioes.agendadas} reuniões do mês foram avaliadas — a média vem dessa
                amostra. Reagendadas, canceladas e "não compareceu" contam como agendadas, não como
                realizadas.
                {d.assessoria.reunioes.por_gc.reduce((s, g) => s + g.reunioes, 0) >
                  d.assessoria.reunioes.realizadas && (
                  <>
                    {" "}As barras somam mais que o total porque{" "}
                    {d.assessoria.reunioes.por_gc.reduce((s, g) => s + g.reunioes, 0) -
                      d.assessoria.reunioes.realizadas}{" "}
                    reunião(ões) teve mais de um gerente: aparece para cada um, mas conta uma
                    vez só no total da empresa.
                  </>
                )}
              </p>
            </SectionCard>
          )}

          <SectionCard title="Saídas do mês" headerClassName="min-h-[46px]"
            subtitle={`${formatNumber(d.saidas.total)} saída(s) · ${
              d.saidas.taxa_recorrentes != null
                ? `${(d.saidas.taxa_recorrentes * 100).toFixed(1)}% da base recorrente`
                : "taxa indisponível"}`}>
            {d.saidas.por_plano.length > 0 && (
              <BarListH
                data={d.saidas.por_plano.slice(0, 8).map((s) => ({ label: s.plano, value: s.qtde }))}
                height={Math.max(120, Math.min(8, d.saidas.por_plano.length) * 40)} width={170}
                color="var(--destructive)" valueLabel={(v) => `${v} saída(s)`} />
            )}
            {d.saidas.sem_plano > 0 && (
              <Lacuna txt={`${d.saidas.sem_plano} saída(s) sem plano lançado na planilha`} />
            )}
            <Linha rot="Taxa de cancelamento (recorrentes)"
              val={d.saidas.taxa_recorrentes != null ? `${(d.saidas.taxa_recorrentes * 100).toFixed(1)}%` : "—"}
              sub={`saídas recorrentes ${d.saidas.saidas_rec} ÷ base recorrente ${formatNumber(d.saidas.base_rec)} — B1/Start fora (semestral)`} />
          </SectionCard>
        </div>
        </>
      )}

      {/* a apresentação virou o FECHO da página (Otávio 24/07: All Hands abre
          direto nos dados; gerar os slides é o passo seguinte) */}
      {d && (
        <a href="/allhands?view=apresentacao"
          className="block max-w-2xl rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/50">
          <div className="flex items-center gap-2 font-display text-base font-semibold">
            <Presentation className="h-5 w-5 text-primary" /> Gerar apresentação do All Hands
          </div>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Estes mesmos números viram os slides no design do deck — mais destaques, novos
            colaboradores, orientações e slides extras. Exporta em PDF ou PPTX.
          </p>
        </a>
      )}

      {d && (
        <p className="text-xs text-muted-foreground">
          Fonte: espelho do Pipedrive (funil/vendas) · lista Clientes Ativos do ClickUp (clientes
          por plano, as-of {d.mes_label}) · planilha oficial de cancelamentos. Os mesmos números
          alimentam os slides da apresentação.
        </p>
      )}
    </div>
  );
}
