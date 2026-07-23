import { AlertTriangle, ChevronRight, ExternalLink, Users } from "lucide-react";
import { Fragment, useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { formatBRL, formatPct } from "@/lib/format";

// Growth · Análise dos Squads (Lote 6) — /api/growth/carga embrulha
// `growth_carga.carga_dados`, extraída das 411 linhas que misturavam cálculo e
// HTML. Três perguntas, nesta ordem:
//   1. onde está o risco por time;
//   2. o time dá conta? (contas/pessoa E tarefas/pessoa — tarefa recorrente faz
//      a carga REAL divergir do tamanho da carteira);
//   3. os atrasos vêm de SOBRECARGA ou de RITMO/processo?

interface ItemAtraso {
  conta: string; tarefa: string | null; url: string | null;
  dias_atraso: number; vence_em: string | null; responsavel: string | null;
}
interface Payload {
  ranking: Array<{ squad: string; sem_squad: boolean; contas: number; mrr: number;
    mrr_risco: number; concentracao: number; concentra_risco: boolean;
    criticos: number; altos: number; atencao: number; exec_critica: number;
    bandas: Record<string, number> }>;
  capacidade: Array<{ squad: string; pessoas: number; contas: number;
    contas_pessoa: number | null; estado: string | null;
    tarefas_abertas: number | null; tarefas_pessoa: number | null;
    tom_tarefas: string | null; mrr_pessoa: number | null;
    graves_pessoa: number | null; pct_saudavel: number | null }>;
  media_contas_pessoa: number | null;
  leitura_capacidade: string;
  tem_tarefas: boolean;
  atrasos_disponiveis: boolean;
  leitura_atrasos: string; total_atrasos: number;
  atrasos_squad: Array<{ squad: string; tarefas: number; contas: number; pior: number;
    pessoas: number | null; contas_pessoa: number | null; tarefas_pessoa: number | null;
    pct_carteira: number | null; diagnostico: string | null; itens: ItemAtraso[] }>;
  atrasos_responsavel: Array<{ responsavel: string; tarefas: number; contas: number;
    pior: number; squads_txt: string[]; itens: ItemAtraso[] }>;
  atrasos_sem_squad: number; atrasos_inativos: number; atrasos_inativos_contas: number;
  atrasos_duplicados: number;
  correlacao_carga_atraso: number | null;
  // já vem ORDENADO por score desc do `_squad_analysis` — o front não reordena
  analise: Array<{ squad: string; n: number; score: number; rel: number; exe: number;
    risco_pct: number; caindo_pct: number; cp: number | null; pessoas: number;
    n_alert: number; exec_atr: number; mrr_risco: number; dor: string | null;
    drivers?: unknown; fortes: string[]; fracos: string[]; acoes: string[] }>;
  sem_squad: number;
}

const th = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";

// lista de tarefas vencidas — cada uma com link direto para o ClickUp
function ListaTarefas({ itens }: { itens: ItemAtraso[] }) {
  return (
    <div className="rounded-lg bg-muted/40 p-3">
      {itens.map((t, i) => (
        <div key={`${t.url ?? t.tarefa}-${i}`}
          className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-border py-1 text-xs last:border-b-0">
          <span className="w-11 shrink-0 text-right font-medium tabular-nums text-destructive">
            {t.dias_atraso} d
          </span>
          <span className="min-w-[220px] flex-1">
            {t.url ? (
              <a href={t.url} target="_blank" rel="noopener"
                className="underline decoration-dotted hover:text-primary" title="abrir a tarefa no ClickUp">
                {t.tarefa ?? "?"} <ExternalLink className="inline h-3 w-3" />
              </a>
            ) : (t.tarefa ?? "?")}
            <span className="text-muted-foreground"> — {t.conta}</span>
          </span>
          <span className="text-muted-foreground">{t.responsavel ?? "sem responsável"}</span>
          <span className="whitespace-nowrap text-muted-foreground/70">
            venceu {t.vence_em ? `${t.vence_em.slice(8, 10)}/${t.vence_em.slice(5, 7)}` : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}

export function GrowthSquadsPage() {
  const q = useApi<Payload>("/api/growth/carga");
  const d = q.data;
  const [aberto, setAberto] = useState<Set<string>>(new Set());
  const alterna = (k: string) => setAberto((s) => {
    const n = new Set(s);
    n.has(k) ? n.delete(k) : n.add(k);
    return n;
  });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">
          Análise dos Squads
          <Hint area="growth/carga" titulo="_intro" />
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Tudo do time num lugar só: score e plano de ação, carga de risco, capacidade de atendimento
          e atividades em atraso.
        </p>
      </header>

      {q.loading && <LoadingSkeleton rows={6} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && (
        <>
          {/* RANKING NO TOPO (Otávio 23/07): é a leitura de entrada da tela —
              quem está bem, quem está mal e o que fazer. O score composto e a
              POSIÇÃO tinham sumido no port; a ordem vem do backend
              (`_squad_analysis`, já ordenado por score desc). */}
          {d.analise.length > 0 && (
            <SectionCard hint={<Hint area="growth/carga" titulo="Ranking e análise" />}
              title="Ranking e análise por squad"
              subtitle="score composto: 50% relacionamento · 25% execução · 25% risco — dores dominantes e plano de ação por equipe; fortes e fracos já consideram carga e concentração de risco">
              <div className="grid gap-3 lg:grid-cols-2">
                {d.analise.map((a, i) => (
                  <div key={a.squad} className="rounded-xl border border-border p-4">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <b className="font-display text-sm">
                        <span className="mr-1.5 text-muted-foreground">{i + 1}º</span>
                        {a.squad}
                      </b>
                      <span className="flex items-baseline gap-2">
                        <span className={cn("font-display text-xl font-bold tabular-nums",
                          a.score >= 65 ? "text-success"
                            : a.score >= 55 ? "text-warning" : "text-destructive")}>
                          {a.score.toFixed(1)}
                        </span>
                        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                          score
                        </span>
                      </span>
                    </div>
                    {/* as 3 partes do score, para o número não ser uma caixa-preta */}
                    <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                      <div>
                        <div className="tabular-nums font-semibold">{a.rel.toFixed(0)}</div>
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                          relacion. 50%
                        </div>
                      </div>
                      <div>
                        <div className="tabular-nums font-semibold">{a.exe.toFixed(0)}</div>
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                          execução 25%
                        </div>
                      </div>
                      <div>
                        <div className="tabular-nums font-semibold">
                          {formatPct(a.risco_pct * 100)}
                        </div>
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                          em risco 25%
                        </div>
                      </div>
                    </div>
                    <div className="mt-2 text-xs text-muted-foreground">
                      {a.n} contas
                      {a.pessoas ? ` · ${a.pessoas} pessoa(s)` : ""}
                      {a.cp != null ? ` · ${a.cp.toFixed(1)} contas/pessoa` : ""}
                      {a.n_alert ? ` · ${a.n_alert} alerta(s)` : ""}
                      {a.dor ? ` · dor dominante: ${a.dor}` : ""}
                    </div>
                    <ul className="mt-2 space-y-1 text-sm">
                      {a.fortes.map((f) => <li key={f} className="text-success">• {f}</li>)}
                      {a.fracos.map((f) => <li key={f} className="text-warning">• {f}</li>)}
                      {a.acoes.map((x) => <li key={x} className="text-muted-foreground">→ {x}</li>)}
                    </ul>
                  </div>
                ))}
              </div>
              {!!d.sem_squad && (
                <p className="mt-3 flex items-start gap-1.5 text-xs text-muted-foreground">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  {d.sem_squad} conta(s) sem squad identificado na planilha ficaram fora desta análise.
                </p>
              )}
            </SectionCard>
          )}

          <SectionCard hint={<Hint area="growth/carga" titulo="Carga de risco por squad" />}
            title="Carga de risco por squad"
            subtitle="onde há carga desproporcional de contas críticas e MRR em risco — decidir realocação/reforço ANTES de a sobrecarga virar churn · o selo marca concentração (3+ críticos ou 30%+ do MRR em risco)">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <TableHead className={th}>Squad</TableHead>
                    <TableHead className={`${th} text-right`}>Contas</TableHead>
                    <TableHead className={`${th} text-right`}>MRR</TableHead>
                    <TableHead className={`${th} text-right`}>Crít.</TableHead>
                    <TableHead className={`${th} text-right`}>Alto</TableHead>
                    <TableHead className={`${th} text-right`}>Aten.</TableHead>
                    <TableHead className={`${th} text-right`}>MRR em risco</TableHead>
                    <TableHead className={`${th} text-right`}>Exec. crítica</TableHead>
                    <TableHead className={`${th} text-center`}>Faixas</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.ranking.map((r) => (
                    <TableRow key={r.squad} className={cn(r.sem_squad && "text-muted-foreground")}>
                      <TableCell className="font-medium">
                        {r.squad}
                        {r.concentra_risco && (
                          <Badge className="ml-2 border-0 bg-destructive/15 text-[10px] text-destructive">
                            concentração de risco
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{r.contas}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatBRL(r.mrr)}</TableCell>
                      <TableCell className="text-right tabular-nums text-destructive">
                        {r.criticos || ""}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{r.altos || ""}</TableCell>
                      <TableCell className="text-right tabular-nums">{r.atencao || ""}</TableCell>
                      <TableCell className="whitespace-nowrap text-right tabular-nums">
                        {formatBRL(r.mrr_risco)}{" "}
                        <span className="text-xs text-muted-foreground">
                          ({(r.concentracao * 100).toFixed(0)}%)
                        </span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{r.exec_critica || ""}</TableCell>
                      <TableCell className="whitespace-nowrap text-center text-xs tabular-nums">
                        {/* cor + número: cada faixa continua legível sem depender só da cor */}
                        <span className="text-success">{r.bandas.baixo}</span>{" · "}
                        <span className="text-warning">{r.bandas.medio}</span>{" · "}
                        <span className="text-warning">{r.bandas.alto}</span>{" · "}
                        <span className="text-destructive">{r.bandas.critico}</span>
                        {!!r.bandas.sem && (
                          <span className="text-muted-foreground"> · {r.bandas.sem} s/d</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </SectionCard>

          <SectionCard hint={<Hint area="growth/carga" titulo="Capacidade de atendimento" />}
            title="Capacidade de atendimento"
            subtitle="carteira E carga de trabalho ÷ tamanho do time — contas/pessoa mede a carteira; tarefas abertas/pessoa mede o trabalho REAL no ClickUp, e tarefas recorrentes fazem os dois divergirem">
            <p className="mb-3 rounded-lg bg-muted/40 p-3 text-sm leading-relaxed">
              → {d.leitura_capacidade}
            </p>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <TableHead className={th}>Squad</TableHead>
                    <TableHead className={`${th} text-right`}>Pessoas</TableHead>
                    <TableHead className={`${th} text-right`}>Contas</TableHead>
                    <TableHead className={`${th} text-right`}>Contas/pessoa</TableHead>
                    <TableHead className={`${th} text-right`}>Tarefas abertas</TableHead>
                    <TableHead className={`${th} text-right`}>Tarefas/pessoa</TableHead>
                    <TableHead className={`${th} text-right`}>MRR/pessoa</TableHead>
                    <TableHead className={`${th} text-right`}>Graves/pessoa</TableHead>
                    <TableHead className={`${th} text-right`}>% saudável</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.capacidade.map((c) => (
                    <TableRow key={c.squad}>
                      <TableCell className="font-medium">
                        {c.squad}
                        {c.estado === "sobrecarga" && (
                          <Badge className="ml-2 border-0 bg-destructive/15 text-[10px] text-destructive">
                            sobrecarga
                          </Badge>
                        )}
                        {c.estado === "folga" && (
                          <Badge className="ml-2 border-0 bg-success/15 text-[10px] text-success">
                            folga
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{c.pessoas || "—"}</TableCell>
                      <TableCell className="text-right tabular-nums">{c.contas}</TableCell>
                      <TableCell className="text-right font-semibold tabular-nums">
                        {c.contas_pessoa != null ? c.contas_pessoa.toFixed(1) : "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {d.tem_tarefas ? c.tarefas_abertas : "—"}
                      </TableCell>
                      <TableCell className={cn("text-right tabular-nums",
                        c.tom_tarefas === "critico" ? "font-bold text-destructive"
                          : c.tom_tarefas === "ok" ? "text-success" : "")}>
                        {d.tem_tarefas && c.tarefas_pessoa != null ? c.tarefas_pessoa.toFixed(0) : "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{formatBRL(c.mrr_pessoa)}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {c.graves_pessoa != null ? c.graves_pessoa.toFixed(1) : "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {c.pct_saudavel != null ? formatPct(c.pct_saudavel * 100) : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </SectionCard>

          <SectionCard hint={<Hint area="growth/carga" titulo="Atividades em atraso" />}
            title="Atividades em atraso"
            subtitle="tarefas ABERTAS com vencimento estourado no ClickUp (as mesmas da coluna “Atrasos” da aba Contas) · clientes pausados por inadimplência ou concluídos ficam fora · clique num squad ou responsável para abrir as tarefas">
            <p className="mb-3 rounded-lg bg-muted/40 p-3 text-sm leading-relaxed">
              → {d.leitura_atrasos}
            </p>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <TableHead className={th}>Squad</TableHead>
                    <TableHead className={`${th} text-right`}>Tarefas atrasadas</TableHead>
                    <TableHead className={`${th} text-right`}>Contas com atraso</TableHead>
                    <TableHead className={`${th} text-right`}>% da carteira</TableHead>
                    <TableHead className={`${th} text-right`}>Atrasos/pessoa</TableHead>
                    <TableHead className={`${th} text-right`}>Contas/pessoa</TableHead>
                    <TableHead className={`${th} text-right`}>Maior atraso</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {/* Fragment COM key: `<>` sem key gera warning e re-render
                      instável das linhas (gotcha já visto no Heatmap) */}
                  {d.atrasos_squad.map((a) => (
                    <Fragment key={a.squad}>
                      <TableRow className={cn(a.tarefas > 0 && "cursor-pointer")}
                        onClick={() => a.tarefas > 0 && alterna(`sq-${a.squad}`)}>
                        <TableCell className="font-medium">
                          {a.tarefas > 0 && (
                            <ChevronRight className={cn("mr-1 inline h-3.5 w-3.5 text-primary transition-transform",
                              aberto.has(`sq-${a.squad}`) && "rotate-90")} />
                          )}
                          {a.squad}
                          {/* o DIAGNÓSTICO é a resposta da seção: sobrecarga × ritmo */}
                          {a.diagnostico === "capacidade" && (
                            <Badge className="ml-2 border-0 bg-warning/15 text-[10px] text-warning"
                              title="atrasos altos E carga alta: o atraso é coerente com sobrecarga — redistribuir contas ou reforçar o time">
                              capacidade
                            </Badge>
                          )}
                          {a.diagnostico === "ritmo" && (
                            <Badge className="ml-2 border-0 bg-destructive/15 text-[10px] text-destructive"
                              title="atrasos altos SEM carga acima da média: o gargalo não é falta de gente — revisar rotina, priorização e disciplina de prazo">
                              ritmo/processo
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-right font-bold tabular-nums text-destructive">
                          {a.tarefas || ""}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{a.contas || ""}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          {a.pct_carteira != null ? `${(a.pct_carteira * 100).toFixed(0)}%` : "—"}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {a.tarefas_pessoa != null ? a.tarefas_pessoa.toFixed(1) : "—"}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {a.contas_pessoa != null ? a.contas_pessoa.toFixed(1) : "—"}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{a.pior || ""}</TableCell>
                      </TableRow>
                      {aberto.has(`sq-${a.squad}`) && (
                        <TableRow>
                          <TableCell colSpan={7} className="p-2"><ListaTarefas itens={a.itens} /></TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  ))}
                </TableBody>
              </Table>
            </div>

            {/* ressalvas do que FICOU DE FORA da conta — ao lado do número */}
            <div className="mt-3 space-y-1 text-xs text-muted-foreground">
              {!!d.atrasos_sem_squad && (
                <p>{d.atrasos_sem_squad} tarefa(s) atrasada(s) em contas sem squad identificado ficaram
                  fora da tabela.</p>
              )}
              {!!d.atrasos_inativos && (
                <p>{d.atrasos_inativos} tarefa(s) vencida(s) de {d.atrasos_inativos_contas} cliente(s){" "}
                  <b>pausado(s) por inadimplência ou concluído(s)</b> no ClickUp ficaram fora das
                  contagens — serviço suspenso não é cobrança do squad. Voltam a contar se o cliente
                  reativar.</p>
              )}
              {!!d.atrasos_duplicados && (
                <p>{d.atrasos_duplicados} tarefa(s) apareciam em <b>mais de uma conta do mesmo
                  cliente</b> (ex.: conta do bundle + conta ADS) e foram contadas UMA vez, na conta
                  principal — se o cliente tem grupos duplicados no painel, vale unificar.</p>
              )}
            </div>

            <div className="mt-5">
              <div className="mb-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                por responsável (assignee das tarefas vencidas no ClickUp)
              </div>
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <TableHead className={th}>Responsável</TableHead>
                    <TableHead className={`${th} text-right`}>Tarefas atrasadas</TableHead>
                    <TableHead className={`${th} text-right`}>Contas</TableHead>
                    <TableHead className={th}>Squad(s)</TableHead>
                    <TableHead className={`${th} text-right`}>Maior atraso</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.atrasos_responsavel.slice(0, 15).map((r) => (
                    <Fragment key={r.responsavel}>
                      <TableRow className="cursor-pointer"
                        onClick={() => alterna(`rp-${r.responsavel}`)}>
                        <TableCell className="font-medium">
                          <ChevronRight className={cn("mr-1 inline h-3.5 w-3.5 text-primary transition-transform",
                            aberto.has(`rp-${r.responsavel}`) && "rotate-90")} />
                          {r.responsavel}
                        </TableCell>
                        <TableCell className="text-right font-bold tabular-nums text-destructive">
                          {r.tarefas}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{r.contas}</TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {r.squads_txt.join(", ") || "—"}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{r.pior}</TableCell>
                      </TableRow>
                      {aberto.has(`rp-${r.responsavel}`) && (
                        <TableRow>
                          <TableCell colSpan={5} className="p-2"><ListaTarefas itens={r.itens} /></TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  ))}
                </TableBody>
              </Table>
              {d.atrasos_responsavel.length > 15 && (
                <p className="mt-2 text-xs text-muted-foreground">
                  + {d.atrasos_responsavel.length - 15} responsável(is) com menos atrasos fora do top 15.
                </p>
              )}
            </div>
          </SectionCard>

        </>
      )}
    </div>
  );
}
