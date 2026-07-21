import { CalendarRange } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatBRL, formatPct } from "@/lib/format";
import type { MktCanaisPayload } from "@/types/api";

// Marketing · Ranking de Canais (Lote 3) — números prontos de
// /api/marketing/canais (embrulha ranking_canais de analysis.py — a MESMA
// função da tela HTML; paridade checada).

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const numCls = "text-right tabular-nums";
const brl = (v: number | null) => (v != null ? formatBRL(v) : "—");

export function MktCanaisPage() {
  const hoje = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const [ini, setIni] = useState(iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)));
  const [fim, setFim] = useState(iso(hoje));
  const q = useApi<MktCanaisPayload>(`/api/marketing/canais?ini=${ini}&fim=${fim}`);
  const d = q.data;
  const maxLeads = d ? Math.max(...d.canais.map((c) => c.leads), 1) : 1;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Ranking de Canais<Hint area="marketing/canais" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Período selecionável · comparativo de leads vs período anterior equivalente.
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
      {d && (
        <>
          <SectionCard hint={<Hint area="marketing/canais" titulo="Ranking de canais" />}
            title="Ranking de canais"
            subtitle="canais sem custo de mídia: CPL/CAC “—” (custo zero) · Oportunidade = régua de coorte (qualidade do lead) · detalhes no ⓘ">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Canal</TableHead>
                    <TableHead className={`${thCls} text-right`}>Gasto</TableHead>
                    <TableHead className={`${thCls} text-right`}>Leads</TableHead>
                    <TableHead className={`${thCls} text-right`}>CPL</TableHead>
                    <TableHead className={`${thCls} text-right`}>Lead→Oport</TableHead>
                    <TableHead className={`${thCls} text-right`}>Bookings</TableHead>
                    <TableHead className={`${thCls} text-right`}>Lead→Book</TableHead>
                    <TableHead className={`${thCls} text-right`}>Receita</TableHead>
                    <TableHead className={`${thCls} text-right`}>CAC</TableHead>
                    <TableHead className={`${thCls} text-right`}>ROAS</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.canais.map((c) => (
                    <TableRow key={c.canal}>
                      <TableCell className="font-medium">{c.canal}</TableCell>
                      <TableCell className={numCls}>{brl(c.gasto)}</TableCell>
                      <TableCell className={numCls}>
                        <span className="inline-flex items-center gap-2">
                          <span className="inline-block h-1.5 rounded bg-primary/60"
                            style={{ width: `${Math.max((c.leads / maxLeads) * 46, 2)}px` }} />
                          {c.leads}
                          {c.var_leads_pct != null && (
                            <span className={`text-[10px] ${c.var_leads_pct >= 0 ? "text-success" : "text-destructive"}`}>
                              ({c.var_leads_pct >= 0 ? "+" : ""}{c.var_leads_pct.toFixed(0)}%)
                            </span>
                          )}
                        </span>
                      </TableCell>
                      <TableCell className={numCls}>{brl(c.cpl)}</TableCell>
                      <TableCell className={numCls}>{c.conv_lead_oport_pct != null ? formatPct(c.conv_lead_oport_pct, 1) : "—"}</TableCell>
                      <TableCell className={numCls}>{c.bookings}</TableCell>
                      <TableCell className={numCls}>{c.conv_lead_book_pct != null ? formatPct(c.conv_lead_book_pct, 1) : "—"}</TableCell>
                      <TableCell className={numCls}>{brl(c.receita)}</TableCell>
                      <TableCell className={numCls}>{brl(c.cac)}</TableCell>
                      <TableCell className={numCls}>{c.roas != null ? `${c.roas.toFixed(1)}x` : "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </SectionCard>

          <SectionCard hint={<Hint area="marketing/canais" titulo="Evolução mensal — mídia paga" />}
            title="Evolução mensal — mídia paga (6 meses)"
            subtitle="leads = coorte do mês · CPL = gasto ÷ leads · CAC = gasto ÷ bookings da coorte (mês recente subestima — o lead ainda converte)">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Canal · métrica</TableHead>
                    {d.meses.map((m) => (
                      <TableHead key={m} className={`${thCls} text-right`}>{m}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.evolucao.flatMap((e) => ([
                    <TableRow key={`${e.canal}-leads`}>
                      <TableCell className="font-medium">{e.canal} · Leads</TableCell>
                      {e.meses.map((m) => <TableCell key={m.mes} className={numCls}>{m.leads || "—"}</TableCell>)}
                    </TableRow>,
                    <TableRow key={`${e.canal}-cpl`}>
                      <TableCell className="font-medium">{e.canal} · CPL</TableCell>
                      {e.meses.map((m) => <TableCell key={m.mes} className={numCls}>{m.cpl != null ? formatBRL(m.cpl) : "—"}</TableCell>)}
                    </TableRow>,
                    <TableRow key={`${e.canal}-cac`}>
                      <TableCell className="font-medium">{e.canal} · CAC</TableCell>
                      {e.meses.map((m) => <TableCell key={m.mes} className={numCls}>{m.cac != null ? formatBRL(m.cac) : "—"}</TableCell>)}
                    </TableRow>,
                  ]))}
                </TableBody>
              </Table>
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}
