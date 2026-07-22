import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatBRL, formatPct } from "@/lib/format";

// Marketing · Criativos e Públicos (Lote 4) — /api/marketing/criativos.
// Veredito (escalar/revisar/pausar/manter) vem do BACKEND pela mediana do
// conjunto — o frontend só pinta. Mesmas regras da tela HTML.

interface Payload {
  publico: string | null; publicos: string[];
  medianas: { cpl: number | null; conv_pct: number | null };
  criativos: Array<{ criativo: string; publico: string; gasto: number; leads: number;
    cpl: number | null; conv_pct: number | null; bookings: number; veredito: string | null }>;
  elementos: Array<{ elemento: string; criativos: number; leads: number; cpl: number;
    conv_pct: number | null; destaque: string | null }>;
  criativo_x_plano: { planos: string[];
    linhas: Array<{ criativo: string; por_plano: Record<string, number>; total: number; traz_b2_b5: boolean }> };
  leitura: string[];
  testes: Array<{ anuncio: string; publico: string; formato: string; inicio: string; dias_ativo: number | null }>;
  n_testes: number; testes_aviso: string | null; ideias: string[];
}

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const numCls = "text-right tabular-nums";
const CORES: Record<string, string> = {
  escalar: "border-success/50 text-success",
  pausar: "border-destructive/50 text-destructive",
  revisar: "border-warning/50 text-warning",
  manter: "border-border text-muted-foreground",
};

