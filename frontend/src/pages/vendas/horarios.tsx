import { CalendarRange, Clock, PhoneCall, Target, Timer } from "lucide-react";
import { useMemo, useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { SectionCard } from "@/components/blocks/section-card";
import { Heatmap, type HeatmapCell } from "@/components/charts/heatmap";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatNumber, formatPct } from "@/lib/format";

// Vendas · Melhor Horário (Lote 6) — /api/vendas/horarios embrulha
// `sales.dados.vd_horarios_dados`.
//
// É uma tela DIFERENTE da de Pré-vendas, apesar do nome igual (Otávio 23/07):
// lá a pergunta é quando o lead ATENDE a ligação; aqui é em que horário a
// REUNIÃO fecha mais. Base: 1ª entrada do deal em Negociação — o card é movido
// depois da reunião, então o carimbo é o proxy de quando ela aconteceu.
//
// TAXA = ganhas ÷ DECIDIDAS da própria coorte. Deal ainda aberto não derruba a
// taxa — por isso ela difere da taxa do funil, que mistura coortes.

const DOW = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const th = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";

interface Payload {
  ini: string; fim: string; bundle: string; sem_dados: boolean;
  celulas: Array<{ dow: number; hora: number; n: number; won: number; lost: number;
    abertas: number; taxa: number | null }>;
  dows: number[]; horas: number[];
  por_hora: Array<{ hora: number; reunioes: number; won: number; lost: number;
    abertas: number; taxa: number | null; amostra_pequena: boolean }>;
  kpis: { reunioes: number; won: number; lost: number; decididas: number;
    abertas: number; taxa: number | null; melhor_hora: number | null;
    melhor_taxa: number | null; melhor_dec: number | null };
}

