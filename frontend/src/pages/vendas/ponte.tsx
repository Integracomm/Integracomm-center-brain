import { CalendarRange, GitBranch, Hourglass, Target } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { SectionCard } from "@/components/blocks/section-card";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatPct } from "@/lib/format";
import type { PonteSegItem, VendasPontePayload } from "@/types/api";

// Vendas · Ponte PV → Vendas (Lote 3) — a conversão fraca é herdada da
// qualificação ou é do fechamento? Números prontos de /api/vendas/ponte
// (mesmas queries/leitura da tela HTML — paridade checada). Taxa SEMPRE
// sobre decididas (ganhas+perdidas); em aberto fica fora.

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const numCls = "text-right tabular-nums";

function SegTable({ rotulo, itens }: { rotulo: string; itens: PonteSegItem[] }) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className={thCls}>{rotulo}</TableHead>
            <TableHead className={`${thCls} text-right`}>Oports</TableHead>
            <TableHead className={`${thCls} text-right`}>Fechadas</TableHead>
            <TableHead className={`${thCls} text-right`}>Perdidas</TableHead>
            <TableHead className={`${thCls} text-right`}>Em aberto</TableHead>
            <TableHead className={`${thCls} text-right`}>Taxa</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {itens.map((s) => (
            <TableRow key={s.rotulo}>
              <TableCell className="font-medium">{s.rotulo}</TableCell>
              <TableCell className={numCls}>{s.oports}</TableCell>
              <TableCell className={numCls}>{s.fechadas}</TableCell>
              <TableCell className={numCls}>{s.perdidas}</TableCell>
              <TableCell className={numCls}>{s.em_aberto}</TableCell>
              <TableCell className={`${numCls} font-semibold`}>
                {s.taxa_pct != null ? formatPct(s.taxa_pct, 1) : "—"}
                {s.amostra_pequena && (
                  <span className="ml-2 text-[10px] font-normal text-muted-foreground">amostra pequena</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function VendasPontePage() {
  const hoje = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const [ini, setIni] = useState(iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)));
  const [fim, setFim] = useState(iso(hoje));
  const q = useApi<VendasPontePayload>(`/api/vendas/ponte?ini=${ini}&fim=${fim}`);
  const d = q.data;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Ponte PV → Vendas<Hint area="vendas/ponte" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          A pergunta estratégica: a conversão fraca é herdada da qualificação ou é do fechamento? ·
          oportunidades do período (Dia Oportunidade) × desfecho · taxa sobre decididas.
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
      {d && d.kpis.oportunidades === 0 && (
        <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
          Sem oportunidades no período selecionado.
        </p>
      )}
      {d && d.kpis.oportunidades > 0 && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
            <KpiCard icon={GitBranch} tone="primary" title="Oportunidades no período"
              value={d.kpis.oportunidades.toLocaleString("pt-BR")} />
            <KpiCard icon={Target} tone="accent" title="Fechamento no período"
              value={d.kpis.fechamento_pct != null ? formatPct(d.kpis.fechamento_pct, 1) : "—"}
              subtitle={`${d.kpis.fechadas} ÷ ${d.kpis.decididas} decididas`}
              caveat="oportunidades (Dia Oportunidade) do período, todas as origens — o Raio-X usa janela fixa (30/90/120d): números podem diferir" />
            <KpiCard icon={Hourglass} tone="muted" title="Ainda em aberto"
              value={d.kpis.em_aberto.toLocaleString("pt-BR")} />
          </div>

          <SectionCard hint={<Hint area="vendas/ponte" titulo="Leitura do especialista" />}
            title="Leitura do especialista"
            subtitle={`gerada por ${d.leitura.fonte} — hipótese para investigar, não veredito`}>
            <p className="text-sm leading-relaxed">→ {d.leitura.texto}</p>
          </SectionCard>

          <div className="grid gap-6 xl:grid-cols-2">
            <SectionCard hint={<Hint area="vendas/ponte" titulo="Por SLA do 1º contato" />}
              headerClassName="min-h-[56px]" title="Por SLA do 1º contato"
              subtitle="a tese do speed-to-lead medida no CAIXA: lead atendido rápido fecha mais?">
              <SegTable rotulo="1º contato" itens={d.por_sla} />
            </SectionCard>
            <SectionCard hint={<Hint area="vendas/ponte" titulo="Por tempo de qualificação" />}
              headerClassName="min-h-[56px]" title="Por tempo de qualificação"
              subtitle="dias entre o lead entrar e virar oportunidade">
              <SegTable rotulo="Lead → oportunidade" itens={d.por_tempo_qualificacao} />
            </SectionCard>
          </div>

          <SectionCard hint={<Hint area="vendas/ponte" titulo="Por origem do lead" />}
            title="Por origem do lead" subtitle="as 8 origens com mais oportunidades no período">
            <SegTable rotulo="Origem" itens={d.por_origem} />
          </SectionCard>

          <div className="grid gap-6 xl:grid-cols-2">
            <SectionCard hint={<Hint area="vendas/ponte" titulo="Por SDR que qualificou" />}
              headerClassName="min-h-[56px]" title="Por SDR que qualificou"
              subtitle="a taxa de fechamento das oportunidades entregues por cada SDR — qualidade da entrega, não volume">
              <SegTable rotulo="SDR" itens={d.por_sdr} />
            </SectionCard>
            <SectionCard hint={<Hint area="vendas/ponte" titulo="Por closer" />}
              headerClassName="min-h-[56px]" title="Por closer"
              subtitle="a mesma qualificação nas mãos de cada closer — o outro lado da ponte">
              <SegTable rotulo="Closer" itens={d.por_closer} />
            </SectionCard>
          </div>
        </>
      )}
    </div>
  );
}
