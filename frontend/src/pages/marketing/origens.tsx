import { CalendarRange } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatBRL, formatPct } from "@/lib/format";
import type { MktOrigensPayload } from "@/types/api";

// Marketing · Origem de Leads (Lote 3) — números prontos de
// /api/marketing/origens (embrulha funil_por_origem de analysis.py — a MESMA
// função da tela HTML; chips escalar?/revisar com as mesmas regras).

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const numCls = "text-right tabular-nums";
const MIDIA = [
  { v: "todas", lbl: "todas as mídias" },
  { v: "pagas", lbl: "mídia paga (Meta/Google)" },
  { v: "organicas", lbl: "não pagas (orgânico/indicação/outros)" },
];

export function MktOrigensPage() {
  const hoje = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const [ini, setIni] = useState(iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)));
  const [fim, setFim] = useState(iso(hoje));
  const [midia, setMidia] = useState("todas");
  const [origem, setOrigem] = useState<string | null>(null);
  const q = useApi<MktOrigensPayload>(
    `/api/marketing/origens?ini=${ini}&fim=${fim}&midia=${midia}${origem ? `&origem=${encodeURIComponent(origem)}` : ""}`);
  const d = q.data;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">
          {origem ? `Origem: ${origem}` : "Análise por Origem de Leads"}
          <Hint area="marketing/origens" titulo="_intro" />
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {origem ? (
            <button className="text-primary hover:underline" onClick={() => setOrigem(null)}>← todas as origens</button>
          ) : (
            <>Funil lead → oportunidade → booking; clique na origem para ver campanhas e criativos.
              {d?.totais && <> · exibindo <b>{MIDIA.find((m) => m.v === midia)?.lbl}</b>: {d.totais.leads} leads, {d.totais.bookings} bookings</>}</>
          )}
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
        <CalendarRange className="h-4 w-4 text-muted-foreground" />
        <Input type="date" value={ini} onChange={(e) => setIni(e.target.value)} className="w-[160px]" />
        <span className="text-xs text-muted-foreground">até</span>
        <Input type="date" value={fim} onChange={(e) => setFim(e.target.value)} className="w-[160px]" />
        {!origem && (
          <Select value={midia} onValueChange={setMidia}>
            <SelectTrigger className="w-[260px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              {MIDIA.map((m) => <SelectItem key={m.v} value={m.v}>{m.lbl}</SelectItem>)}
            </SelectContent>
          </Select>
        )}
      </div>

      {q.loading && <LoadingSkeleton rows={6} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}

      {d && !origem && d.linhas && (
        <SectionCard hint={<Hint area="marketing/origens" titulo="Funil por origem" />}
          title="Funil por origem"
          subtitle="“escalar?” = conversão >1,5× a mediana com volume ainda baixo · “revisar” = volume alto com conversão <0,5× a mediana">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className={thCls}>Origem (utm_source)</TableHead>
                  <TableHead className={`${thCls} text-right`}>Leads</TableHead>
                  <TableHead className={`${thCls} text-right`}>Oportunidades</TableHead>
                  <TableHead className={`${thCls} text-right`}>Bookings</TableHead>
                  <TableHead className={`${thCls} text-right`}>Receita</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.linhas.map((l) => (
                  <TableRow key={l.origem}>
                    <TableCell>
                      <button className="font-medium text-primary hover:underline" onClick={() => setOrigem(l.origem)}>
                        {l.origem}
                      </button>
                      {l.tag && (
                        <Badge variant="outline"
                          className={`ml-2 ${l.tag === "escalar?" ? "border-success/50 text-success" : "border-warning/50 text-warning"}`}>
                          {l.tag}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className={numCls}>{l.leads}</TableCell>
                    <TableCell className={numCls}>{l.oport} ({formatPct(l.oport_pct, 1)})</TableCell>
                    <TableCell className={numCls}>{l.bookings} ({formatPct(l.conv_pct, 1)})</TableCell>
                    <TableCell className={numCls}>{l.receita != null ? formatBRL(l.receita) : "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </SectionCard>
      )}

      {d && origem && d.detalhe && (
        <SectionCard hint={<Hint area="marketing/origens" titulo="Campanhas e criativos da origem" />}
          title="Campanhas e criativos"
          subtitle="o funil da origem selecionada, por utm_campaign e utm_content">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className={thCls}>Campanha</TableHead>
                  <TableHead className={thCls}>Criativo</TableHead>
                  <TableHead className={`${thCls} text-right`}>Leads</TableHead>
                  <TableHead className={`${thCls} text-right`}>Oport</TableHead>
                  <TableHead className={`${thCls} text-right`}>Bookings</TableHead>
                  <TableHead className={`${thCls} text-right`}>Receita</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.detalhe.map((r, i) => (
                  <TableRow key={`${r.campanha}-${r.criativo}-${i}`}>
                    <TableCell className="font-medium">{r.campanha}</TableCell>
                    <TableCell>{r.criativo}</TableCell>
                    <TableCell className={numCls}>{r.leads}</TableCell>
                    <TableCell className={numCls}>{r.oport}</TableCell>
                    <TableCell className={numCls}>{r.bookings}</TableCell>
                    <TableCell className={numCls}>{r.receita != null ? formatBRL(r.receita) : "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </SectionCard>
      )}
    </div>
  );
}
