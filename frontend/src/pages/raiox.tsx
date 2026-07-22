import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { MetaBar } from "@/components/blocks/meta-bar";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatBRL, formatNumber, formatPct } from "@/lib/format";

// Raio-X por Bundle (Lote 5) — /api/raiox EMBRULHA _dados_bundle (que já era
// puro) + a mesma leitura/insights da tela HTML. View de COMPOSIÇÃO: nenhuma
// régua recalculada aqui.

interface Canal { n: number; ativo: number; precoce: number; tardio: number;
  prec: number; cac?: number | null; cac_aj?: number | null }
interface Squad { n: number; alerta: number; exec: number; mrr_risco: number;
  pessoas: number; cp_geral: number | null }
interface Dados {
  b: string; todos: boolean; janela: number; frac: number;
  meta_q: number | null; meta_r: number | null; real_q: number; real_r: number;
  taxa: number | null; won_n: number; dec_n: number; ticket: number | null;
  oports_n: number; coorte_n: number; precoce_pct: number | null; tardio_pct: number | null;
  por_canal: Record<string, Canal>;
  ponte_origens: Array<[string, [number, number]]>;
  tx_sla_ok: number | null; tx_sla_ruim: number | null; n_sla_ok: number | null; n_sla_ruim: number | null;
  canc_total: number; canc_sem_motivo: number;
  canc_meses: Array<[string, number, number]>;
  motivos: Array<[string, number]>;
  squads: Record<string, Squad>;
  alertas_b: number; exec_b: number; mrr_risco_b: number;
  mrr_cnt: number; mrr_soma: number; mrr_est: number | null; mrr_exato: boolean;
  base_contas: number;
  entra_sai: Array<[string, number, number, number, number]>;
  cobertura: { sem_origem: number; canc_casados: number; n_cancs: number };
}
interface Payload {
  bundle: string; rotulo: string; janela: number; bundles: string[]; janelas: number[];
  dados: Dados; fatos: string[];
  leitura: { texto: string; via_llm: boolean; alternativa: string | null; fonte: string };
  areas: Array<{ area: string; href: string; link: string; bullets: string[] }>;
}

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const numCls = "text-right tabular-nums";
const pc = (v: number | null | undefined) => (v == null ? "—" : formatPct(v * 100, 0));
const brl = (v: number | null | undefined) => (v == null ? "—" : formatBRL(v));

