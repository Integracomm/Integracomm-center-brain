import { CalendarRange, Users } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { formatNumber, formatPct } from "@/lib/format";

// Pré-vendas · Desempenho Individual (Lote 6) — /api/prevendas/sdrs embrulha
// `sales.dados.pv_sdrs_dados`, a MESMA função que a tela HTML formata.
// Régua (dos gráficos do Pipedrive que a gestão acompanha): atribuição pelo
// campo SDR do deal, SEM fallback; leads = criados no período; oportunidades =
// Dia Oportunidade no período; bookings = won no período.

interface Celula { nome: string; n: number; oport?: number; taxa?: number | null;
  tom?: string | null; amostra_pequena?: boolean; pct?: number }
interface Payload {
  ini: string; fim: string;
  pessoas: Array<{ nome: string; sem_sdr: boolean; papel: string | null;
    papel_label: string | null; leads: number; oport: number; taxa: number | null;
    bookings: number; speed_min: number | null }>;
  total: { leads: number; oport: number; book: number; taxa: number | null };
  ex_colaboradores: { leads: number; oport: number; book: number } | null;
  colunas: string[];
  desqualificacao: Array<{ nome: string; total: number; leads: number;
    motivos: Array<{ motivo: string; n: number; pct: number; sem_motivo: boolean }> }>;
  origens: Array<{ origem: string; leads: number; oport: number; taxa_time: number;
    celulas: Celula[] }>;
  planos: Array<{ plano: string; celulas: Celula[] }>;
  acoes_individuais: Array<{ nome: string; fortes: string[]; fracos: string[]; acoes: string[] }>;
  persona: string; coordenacao: string;
}

const th = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const abrev = (n: string) => {
  const p = n.split(" ");
  return p.length < 2 ? n : `${p[0]} ${p[1][0]}.`;
};
// speed vem em MINUTOS; acima de 2h a leitura em horas é mais honesta
const fmtSpeed = (m: number | null) =>
  m == null ? "—" : m < 120 ? `${m.toFixed(0)} min` : `${(m / 60).toFixed(1)} h`;

