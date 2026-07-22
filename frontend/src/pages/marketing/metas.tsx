import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatBRL, formatNumber, formatPct } from "@/lib/format";

// Marketing · Metas do Semestre (Lote 4) — /api/marketing/metas embrulha o
// compute da tela HTML (plan_funnel + funil oficial + gasto). Paridade checada.

interface Payload {
  ano: number; sem_plano: boolean; mes_atual: string; ritmo_pct: number;
  kpis: Array<{ label: string; real: number; meta: number; kind: string; pct: number | null; inverso: boolean }>;
  meses: string[];
  grade: Array<{ mes: string; atual: boolean;
    cels: Array<{ etapa: string; real: number | null; meta: number | null; pct: number | null; ritmo_pct: number | null }> }>;
  h2: { real: number; meta: number };
  custos: Array<{ etapa: string; volume: number; alvo: number; real: number | null; var_pct: number | null }>;
  investimento: Array<{ mes: string; meta_leads: number | null; investimento: number | null;
    verba: number | null; gasto: number | null; cobertura_pct: number | null }>;
  canais: Array<{ canal: string; total: boolean; real_mes: number | null; no_ritmo: boolean | null;
    meses: Array<{ mes: string; meta: number | null; verba: number | null }> }>;
}

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const numCls = "text-right tabular-nums";
const fmt = (v: number | null, kind = "num") =>
  v == null ? "—" : kind === "brl" ? formatBRL(v) : formatNumber(Math.round(v));

