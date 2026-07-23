import { CalendarRange, Users } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { Heatmap, type HeatmapCell } from "@/components/charts/heatmap";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatBRL, formatNumber, formatPct } from "@/lib/format";

// Vendas · Desempenho Individual (Lote 6) — /api/vendas/closers embrulha
// `sales.dados.vd_closers_dados`, a MESMA função que a tela HTML formata.
// Régua: atribuição pelo DONO do deal. Ticket em MRR — B1 é semestral pago à
// vista, dividido por 6 para comparar com os mensais (senão quem fecha muito
// B1 aparece com "ticket alto" indevidamente).

interface Payload {
  ini: string; fim: string; sem_dados: boolean;
  pessoas: Array<{ nome: string; papel: string; papel_label: string | null;
    oports: number; bookings: number; taxa_conv: number | null;
    ticket: number | null; ciclo_dias: number | null; perdas_top: string | null }>;
  colunas: string[];
  planos_bundle: Array<{ plano: string; celulas: Array<{ nome: string; n: number }> }>;
  horas: Array<{ nome: string; total: number; pico_hora: number; fora: number;
    amostra_pequena: boolean;
    celulas: Array<{ hora: number; n: number; intensidade: number; pico: boolean }> }>;
  horas_eixo: number[];
  acoes_individuais: Array<{ nome: string; fortes: string[]; fracos: string[]; acoes: string[] }>;
  persona: string; coordenacao: string;
}

const th = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const abrev = (n: string) => {
  const p = n.split(" ");
  return p.length < 2 ? n : `${p[0]} ${p[1][0]}.`;
};