export function RaioXPage() {
  const params = new URLSearchParams(window.location.search);
  const [bundle, setBundle] = useState(params.get("b") ?? "TODOS");
  const [janela, setJanela] = useState(params.get("j") ?? "120");
  const q = useApi<Payload>(`/api/raiox?b=${bundle}&j=${janela}`);
  const d = q.data;
  const x = d?.dados;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Raio-X por Bundle<Hint area="raiox" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          A cadeia completa {d?.rotulo ?? ""} na ordem do ciclo: aquisição → fechamento → meta ×
          realizado → retenção → carga operacional → resultado recorrente.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
        <span className="text-xs text-muted-foreground">bundle</span>
        <Select value={bundle} onValueChange={setBundle}>
          <SelectTrigger className="w-[150px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(d?.bundles ?? ["TODOS"]).map((b) => <SelectItem key={b} value={b}>{b}</SelectItem>)}
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">janela de fechamento</span>
        <Select value={janela} onValueChange={setJanela}>
          <SelectTrigger className="w-[130px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(d?.janelas ?? [120]).map((j) => <SelectItem key={j} value={String(j)}>{j} dias</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {q.loading && <LoadingSkeleton rows={6} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && x && (
        <>
          {x.meta_q != null && (
            <SectionCard hint={<Hint area="raiox" titulo="Meta × realizado" />}
              title="Meta × realizado no mês"
              subtitle={`ritmo do mês: ${(x.frac * 100).toFixed(0)}% decorrido — o verde/vermelho compara com esse ritmo`}>
              <div className="grid gap-4 md:grid-cols-2">
                <MetaBar value={x.real_q} target={x.meta_q}
                  valueLabel={`Bookings: ${x.real_q}`}
                  targetLabel={`meta ${x.meta_q.toFixed(0)}`} pacePct={x.frac * 100} />
                <MetaBar value={x.real_r} target={x.meta_r ?? 0}
                  valueLabel={`Receita: ${formatBRL(x.real_r)}`}
                  targetLabel={`meta ${brl(x.meta_r)}`} pacePct={x.frac * 100} />
              </div>
            </SectionCard>
          )}

          <SectionCard hint={<Hint area="raiox" titulo="Leitura do especialista" />}
            title="Leitura do especialista"
            subtitle={`gerada por ${d.leitura.fonte} — hipótese para investigar, não veredito`}>
            <p className="text-sm leading-relaxed">→ {d.leitura.texto}</p>
            {d.leitura.alternativa && (
              <details className="mt-3">
                <summary className="cursor-pointer text-xs font-medium text-primary">
                  ver também a leitura determinística
                </summary>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{d.leitura.alternativa}</p>
              </details>
            )}
            {d.fatos.length > 0 && (
              <details className="mt-3">
                <summary className="cursor-pointer text-xs font-medium text-primary">
                  fatos que alimentam a leitura ({d.fatos.length})
                </summary>
                <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
                  {d.fatos.map((f) => <li key={f}>· {f}</li>)}
                </ul>
              </details>
            )}
          </SectionCard>

          <div className="grid gap-6 xl:grid-cols-2">
            <SectionCard hint={<Hint area="raiox" titulo="Aquisição por canal" />}
              headerClassName="min-h-[72px]" title="Aquisição — canal × retenção"
              subtitle="de onde vem o cliente e quantos saem cedo · CAC aj. = CAC ÷ retenção (o custo real por cliente que FICA)">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className={thCls}>Canal</TableHead>
                      <TableHead className={`${thCls} text-right`}>Clientes</TableHead>
                      <TableHead className={`${thCls} text-right`}>Precoce</TableHead>
                      <TableHead className={`${thCls} text-right`}>CAC</TableHead>
                      <TableHead className={`${thCls} text-right`}>CAC aj.</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {Object.entries(x.por_canal).sort((a, b) => b[1].n - a[1].n).map(([c, v]) => (
                      <TableRow key={c}>
                        <TableCell className="font-medium">{c}</TableCell>
                        <TableCell className={numCls}>{v.n}</TableCell>
                        <TableCell className={`${numCls} ${v.prec >= 0.4 && v.n >= 5 ? "text-destructive" : ""}`}>
                          {pc(v.prec)}{v.n < 5 && <span className="ml-1 text-[10px] text-muted-foreground">(n&lt;5)</span>}
                        </TableCell>
                        <TableCell className={numCls}>{brl(v.cac)}</TableCell>
                        <TableCell className={`${numCls} font-semibold`}>{brl(v.cac_aj)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </SectionCard>

            <SectionCard hint={<Hint area="raiox" titulo="Qualificação e fechamento" />}
              headerClassName="min-h-[72px]" title="Qualificação e fechamento"
              subtitle={`janela de ${x.janela} dias · taxa sobre DECIDIDAS (ganhas + perdidas)`}>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-lg border border-border p-3">
                  <div className="font-display text-xl font-bold tabular-nums">{pc(x.taxa)}</div>
                  <div className="text-xs text-muted-foreground">fechamento ({x.won_n} de {x.dec_n} decididas)</div>
                </div>
                <div className="rounded-lg border border-border p-3">
                  <div className="font-display text-xl font-bold tabular-nums">{brl(x.ticket)}</div>
                  <div className="text-xs text-muted-foreground">ticket médio</div>
                </div>
                <div className="rounded-lg border border-border p-3">
                  <div className="font-display text-xl font-bold tabular-nums">{formatNumber(x.oports_n)}</div>
                  <div className="text-xs text-muted-foreground">oportunidades na janela</div>
                </div>
                <div className="rounded-lg border border-border p-3">
                  <div className="font-display text-xl font-bold tabular-nums">
                    {x.tx_sla_ok != null ? pc(x.tx_sla_ok) : "—"}
                    {x.tx_sla_ruim != null && <span className="text-sm text-muted-foreground"> vs {pc(x.tx_sla_ruim)}</span>}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    fecha em ≤15min vs &gt;1h{x.n_sla_ok != null ? ` (${x.n_sla_ok}×${x.n_sla_ruim})` : ""}
                  </div>
                </div>
              </div>
              {x.ponte_origens.length > 0 && (
                <div className="mt-3">
                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Origens que mais trouxeram oportunidades
                  </div>
                  <ul className="space-y-1 text-sm">
                    {x.ponte_origens.slice(0, 6).map(([o, [won, tot]]) => (
                      <li key={o} className="flex justify-between border-t border-border pt-1 first:border-t-0">
                        <span>{o}</span>
                        <span className="tabular-nums text-muted-foreground">
                          {won}/{tot} · {tot ? formatPct((won / tot) * 100, 0) : "—"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </SectionCard>
          </div>

          <div className="grid gap-6 xl:grid-cols-2">
            <SectionCard hint={<Hint area="raiox" titulo="Retenção" />}
              headerClassName="min-h-[72px]" title="Retenção — quem saiu e por quê"
              subtitle={`${x.canc_total} cancelamento(s) no recorte · precoce = saída em até 3 meses`}>
              <div className="mb-3 flex gap-3">
                <Badge variant="outline" className="border-destructive/50 text-destructive">
                  precoce {pc(x.precoce_pct)}
                </Badge>
                <Badge variant="outline">tardio {pc(x.tardio_pct)}</Badge>
                <Badge variant="outline" className="text-muted-foreground">coorte {x.coorte_n}</Badge>
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Motivo</TableHead>
                    <TableHead className={`${thCls} text-right`}>Saídas</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {x.motivos.slice(0, 8).map(([m, n]) => (
                    <TableRow key={m}>
                      <TableCell className="text-sm">{m}</TableCell>
                      <TableCell className={numCls}>{n}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {x.canc_sem_motivo > 0 && (
                <p className="mt-2 text-xs text-muted-foreground">
                  {x.canc_sem_motivo} saída(s) <b>sem motivo registrado</b> — lacuna de registro, não ausência de causa.
                </p>
              )}
            </SectionCard>

            <SectionCard hint={<Hint area="raiox" titulo="Carga operacional" />}
              headerClassName="min-h-[72px]" title="Carga operacional por squad"
              subtitle={`${x.base_contas} conta(s) no recorte · ${x.alertas_b} com alerta aberto · ${x.exec_b} com execução crítica`}>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className={thCls}>Squad</TableHead>
                      <TableHead className={`${thCls} text-right`}>Contas</TableHead>
                      <TableHead className={`${thCls} text-right`}>Alertas</TableHead>
                      <TableHead className={`${thCls} text-right`}>Exec. crítica</TableHead>
                      <TableHead className={`${thCls} text-right`}>MRR em risco</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {Object.entries(x.squads).map(([s, v]) => (
                      <TableRow key={s}>
                        <TableCell className="font-medium">{s}</TableCell>
                        <TableCell className={numCls}>{v.n}</TableCell>
                        <TableCell className={numCls}>{v.alerta}</TableCell>
                        <TableCell className={numCls}>{v.exec}</TableCell>
                        <TableCell className={numCls}>{formatBRL(v.mrr_risco)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </SectionCard>
          </div>

          <SectionCard hint={<Hint area="raiox" titulo="Resultado recorrente" />}
            title="Resultado recorrente — entra × sai"
            subtitle={x.mrr_exato
              ? `base de MRR: ${formatBRL(x.mrr_soma)} (todas as contas cadastradas)`
              : `base ESTIMADA em ${brl(x.mrr_est)} — só ${x.mrr_cnt} de ${x.base_contas} contas têm MRR cadastrado (média aplicada às demais)`}>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Mês</TableHead>
                    <TableHead className={`${thCls} text-right`}>Entraram</TableHead>
                    <TableHead className={`${thCls} text-right`}>R$ que entrou</TableHead>
                    <TableHead className={`${thCls} text-right`}>Saíram</TableHead>
                    <TableHead className={`${thCls} text-right`}>R$ que saiu</TableHead>
                    <TableHead className={`${thCls} text-right`}>Saldo</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {x.entra_sai.map(([mes, nIn, vIn, nOut, vOut]) => (
                    <TableRow key={mes}>
                      <TableCell className="font-medium">{mes}</TableCell>
                      <TableCell className={numCls}>{nIn}</TableCell>
                      <TableCell className={numCls}>{formatBRL(vIn)}</TableCell>
                      <TableCell className={numCls}>{nOut}</TableCell>
                      <TableCell className={numCls}>{formatBRL(vOut)}</TableCell>
                      <TableCell className={`${numCls} font-semibold ${vIn - vOut >= 0 ? "text-success" : "text-destructive"}`}>
                        {formatBRL(vIn - vOut)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </SectionCard>

          <SectionCard hint={<Hint area="raiox" titulo="O que cada área leva" />}
            title="O que cada área leva deste raio-x"
            subtitle="composição dos números acima, sem recálculo — área sem sinal forte diz isso explicitamente">
            <div className="grid gap-4 md:grid-cols-2">
              {d.areas.map((a) => (
                <div key={a.area} className="rounded-xl border border-border p-4">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <b className="text-sm">{a.area}</b>
                    <a href={a.href} className="text-xs text-primary hover:underline">{a.link} →</a>
                  </div>
                  <ul className="space-y-1.5 text-sm text-muted-foreground">
                    {a.bullets.map((b) => (
                      <li key={b} className="border-t border-border pt-1.5 first:border-t-0 first:pt-0">{b}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </SectionCard>

          <p className="text-xs text-muted-foreground">
            Cobertura do vínculo booking↔cancelamento: {x.cobertura.canc_casados}/{x.cobertura.n_cancs} ·
            {" "}{x.cobertura.sem_origem} booking(s) sem origem atribuída.
          </p>
        </>
      )}
    </div>
  );
}