export function MktMetasPage() {
  const q = useApi<Payload>("/api/marketing/metas");
  const d = q.data;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Metas do Semestre<Hint area="marketing/metas" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Plano mensal da planilha de metas do Marketing (jul-dez {d?.ano ?? ""}) × realizado — releitura semanal.
        </p>
      </header>
      {q.loading && <LoadingSkeleton rows={6} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && d.sem_plano && (
        <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
          Plano ainda não importado — rode o sync semanal da planilha de metas.
        </p>
      )}
      {d && !d.sem_plano && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
            {d.kpis.map((k) => {
              const ok = k.pct != null && (k.inverso ? k.pct <= 100 : k.pct >= d.ritmo_pct);
              return (
                <div key={k.label} className="rounded-xl border border-border bg-card p-4">
                  <div className="font-display text-xl font-bold tabular-nums">{fmt(k.real, k.kind)}</div>
                  <div className="text-xs text-muted-foreground">{k.label}</div>
                  <div className={`mt-1 text-xs font-medium ${ok ? "text-success" : "text-destructive"}`}>
                    {k.pct != null ? formatPct(k.pct, 0) : "—"} ({k.inverso ? "alvo" : "meta"}: {fmt(k.meta, k.kind)})
                  </div>
                </div>
              );
            })}
          </div>
          <p className="text-xs text-muted-foreground">
            ritmo esperado: {d.ritmo_pct.toFixed(0)}% do mês decorrido — verde = no ritmo da meta
            (custos: verde = dentro do alvo/verba).
          </p>

          <SectionCard hint={<Hint area="marketing/metas" titulo="Funil mês a mês" />}
            title="Funil mês a mês — realizado/meta"
            subtitle="realizado = coorte de deals criados no mês (mesma régua da aba Funil) · verde = no ritmo · vermelho = abaixo de 75% do ritmo">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Mês</TableHead>
                    {d.grade[0]?.cels.map((c) => <TableHead key={c.etapa} className={`${thCls} text-right`}>{c.etapa}</TableHead>)}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.grade.map((g) => (
                    <TableRow key={g.mes} className={g.atual ? "bg-primary/5" : undefined}>
                      <TableCell className="font-medium">{g.mes}</TableCell>
                      {g.cels.map((c) => (
                        <TableCell key={c.etapa} className={numCls}>
                          {c.real == null ? (
                            <span className="text-muted-foreground">{fmt(c.meta)}</span>
                          ) : c.meta == null ? c.real : (
                            <>
                              <b>{c.real}</b><span className="text-muted-foreground">/{c.meta.toFixed(0)}</span>{" "}
                              <span className={`text-[10px] ${(c.pct ?? 0) >= (c.ritmo_pct ?? 0) ? "text-success" : (c.pct ?? 0) < (c.ritmo_pct ?? 0) * 0.75 ? "text-destructive" : "text-muted-foreground"}`}>
                                {c.pct != null ? formatPct(c.pct, 0) : ""}
                              </span>
                            </>
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                  <TableRow>
                    <TableCell className="font-semibold">H2</TableCell>
                    <TableCell colSpan={(d.grade[0]?.cels.length ?? 1) - 1} />
                    <TableCell className={`${numCls} font-semibold`}>
                      {d.h2.real}<span className="font-normal text-muted-foreground">/{d.h2.meta.toFixed(0)}</span>
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>
          </SectionCard>

          {d.custos.length > 0 && (
            <SectionCard hint={<Hint area="marketing/metas" titulo="Custo por etapa vs alvo" />}
              title="Custo por etapa vs alvo (mês corrente)"
              subtitle="custo real = gasto de mídia ÷ volume da etapa (proxy: inclui canais não pagos) · alvo da planilha">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Etapa</TableHead>
                    <TableHead className={`${thCls} text-right`}>Volume</TableHead>
                    <TableHead className={`${thCls} text-right`}>Custo-alvo</TableHead>
                    <TableHead className={`${thCls} text-right`}>Custo real</TableHead>
                    <TableHead className={`${thCls} text-right`}>Δ</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.custos.map((c) => (
                    <TableRow key={c.etapa}>
                      <TableCell className="font-medium">{c.etapa}</TableCell>
                      <TableCell className={numCls}>{c.volume}</TableCell>
                      <TableCell className={numCls}>{formatBRL(c.alvo)}</TableCell>
                      <TableCell className={numCls}>{c.real != null ? formatBRL(c.real) : "—"}</TableCell>
                      <TableCell className={`${numCls} font-medium ${(c.var_pct ?? 0) > 0 ? "text-destructive" : "text-success"}`}>
                        {c.var_pct != null ? `${c.var_pct >= 0 ? "+" : ""}${c.var_pct.toFixed(0)}%` : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </SectionCard>
          )}

          <SectionCard hint={<Hint area="marketing/metas" titulo="Investimento planejado × gasto" />}
            title="Investimento planejado × gasto"
            subtitle="investimento necessário = meta de leads × CPL-alvo · verba mídia = orçamento do mês · gasto = Meta+Google">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Mês</TableHead>
                    <TableHead className={`${thCls} text-right`}>Meta leads</TableHead>
                    <TableHead className={`${thCls} text-right`}>Investimento necessário</TableHead>
                    <TableHead className={`${thCls} text-right`}>Verba mídia</TableHead>
                    <TableHead className={`${thCls} text-right`}>Gasto real</TableHead>
                    <TableHead className={`${thCls} text-right`}>Gasto ÷ necessário</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.investimento.map((i) => (
                    <TableRow key={i.mes}>
                      <TableCell className="font-medium">{i.mes}</TableCell>
                      <TableCell className={numCls}>{fmt(i.meta_leads)}</TableCell>
                      <TableCell className={numCls}>{i.investimento != null ? formatBRL(i.investimento) : "—"}</TableCell>
                      <TableCell className={numCls}>{i.verba != null ? formatBRL(i.verba) : "—"}</TableCell>
                      <TableCell className={numCls}>{i.gasto != null ? formatBRL(i.gasto) : "—"}</TableCell>
                      <TableCell className={numCls}>{i.cobertura_pct != null ? formatPct(i.cobertura_pct, 0) : "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </SectionCard>

          <SectionCard hint={<Hint area="marketing/metas" titulo="Oportunidades por canal" />}
            title="Oportunidades por canal — metas do semestre"
            subtitle={`metas da planilha · Real ${d.mes_atual} = oportunidades do mês por utm_source (mapeamento aproximado; origens não rastreadas ficam fora)`}>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Canal</TableHead>
                    {d.meses.map((m) => <TableHead key={m} className={`${thCls} text-right`}>{m}</TableHead>)}
                    <TableHead className={`${thCls} text-right`}>Real {d.mes_atual}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.canais.map((c) => (
                    <TableRow key={c.canal} className={c.total ? "border-t-2" : undefined}>
                      <TableCell className="font-medium">{c.canal}</TableCell>
                      {c.meses.map((m) => (
                        <TableCell key={m.mes} className={numCls}
                          title={m.verba != null ? `verba: ${formatBRL(m.verba)}` : undefined}>
                          {fmt(m.meta)}
                        </TableCell>
                      ))}
                      <TableCell className={`${numCls} font-medium ${c.no_ritmo == null ? "" : c.no_ritmo ? "text-success" : "text-destructive"}`}>
                        {c.real_mes ?? "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}