export function VendasClosersPage() {
  const hoje = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const [ini, setIni] = useState(iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)));
  const [fim, setFim] = useState(iso(hoje));
  const q = useApi<Payload>(`/api/vendas/closers?ini=${ini}&fim=${fim}`);
  const d = q.data;

  // reuniões closer × hora: cada linha na PRÓPRIA escala (compara o padrão da
  // pessoa, não o volume) — mesma régua do heatmap de PV
  const heat = d && d.horas.length
    ? {
      rows: d.horas.map((h) => abrev(h.nome)),
      cols: d.horas_eixo.map((h) => `${h}h`),
      cells: d.horas.flatMap((h) =>
        h.celulas.filter((c) => c.n > 0).map((c): HeatmapCell => ({
          row: abrev(h.nome), col: `${c.hora}h`, value: c.n, n: h.total,
          amostra_pequena: h.amostra_pequena,
        }))),
    }
    : null;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">
          Desempenho Individual — Vendas
          <Hint area="vendas/closers" titulo="_intro" />
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Dono do deal = atribuição · lista do time editável no Painel Administrativo
          {d && ` · coordenação: ${d.coordenacao}`}
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
        <CalendarRange className="h-4 w-4 text-muted-foreground" />
        <Input type="date" value={ini} onChange={(e) => setIni(e.target.value)} className="w-[160px]" />
        <span className="text-xs text-muted-foreground">até</span>
        <Input type="date" value={fim} onChange={(e) => setFim(e.target.value)} className="w-[160px]" />
      </div>

      {q.loading && <LoadingSkeleton rows={5} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d?.sem_dados && (
        <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
          Sem dono de deal registrado no período — a atribuição por closer depende desse campo no
          Pipedrive.
        </p>
      )}
      {d && !d.sem_dados && (
        <>
          <SectionCard hint={<Hint area="vendas/closers" titulo="Performance por closer" />}
            title="Performance por closer"
            subtitle="ticket em MRR — B1 é semestral pago à vista e entra dividido por 6, para comparar com os mensais · ciclo = mediana da 1ª reunião até o ganho">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableHead className={th}>Closer</TableHead>
                  <TableHead className={`${th} text-right`}>Oports</TableHead>
                  <TableHead className={`${th} text-right`}>Bookings</TableHead>
                  <TableHead className={`${th} text-right`}>Conversão</TableHead>
                  <TableHead className={`${th} text-right`}>Ticket (MRR)</TableHead>
                  <TableHead className={`${th} text-right`}>Ciclo (med.)</TableHead>
                  <TableHead className={th}>Perda nº1</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.pessoas.map((p) => (
                  <TableRow key={p.nome}>
                    <TableCell className="font-medium">
                      {p.nome}
                      {p.papel_label && (
                        <Badge variant="outline" className="ml-2 border-primary/50 text-[10px] text-primary">
                          {p.papel_label}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{p.oports}</TableCell>
                    <TableCell className="text-right tabular-nums">{p.bookings}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {p.taxa_conv != null ? formatPct(p.taxa_conv * 100, 1) : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatBRL(p.ticket)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {p.ciclo_dias != null ? `${p.ciclo_dias.toFixed(0)} d` : "—"}
                    </TableCell>
                    <TableCell className="max-w-[220px] truncate text-sm text-muted-foreground"
                      title={p.perdas_top ?? ""}>
                      {p.perdas_top ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </SectionCard>

          {d.planos_bundle.length > 0 && (
            <SectionCard hint={<Hint area="vendas/closers" titulo="Fechamentos por plano × closer" />}
              title="Fechamentos por plano × closer"
              subtitle="contratos ganhos no período por bundle — quem fecha o quê; forte em B1 e zerado em B3–B5 = treinar oferta para cima (prioridade da empresa)">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/40 hover:bg-muted/40">
                      <TableHead className={th}>Plano</TableHead>
                      {d.colunas.map((c) => (
                        <TableHead key={c} className={`${th} text-center`} title={c}>{abrev(c)}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.planos_bundle.map((p) => (
                      <TableRow key={p.plano}>
                        <TableCell className="font-medium">{p.plano}</TableCell>
                        {p.celulas.map((c) => (
                          <TableCell key={c.nome} className="text-center tabular-nums">
                            {c.n || <span className="text-muted-foreground/60">—</span>}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </SectionCard>
          )}

          {heat && (
            <SectionCard hint={<Hint area="vendas/closers" titulo="Reuniões por closer × hora" />}
              title="Reuniões por closer × hora"
              subtitle="1ª entrada do deal em Negociação (proxy da reunião realizada; o carimbo é a movimentação do card) · cada linha na PRÓPRIA escala · hachura = amostra pequena (menos de 30 reuniões)">
              <Heatmap rows={heat.rows} cols={heat.cols} cells={heat.cells}
                color="var(--chart-1)" rowScale dense scrollX rowLabelWidth={110}
                legendLabel="reuniões"
                tooltipLabel={(c) => `${c.row} ${c.col}: ${c.value} reunião(ões)`} />
              {d.horas.some((h) => h.fora > 0) && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Reuniões fora da janela 7h–20h:{" "}
                  {d.horas.filter((h) => h.fora > 0).map((h) => `${abrev(h.nome)} ${h.fora}`).join(" · ")}
                </p>
              )}
            </SectionCard>
          )}

          {d.acoes_individuais.length > 0 && (
            <SectionCard hint={<Hint area="vendas/closers" titulo="Planos de ação individuais" />}
              title="Planos de ação individuais"
              subtitle={`${d.persona} · comparação com a mediana do time (coordenação e gerência ficam fora da mediana)`}>
              <div className="space-y-4">
                {d.acoes_individuais.map((x) => (
                  <div key={x.nome} className="rounded-xl border border-border p-4">
                    <div className="flex items-center gap-2">
                      <Users className="h-4 w-4 text-muted-foreground" />
                      <b className="text-sm">{x.nome}</b>
                    </div>
                    <ul className="mt-2 space-y-1 text-sm">
                      {x.fortes.map((f) => <li key={f} className="text-success">• {f}</li>)}
                      {x.fracos.map((f) => <li key={f} className="text-warning">• {f}</li>)}
                      {x.acoes.map((a) => <li key={a} className="text-muted-foreground">→ {a}</li>)}
                    </ul>
                  </div>
                ))}
              </div>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}
