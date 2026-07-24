import { AlertTriangle } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
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
    total: number; leitura_tardia: boolean };
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
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <LoadingSkeleton rows={2} /><LoadingSkeleton rows={2} /><LoadingSkeleton rows={2} />
        </div>
      )}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}

      {d && (
        <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
          <SectionCard title="Marketing">
            <Linha rot="Leads gerados" val={formatNumber(d.marketing.leads)} />
            <Linha rot="Oportunidades geradas" val={formatNumber(d.marketing.oportunidades)}
              sub="régua retroativa — o número se move enquanto a fila é qualificada" />
            <Linha rot="Vendas" val={formatNumber(d.marketing.vendas)} />
            {d.lacunas.marketing?.map((l) => <Lacuna key={l} txt={l} />)}
          </SectionCard>

          <SectionCard title="Pré-vendas">
            <Linha rot="Leads totais" val={formatNumber(d.marketing.leads)} />
            <Linha rot="MQLs" val={formatNumber(d.marketing.mqls)} />
            <Linha rot="SALs" val={formatNumber(d.marketing.sals)} />
            <Linha rot="SQLs" val={formatNumber(d.marketing.sqls)} />
            <Linha rot="Oportunidades" val={formatNumber(d.marketing.oportunidades)} />
            <p className="mt-2 text-xs text-muted-foreground">
              mesma régua do funil oficial de Marketing — as duas áreas fecham com os mesmos números
              por definição
            </p>
          </SectionCard>

          <SectionCard title="Vendas — bookings por plano">
            {d.vendas.por_plano.map((v) => (
              <Linha key={v.plano} rot={v.plano}
                val={`${v.qtde}${v.receita ? ` · ${formatBRL(v.receita)}` : ""}`} />
            ))}
            <Linha rot="Total" val={`${d.vendas.total} · ${formatBRL(d.vendas.receita)}`} bold />
          </SectionCard>

          <SectionCard title={`Assessoria — clientes ativos por plano (${formatNumber(d.assessoria.total)})`}>
            {d.assessoria.clientes_plano.map((c) => (
              <Linha key={c.plano} rot={c.plano} val={formatNumber(c.qtde)} />
            ))}
            <Linha rot="Total" val={formatNumber(d.assessoria.total)} bold />
            {d.assessoria.leitura_tardia && (
              <Lacuna txt="leitura tardia: a contagem retroativa SUBCONTA (cancelados desde o fechamento saem da lista Clientes Ativos) — o número oficial é o do deck gerado logo após o mês virar" />
            )}
            {d.lacunas.assessoria?.map((l) => <Lacuna key={l} txt={l} />)}
          </SectionCard>

          <SectionCard title="Estratégia">
            <Linha rot="Clientes ativos" val={formatNumber(d.estrategia.clientes)}
              sub="da lista Clientes Ativos do ClickUp (as-of fim do mês)" />
            {d.lacunas.estrategia?.map((l) => <Lacuna key={l} txt={l} />)}
          </SectionCard>

          <SectionCard title="Saídas do mês">
            {d.saidas.por_plano.slice(0, 8).map((s) => (
              <Linha key={s.plano} rot={s.plano} val={formatNumber(s.qtde)} />
            ))}
            {d.saidas.sem_plano > 0 && (
              <Lacuna txt={`${d.saidas.sem_plano} saída(s) sem plano lançado na planilha`} />
            )}
            <Linha rot="Total de saídas" val={formatNumber(d.saidas.total)} bold />
            <Linha rot="Taxa de cancelamento (recorrentes)"
              val={d.saidas.taxa_recorrentes != null ? `${(d.saidas.taxa_recorrentes * 100).toFixed(1)}%` : "—"}
              sub={`saídas recorrentes ${d.saidas.saidas_rec} ÷ base recorrente ${formatNumber(d.saidas.base_rec)} — B1/Start fora (semestral)`} />
          </SectionCard>
        </div>
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