export function PrevendasSdrsPage() {
  const hoje = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const [ini, setIni] = useState(iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)));
  const [fim, setFim] = useState(iso(hoje));
  const q = useApi<Payload>(`/api/prevendas/sdrs?ini=${ini}&fim=${fim}`);
  const d = q.data;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">
          Desempenho Individual — Pré-vendas
          <Hint area="prevendas/sdrs" titulo="_intro" />
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Volumes na régua dos gráficos do Pipedrive · comparação com a mediana do time, tom
          construtivo — a lista do time é editável no Painel Administrativo.
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
      {d && (
        <>
          <SectionCard hint={<Hint area="prevendas/sdrs" titulo="Leads e oportunidades por colaborador" />}
            title="Leads e oportunidades por colaborador"
            subtitle="atribuição pelo campo SDR do deal · leads = criados no período · oportunidades = Dia Oportunidade no período · speed = mediana do 1º contato registrado · lead sem SDR entra em “(sem SDR definido)” · desligados ficam agregados em “(ex-colaboradores)”">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableHead className={th}>Colaborador</TableHead>
                  <TableHead className={`${th} text-right`}>Leads</TableHead>
                  <TableHead className={`${th} text-right`}>Oportunidades</TableHead>
                  <TableHead className={`${th} text-right`}>Lead→Oport</TableHead>
                  <TableHead className={`${th} text-right`}>Bookings</TableHead>
                  <TableHead className={`${th} text-right`}>Speed 1º contato</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.pessoas.map((p) => (
                  <TableRow key={p.nome}>
                    <TableCell className={cn("font-medium", p.sem_sdr && "text-muted-foreground")}>
                      {p.nome}
                      {/* cor SEMPRE com rótulo: o chip diz o papel por extenso */}
                      {p.papel_label && (
                        <Badge variant="outline" className={cn("ml-2 text-[10px]",
                          p.papel === "coordenacao" || p.papel === "gerencia"
                            ? "border-primary/50 text-primary"
                            : "text-muted-foreground")}>
                          {p.papel_label}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(p.leads)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(p.oport)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {p.taxa != null ? formatPct(p.taxa * 100, 1) : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{p.bookings || "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtSpeed(p.speed_min)}</TableCell>
                  </TableRow>
                ))}
                {d.ex_colaboradores && (
                  <TableRow className="text-muted-foreground">
                    <TableCell className="italic">(ex-colaboradores)</TableCell>
                    <TableCell className="text-right tabular-nums">{d.ex_colaboradores.leads || "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{d.ex_colaboradores.oport || "—"}</TableCell>
                    <TableCell />
                    <TableCell className="text-right tabular-nums">{d.ex_colaboradores.book || "—"}</TableCell>
                    <TableCell />
                  </TableRow>
                )}
                <TableRow className="border-t-2 border-border font-semibold">
                  <TableCell>Total</TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(d.total.leads)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(d.total.oport)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {d.total.taxa != null ? formatPct(d.total.taxa * 100, 1) : "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(d.total.book)}</TableCell>
                  <TableCell />
                </TableRow>
              </TableBody>
            </Table>
          </SectionCard>

          {d.desqualificacao.some((x) => x.motivos.length > 0) && (
            <SectionCard hint={<Hint area="prevendas/sdrs" titulo="Motivos de desqualificação por SDR" />}
              title="Motivos de desqualificação por SDR"
              subtitle="perdidos antes do handoff, dentre os leads do período de cada uma — motivo dominante em UMA pessoa = dificuldade específica (roteiro/abordagem); igual em todas = qualidade do lead">
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {d.desqualificacao.map((x) => (
                  <div key={x.nome} className="rounded-xl border border-border p-4">
                    <div className="flex items-baseline justify-between gap-2">
                      <b className="text-sm">{abrev(x.nome)}</b>
                      <span className="text-xs text-muted-foreground">
                        {x.total} desq. · {x.leads ? formatPct((x.total / x.leads) * 100, 1) : "—"} dos leads
                      </span>
                    </div>
                    {x.motivos.length === 0 ? (
                      <p className="mt-2 text-xs text-muted-foreground">sem desqualificações no período</p>
                    ) : x.motivos.map((m) => (
                      <div key={m.motivo} className="mt-2">
                        <div className={cn("flex justify-between gap-2 text-xs",
                          m.sem_motivo ? "text-muted-foreground/70" : "text-foreground/80")}>
                          <span className="truncate" title={m.motivo}>{m.motivo}</span>
                          <span className="shrink-0 tabular-nums">
                            <b>{m.n}</b> · {formatPct(m.pct * 100, 1)}
                          </span>
                        </div>
                        <div className="mt-1 h-1 overflow-hidden rounded bg-muted">
                          <div className="h-full rounded bg-warning" style={{ width: `${m.pct * 100}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </SectionCard>
          )}

          {d.origens.length > 0 && (
            <SectionCard hint={<Hint area="prevendas/sdrs" titulo="Conversão por origem × SDR" />}
              title="Conversão por origem × SDR"
              subtitle="taxa lead→oportunidade (coorte do período; a oportunidade conta a qualquer tempo) · verde = bem acima do time naquela origem, vermelho = bem abaixo — só com 8+ leads, abaixo disso não vira diagnóstico">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/40 hover:bg-muted/40">
                      <TableHead className={th}>Origem</TableHead>
                      <TableHead className={`${th} text-center`}>Time</TableHead>
                      {d.colunas.map((n) => (
                        <TableHead key={n} className={`${th} text-center`} title={n}>{abrev(n)}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.origens.map((o) => (
                      <TableRow key={o.origem}>
                        <TableCell className="max-w-[200px] truncate" title={o.origem}>{o.origem}</TableCell>
                        <TableCell className="text-center tabular-nums">
                          <b>{formatPct(o.taxa_time * 100, 1)}</b>{" "}
                          <span className="text-xs text-muted-foreground">({o.leads})</span>
                        </TableCell>
                        {o.celulas.map((c) => (
                          <TableCell key={c.nome} className="text-center tabular-nums"
                            title={c.n ? `${c.oport} oportunidade(s) de ${c.n} leads` : "sem leads no período"}>
                            {c.n ? (
                              <span className={cn(
                                c.tom === "ok" ? "text-success" : c.tom === "ruim" ? "text-destructive" : "",
                                c.amostra_pequena && "opacity-60",
                              )}>
                                {formatPct((c.taxa ?? 0) * 100, 1)}{" "}
                                <span className="text-xs text-muted-foreground">({c.n})</span>
                              </span>
                            ) : <span className="text-muted-foreground/60">—</span>}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </SectionCard>
          )}

          {d.planos.length > 0 && (
            <SectionCard hint={<Hint area="prevendas/sdrs" titulo="Oportunidades por plano × SDR" />}
              title="Oportunidades por plano × SDR"
              subtitle="oportunidades geradas no período por bundle (% = participação no total da própria SDR) · mix concentrado em B1 numa pessoa com o time mirando B3–B5 = qualificação a puxar para cima">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/40 hover:bg-muted/40">
                      <TableHead className={th}>Plano</TableHead>
                      {d.colunas.map((n) => (
                        <TableHead key={n} className={`${th} text-center`} title={n}>{abrev(n)}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.planos.map((p) => (
                      <TableRow key={p.plano}>
                        <TableCell className="font-medium">{p.plano}</TableCell>
                        {p.celulas.map((c) => (
                          <TableCell key={c.nome} className="text-center tabular-nums">
                            {c.n ? (
                              <>
                                {c.n}{" "}
                                <span className="text-xs text-muted-foreground">
                                  ({((c.pct ?? 0) * 100).toFixed(0)}%)
                                </span>
                              </>
                            ) : <span className="text-muted-foreground/60">—</span>}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </SectionCard>
          )}

          {/* Planos de ação: DETERMINÍSTICOS (comparação com a mediana do
              time em especialista.plano_sdr), não texto de LLM — por isso vêm
              no payload e são renderizados aqui, como no HTML. */}
          {d.acoes_individuais.length > 0 && (
            <SectionCard hint={<Hint area="prevendas/sdrs" titulo="Planos de ação individuais" />}
              title="Planos de ação individuais"
              subtitle={`${d.persona} · derivados dos números da primeira tabela · comparação com a mediana do time`}>
              <div className="space-y-4">
                {d.acoes_individuais.map((x) => (
                  <div key={x.nome} className="rounded-xl border border-border p-4">
                    <div className="flex items-center gap-2">
                      <Users className="h-4 w-4 text-muted-foreground" />
                      <b className="text-sm">{x.nome}</b>
                    </div>
                    <ul className="mt-2 space-y-1 text-sm">
                      {x.fortes.map((f) => (
                        <li key={f} className="text-success">• {f}</li>
                      ))}
                      {x.fracos.map((f) => (
                        <li key={f} className="text-warning">• {f}</li>
                      ))}
                      {x.acoes.map((a2) => (
                        <li key={a2} className="text-muted-foreground">→ {a2}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs text-muted-foreground">
                coordenação: {d.coordenacao} · lista do time editável no Painel Administrativo
              </p>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}