export function VendasHorariosPage() {
  const hoje = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const [ini, setIni] = useState(iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)));
  const [fim, setFim] = useState(iso(hoje));
  const [bundle, setBundle] = useState("todos");
  const q = useApi<Payload>(`/api/vendas/horarios?ini=${ini}&fim=${fim}&bundle=${bundle}`);
  const d = q.data;

  const heat = useMemo(() => {
    if (!d || d.sem_dados) return null;
    const cells: HeatmapCell[] = d.celulas.map((c) => ({
      row: `${String(c.hora).padStart(2, "0")}h`,
      col: DOW[c.dow],
      value: c.n,
      n: c.won + c.lost,
    }));
    return {
      rows: d.horas.map((h) => `${String(h).padStart(2, "0")}h`),
      cols: d.dows.map((x) => DOW[x]),
      cells,
      // o desfecho da célula vai no tooltip, como no HTML
      info: new Map(d.celulas.map((c) => [
        `${String(c.hora).padStart(2, "0")}h||${DOW[c.dow]}`, c,
      ])),
    };
  }, [d]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">
          Melhor Horário — reuniões de Vendas
          <Hint area="vendas/horarios" titulo="_intro" />
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Momento em que o deal ENTROU em Negociação (horário de Brasília) — o card é movido após a
          reunião, então é o proxy de quando ela aconteceu. A taxa é <b>ganhas ÷ decididas</b> da
          própria coorte (as em aberto não contam), por isso pode diferir da taxa do funil, que
          divide os bookings do mês pelas oportunidades do mês misturando coortes.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
        <CalendarRange className="h-4 w-4 text-muted-foreground" />
        <Input type="date" value={ini} onChange={(e) => setIni(e.target.value)} className="w-[160px]" />
        <span className="text-xs text-muted-foreground">até</span>
        <Input type="date" value={fim} onChange={(e) => setFim(e.target.value)} className="w-[160px]" />
        <Select value={bundle} onValueChange={setBundle}>
          <SelectTrigger className="w-[170px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos os bundles</SelectItem>
            {["B1", "B2", "B3", "B4", "B5"].map((b) => <SelectItem key={b} value={b}>{b}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {q.loading && <LoadingSkeleton rows={4} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d?.sem_dados && (
        <p className="rounded-xl border border-warning/40 bg-card p-4 text-sm">
          Sem reuniões no período/filtro selecionado.
        </p>
      )}
      {d && !d.sem_dados && (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <KpiCard icon={PhoneCall} tone="primary" title="Reuniões no período"
              value={formatNumber(d.kpis.reunioes)} subtitle="1ª entrada em Negociação" />
            <KpiCard icon={Target} tone="success" title="Taxa de fechamento"
              value={d.kpis.taxa != null ? formatPct(d.kpis.taxa * 100, 1) : "—"}
              subtitle={`${d.kpis.won} ganhas ÷ ${d.kpis.decididas} decididas`} />
            <KpiCard icon={Timer} tone="muted" title="Ainda em aberto"
              value={formatNumber(d.kpis.abertas)}
              caveat="fora da taxa — a coorte segue amadurecendo, então a taxa pode mudar" />
            <KpiCard icon={Clock} tone="accent" title="Melhor hora (conversão)"
              value={d.kpis.melhor_hora != null
                ? `${String(d.kpis.melhor_hora).padStart(2, "0")}h`
                : "—"}
              subtitle={d.kpis.melhor_hora != null
                ? `${formatPct((d.kpis.melhor_taxa ?? 0) * 100, 1)} em ${d.kpis.melhor_dec} decididas`
                : undefined}
              caveat="só entram horas com 15+ reuniões decididas — abaixo disso é ruído" />
          </div>

          {heat && (
            <SectionCard hint={<Hint area="vendas/horarios" titulo="Mapa de calor" />}
              title="Mapa de calor — dia da semana × hora"
              subtitle={`período ${d.ini.split("-").reverse().join("/")} a ${d.fim.split("-").reverse().join("/")}${
                d.bundle !== "todos" ? ` · bundle ${d.bundle}` : ""
              } · quanto mais escuro, mais reuniões · passe o mouse para ver o desfecho da célula`}>
              <Heatmap rows={heat.rows} cols={heat.cols} cells={heat.cells}
                color="var(--chart-1)" dense rowLabelWidth={54} legendLabel="reuniões"
                tooltipLabel={(c) => {
                  const x = heat.info.get(`${c.row}||${c.col}`);
                  if (!x) return `${c.row} × ${c.col}: sem dado`;
                  const dec = x.won + x.lost;
                  return `${c.col} ${c.row} — ${x.n} reunião(ões): ${x.won} fechada(s), `
                    + `${x.lost} perdida(s), ${x.abertas} em aberto`
                    + (dec ? ` · taxa ${((x.taxa ?? 0) * 100).toFixed(0)}% das decididas` : "");
                }} />
            </SectionCard>
          )}

          <SectionCard hint={<Hint area="vendas/horarios" titulo="Conversão por hora da reunião" />}
            title="Conversão por hora da reunião"
            subtitle="a pergunta central: reunião em qual horário FECHA mais? · taxa sobre as decididas (ganhas + perdidas) · use janelas com amostra razoável antes de mudar a agenda do time">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableHead className={th}>Hora</TableHead>
                  <TableHead className={`${th} text-right`}>Reuniões</TableHead>
                  <TableHead className={`${th} text-right`}>Fechadas</TableHead>
                  <TableHead className={`${th} text-right`}>Perdidas</TableHead>
                  <TableHead className={`${th} text-right`}>Em aberto</TableHead>
                  <TableHead className={`${th} text-right`}>Taxa</TableHead>
                  <TableHead className={th} />
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.por_hora.map((h) => (
                  <TableRow key={h.hora}>
                    <TableCell className="font-semibold">{String(h.hora).padStart(2, "0")}h</TableCell>
                    <TableCell className="text-right tabular-nums">{h.reunioes}</TableCell>
                    <TableCell className="text-right tabular-nums">{h.won}</TableCell>
                    <TableCell className="text-right tabular-nums">{h.lost}</TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">{h.abertas}</TableCell>
                    <TableCell className="text-right font-semibold tabular-nums">
                      {h.taxa != null ? formatPct(h.taxa * 100, 1) : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {/* a ressalva anda AO LADO do número, não no rodapé */}
                      {h.amostra_pequena && "amostra pequena"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </SectionCard>
        </>
      )}
    </div>
  );
}