export function MktCriativosPage() {
  const [publico, setPublico] = useState("__todos");
  const q = useApi<Payload>(`/api/marketing/criativos${publico !== "__todos" ? `?publico=${encodeURIComponent(publico)}` : ""}`);
  const d = q.data;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Criativos e Públicos<Hint area="marketing/criativos" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          O que escalar, revisar ou pausar — e que promessa traz o cliente certo · veredito pela mediana
          do conjunto · conversão via atribuição do Pipedrive (utm_content).
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
        <span className="text-xs text-muted-foreground">público (adset)</span>
        <Select value={publico} onValueChange={setPublico}>
          <SelectTrigger className="w-[320px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__todos">todos</SelectItem>
            {d?.publicos.map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}
          </SelectContent>
        </Select>
        {d && (
          <span className="text-xs text-muted-foreground">
            medianas do conjunto: CPL {d.medianas.cpl != null ? formatBRL(d.medianas.cpl) : "—"} · conversão{" "}
            {d.medianas.conv_pct != null ? formatPct(d.medianas.conv_pct, 1) : "—"}
          </span>
        )}
      </div>

      {q.loading && <LoadingSkeleton rows={6} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && (
        <>
          <SectionCard hint={<Hint area="marketing/criativos" titulo="Leitura do especialista" />}
            title="Leitura do especialista"
            subtitle="gerada por regras determinísticas sobre as medianas do conjunto — hipótese, não veredito">
            <div className="space-y-2">
              {(d.leitura.length ? d.leitura : ["Sem volume suficiente para leitura automática neste filtro."]).map((t) => (
                <p key={t} className="border-t border-border pt-2 text-sm leading-relaxed first:border-t-0 first:pt-0">→ {t}</p>
              ))}
            </div>
          </SectionCard>

          <SectionCard hint={<Hint area="marketing/criativos" titulo="Desempenho por criativo" />}
            title="Desempenho por criativo"
            subtitle="ranking por CPL (mín. 5 leads) · escalar = conversão acima da mediana · revisar = conversão fraca com gasto relevante · pausar = CPL alto E conversão fraca">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Criativo</TableHead>
                    <TableHead className={thCls}>Público</TableHead>
                    <TableHead className={`${thCls} text-right`}>Gasto</TableHead>
                    <TableHead className={`${thCls} text-right`}>Leads</TableHead>
                    <TableHead className={`${thCls} text-right`}>CPL</TableHead>
                    <TableHead className={`${thCls} text-right`}>Lead→Oport</TableHead>
                    <TableHead className={`${thCls} text-right`}>Bookings</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.criativos.map((c) => (
                    <TableRow key={c.criativo}>
                      <TableCell className="font-medium">
                        {c.criativo}
                        {c.veredito && (
                          <Badge variant="outline" className={`ml-2 ${CORES[c.veredito] ?? ""}`}>{c.veredito}</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">{c.publico}</TableCell>
                      <TableCell className={numCls}>{formatBRL(c.gasto)}</TableCell>
                      <TableCell className={numCls}>{c.leads}</TableCell>
                      <TableCell className={numCls}>{c.cpl != null ? formatBRL(c.cpl) : "—"}</TableCell>
                      <TableCell className={numCls}>{c.conv_pct != null ? formatPct(c.conv_pct, 1) : "—"}</TableCell>
                      <TableCell className={numCls}>{c.bookings}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </SectionCard>

          {d.elementos.length > 0 && (
            <SectionCard hint={<Hint area="marketing/criativos" titulo="Elementos que funcionam" />}
              title="Elementos que funcionam"
              subtitle="performance agregada por PALAVRA no nome do criativo (mín. 2 criativos e 30 leads) — o padrão vencedor vira brief">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Elemento</TableHead>
                    <TableHead className={`${thCls} text-right`}>Leads</TableHead>
                    <TableHead className={`${thCls} text-right`}>CPL</TableHead>
                    <TableHead className={`${thCls} text-right`}>Lead→Oport</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.elementos.map((e) => (
                    <TableRow key={e.elemento}>
                      <TableCell>
                        <b>{e.elemento}</b>{" "}
                        <span className="text-xs text-muted-foreground">({e.criativos} criativos)</span>
                      </TableCell>
                      <TableCell className={numCls}>{e.leads}</TableCell>
                      <TableCell className={numCls}>{formatBRL(e.cpl)}</TableCell>
                      <TableCell className={`${numCls} ${e.destaque === "pos" ? "text-success" : e.destaque === "neg" ? "text-destructive" : ""}`}>
                        {e.conv_pct != null ? formatPct(e.conv_pct, 1) : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </SectionCard>
          )}

          {d.criativo_x_plano.linhas.length > 0 && (
            <SectionCard hint={<Hint area="marketing/criativos" titulo="Criativo × plano fechado" />}
              title="Criativo × plano fechado"
              subtitle="bookings por criativo e bundle (histórico atribuído) — qual promessa traz o cliente que a empresa QUER (B2-B5) · cruze com Ciclo de Vida p/ ver se ele também FICA">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className={thCls}>Criativo</TableHead>
                      {d.criativo_x_plano.planos.map((p) => (
                        <TableHead key={p} className={`${thCls} text-right`}>{p}</TableHead>
                      ))}
                      <TableHead className={`${thCls} text-right`}>Total</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.criativo_x_plano.linhas.map((l) => (
                      <TableRow key={l.criativo}>
                        <TableCell className="font-medium">
                          {l.criativo}
                          {l.traz_b2_b5 && (
                            <Badge variant="outline" className="ml-2 border-success/50 text-success">traz B2-B5</Badge>
                          )}
                        </TableCell>
                        {d.criativo_x_plano.planos.map((p) => (
                          <TableCell key={p} className={numCls}>{l.por_plano[p] || "—"}</TableCell>
                        ))}
                        <TableCell className={`${numCls} font-semibold`}>{l.total}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </SectionCard>
          )}

          <SectionCard hint={<Hint area="marketing/criativos" titulo="Histórico de testes" />}
            title="Histórico de testes (ad-insightify)"
            subtitle={d.testes_aviso ?? `${d.n_testes} rodadas registradas · 15 mais recentes`}>
            {d.testes_aviso ? (
              <p className="text-sm text-muted-foreground">{d.testes_aviso}</p>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className={thCls}>Anúncio</TableHead>
                      <TableHead className={thCls}>Público</TableHead>
                      <TableHead className={thCls}>Formato</TableHead>
                      <TableHead className={`${thCls} text-right`}>Início</TableHead>
                      <TableHead className={`${thCls} text-right`}>Dias ativo</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.testes.map((t, i) => (
                      <TableRow key={`${t.anuncio}-${i}`}>
                        <TableCell className="font-medium">{t.anuncio}</TableCell>
                        <TableCell className="text-sm text-muted-foreground">{t.publico}</TableCell>
                        <TableCell>{t.formato}</TableCell>
                        <TableCell className={numCls}>{t.inicio ? t.inicio.split("-").reverse().join("/") : "—"}</TableCell>
                        <TableCell className={numCls}>{t.dias_ativo ?? "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </SectionCard>

          {d.ideias.length > 0 && (
            <SectionCard hint={<Hint area="marketing/criativos" titulo="Ideias" />}
              title="Ideias (v1 heurística)"
              subtitle="combinações formato × público ainda não testadas, priorizadas pelos top performers">
              <ul className="space-y-1.5 text-sm text-muted-foreground">
                {d.ideias.map((i) => (
                  <li key={i} className="border-t border-border pt-1.5 first:border-t-0 first:pt-0">{i}</li>
                ))}
              </ul>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}
