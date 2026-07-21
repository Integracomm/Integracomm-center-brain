import { useMemo, useState } from "react";
import {
  AlertOctagon, ArrowDown, ArrowUp, ArrowUpDown, DollarSign, ExternalLink,
  EyeOff, Search, Users,
} from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { LoadingSkeleton, ErrorState, EmptyState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { Caveat, CaveatChip } from "@/components/caveat";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Pagination, PaginationContent, PaginationItem, PaginationLink,
  PaginationNext, PaginationPrevious,
} from "@/components/ui/pagination";
import { formatBRL } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  AtrasosBadge, ExecBadge, RiskBadge, SeverityBadge, TrajectoryIcon, stageLabels,
} from "@/components/growth-badges";
import type { RiskBand, Score, ScoresEnvelope, Severity, Stage } from "@/types/api";

// Growth · Contas — porte da referência do protótipo (composição aprovada).
// KPIs vêm do payload (/api/scores kpis) — o frontend NÃO recalcula nada;
// filtra/ordena/pagina a lista recebida (regra do redesenho).

type SortKey = "name" | "score" | "mrr" | "stage" | "risk";
type SortDir = "asc" | "desc";

function SortHead({ label, k, sort, onSort, align = "left" }: {
  label: string; k: SortKey; sort: { key: SortKey; dir: SortDir };
  onSort: (k: SortKey) => void; align?: "left" | "right";
}) {
  const active = sort.key === k;
  const Icon = !active ? ArrowUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <TableHead className={align === "right" ? "text-right" : ""}>
      <button type="button" onClick={() => onSort(k)}
        className={cn("inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wide hover:text-foreground",
          active ? "text-foreground" : "text-muted-foreground")}>
        {label} <Icon className="h-3 w-3" />
      </button>
    </TableHead>
  );
}

export function GrowthContasPage() {
  const q = useApi<ScoresEnvelope>("/api/scores");

  const [search, setSearch] = useState("");
  const [risco, setRisco] = useState<"todos" | RiskBand>("todos");
  const [alerta, setAlerta] = useState<"todos" | "com" | "sem" | Severity>("todos");
  const [squad, setSquad] = useState("todos");
  const [plano, setPlano] = useState("todos");   // bundle B1..B5 pela tag do nome
  const [execf, setExecf] = useState<"todos" | "em_dia" | "atencao" | "critica" | "atrasos">("todos");
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "score", dir: "asc" });
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Score | null>(null);
  const PAGE_SIZE = 25;

  const scores = q.data?.scores ?? [];

  const bundleDe = (nome: string) => nome.match(/B[1-5]/)?.[0] ?? "outros";
  const squads = useMemo(
    () => Array.from(new Set(scores.map((s) => s.squad).filter(Boolean))).sort() as string[],
    [scores]);

  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    return scores.filter((sc) => {
      if (s && !sc.name.toLowerCase().includes(s)) return false;
      if (risco !== "todos" && sc.risk_band !== risco) return false;
      if (alerta === "com" && !sc.alert_sev) return false;
      if (alerta === "sem" && sc.alert_sev) return false;
      if (["critico", "alto", "atencao"].includes(alerta) && sc.alert_sev !== alerta) return false;
      if (squad !== "todos" && sc.squad !== squad) return false;
      if (plano !== "todos" && bundleDe(sc.name) !== plano) return false;
      if (execf === "atrasos" && !(sc.atrasadas ?? 0)) return false;
      if (execf === "em_dia" && !(sc.exec_score != null && sc.exec_score >= 70)) return false;
      if (execf === "atencao" && !(sc.exec_score != null && sc.exec_score >= 40 && sc.exec_score < 70)) return false;
      if (execf === "critica" && !(sc.exec_score != null && sc.exec_score < 40)) return false;
      return true;
    });
  }, [scores, search, risco, alerta, squad, plano, execf]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    const dir = sort.dir === "asc" ? 1 : -1;
    const riskOrder: Record<RiskBand, number> = { alto: 0, medio: 1, baixo: 2, sem_dados: 3 };
    const stageOrder: Record<Stage, number> = {
      intencao_de_saida: 0, insatisfacao_ativa: 1, desengajamento_inicial: 2,
      insatisfacao_latente: 3, saudavel: 4,
    };
    arr.sort((a, b) => {
      switch (sort.key) {
        case "name": return a.name.localeCompare(b.name, "pt-BR") * dir;
        case "score": return (a.score - b.score) * dir;
        case "mrr": return ((a.recurring_revenue ?? -1) - (b.recurring_revenue ?? -1)) * dir;
        case "risk": return (riskOrder[a.risk_band] - riskOrder[b.risk_band]) * dir;
        case "stage": return (stageOrder[a.stage] - stageOrder[b.stage]) * dir;
      }
    });
    return arr;
  }, [filtered, sort]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pageRows = sorted.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  const onSort = (k: SortKey) => {
    setSort((s) => (s.key === k ? { key: k, dir: s.dir === "asc" ? "desc" : "asc" }
      : { key: k, dir: k === "name" ? "asc" : "desc" }));
    setPage(1);
  };

  const kpis = q.data?.kpis;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-2xl font-bold tracking-tight">Contas</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Todas as contas monitoradas com score de risco, alerta e MRR em jogo.
        </p>
      </header>

      {q.loading && <LoadingSkeleton rows={6} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {q.data && kpis && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <KpiCard icon={Users} tone="primary" title="Monitoradas"
              value={kpis.monitoradas.toLocaleString("pt-BR")}
              subtitle={`${kpis.avaliaveis.toLocaleString("pt-BR")} avaliáveis`} />
            <KpiCard icon={AlertOctagon} tone="destructive" title="Em risco crítico"
              value={kpis.criticos.toLocaleString("pt-BR")} subtitle="alertas críticos abertos" />
            <KpiCard icon={DollarSign} tone="warning" title="MRR em risco"
              value={formatBRL(kpis.mrr_em_risco, { compact: true })}
              subtitle={`${kpis.mrr_em_risco_contas} contas · ${kpis.mrr_em_risco_sem_dados} sem MRR`}
              caveat={kpis.mrr_em_risco_sem_dados > 0
                ? `${kpis.mrr_em_risco_sem_dados} contas em risco não têm MRR cadastrado — o valor real é maior.`
                : undefined} />
            <KpiCard icon={EyeOff} tone="muted" title="Sem cobertura"
              value={kpis.sem_cobertura.toLocaleString("pt-BR")} subtitle="sem dados / não avaliáveis" />
          </div>

          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
            <div className="relative min-w-[220px] flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                placeholder="Buscar por nome da conta…" className="pl-9" />
            </div>
            <Select value={risco} onValueChange={(v) => { setRisco(v as typeof risco); setPage(1); }}>
              <SelectTrigger className="w-[180px]"><SelectValue placeholder="Faixa de risco" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="todos">Todas as faixas</SelectItem>
                <SelectItem value="alto">Alto risco</SelectItem>
                <SelectItem value="medio">Médio risco</SelectItem>
                <SelectItem value="baixo">Baixo risco</SelectItem>
                <SelectItem value="sem_dados">Sem dados</SelectItem>
              </SelectContent>
            </Select>
            <Select value={alerta} onValueChange={(v) => { setAlerta(v as typeof alerta); setPage(1); }}>
              <SelectTrigger className="w-[180px]"><SelectValue placeholder="Alerta" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="todos">Todos</SelectItem>
                <SelectItem value="com">Com alerta</SelectItem>
                <SelectItem value="sem">Sem alerta</SelectItem>
                <SelectItem value="critico">Crítico</SelectItem>
                <SelectItem value="alto">Alto</SelectItem>
                <SelectItem value="atencao">Atenção</SelectItem>
              </SelectContent>
            </Select>
            <Select value={squad} onValueChange={(v) => { setSquad(v); setPage(1); }}>
              <SelectTrigger className="w-[150px]"><SelectValue placeholder="Squad" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="todos">Todos os squads</SelectItem>
                {squads.map((sq) => <SelectItem key={sq} value={sq}>{sq}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={plano} onValueChange={(v) => { setPlano(v); setPage(1); }}>
              <SelectTrigger className="w-[140px]"><SelectValue placeholder="Plano" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="todos">Todos os planos</SelectItem>
                {["B1", "B2", "B3", "B4", "B5"].map((b) => <SelectItem key={b} value={b}>{b}</SelectItem>)}
                <SelectItem value="outros">antigos/ADS</SelectItem>
              </SelectContent>
            </Select>
            <Select value={execf} onValueChange={(v) => { setExecf(v as typeof execf); setPage(1); }}>
              <SelectTrigger className="w-[190px]"><SelectValue placeholder="Execução" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="todos">Execução: todas</SelectItem>
                <SelectItem value="em_dia">Em dia (70 ou mais)</SelectItem>
                <SelectItem value="atencao">Atenção (40 a 69)</SelectItem>
                <SelectItem value="critica">Crítica (abaixo de 40)</SelectItem>
                <SelectItem value="atrasos">Com entregas atrasadas</SelectItem>
              </SelectContent>
            </Select>
            <div className="ml-auto text-xs text-muted-foreground">
              <strong className="tabular-nums text-foreground">{sorted.length}</strong> de{" "}
              <span className="tabular-nums">{scores.length}</span> contas
            </div>
          </div>

          {sorted.length === 0 ? (
            <EmptyState title="Nenhuma conta encontrada" description="Ajuste os filtros para ver resultados." />
          ) : (
            <div className="overflow-hidden rounded-xl border border-border bg-card">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <SortHead label="Conta" k="name" sort={sort} onSort={onSort} />
                    <SortHead label="Score" k="score" sort={sort} onSort={onSort} />
                    <SortHead label="Faixa" k="risk" sort={sort} onSort={onSort} />
                    <SortHead label="Estágio" k="stage" sort={sort} onSort={onSort} />
                    <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Alerta</TableHead>
                    <SortHead label="MRR" k="mrr" sort={sort} onSort={onSort} align="right" />
                    <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Execução</TableHead>
                    <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Atrasos</TableHead>
                    <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Squad</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pageRows.map((s) => (
                    <TableRow key={s.id} className="cursor-pointer" onClick={() => setSelected(s)}>
                      <TableCell className="max-w-[320px]">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className="truncate font-medium">{s.name}</span>
                          {!s.evaluable && (
                            <Caveat text="Conta ainda não é avaliável (sem cobertura suficiente)." tone="warning" />
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <span className="font-display font-semibold tabular-nums">{s.score.toFixed(1)}</span>
                          <TrajectoryIcon t={s.trajectory} />
                        </div>
                      </TableCell>
                      <TableCell><RiskBadge band={s.risk_band} /></TableCell>
                      <TableCell className="text-sm">{stageLabels[s.stage]}</TableCell>
                      <TableCell><SeverityBadge sev={s.alert_sev} /></TableCell>
                      <TableCell className="text-right tabular-nums">
                        {s.recurring_revenue != null ? formatBRL(s.recurring_revenue) : (
                          <span className="inline-flex items-center gap-1 text-muted-foreground">
                            — <Caveat text="MRR não cadastrado para esta conta." />
                          </span>
                        )}
                      </TableCell>
                      <TableCell><ExecBadge score={s.exec_score} inativo={s.clickup_inativo} /></TableCell>
                      <TableCell><AtrasosBadge n={s.atrasadas} execScore={s.exec_score} inativo={s.clickup_inativo} /></TableCell>
                      <TableCell><span className="text-xs text-muted-foreground">{s.squad ?? "—"}</span></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {totalPages > 1 && (
                <div className="flex items-center justify-between border-t border-border p-3">
                  <div className="text-xs text-muted-foreground">
                    Página <span className="tabular-nums">{currentPage}</span> de{" "}
                    <span className="tabular-nums">{totalPages}</span>
                  </div>
                  <Pagination className="mx-0 w-auto justify-end">
                    <PaginationContent>
                      <PaginationItem>
                        <PaginationPrevious href="#"
                          onClick={(e) => { e.preventDefault(); setPage((p) => Math.max(1, p - 1)); }} />
                      </PaginationItem>
                      <PaginationItem>
                        <PaginationLink href="#" isActive>{currentPage}</PaginationLink>
                      </PaginationItem>
                      <PaginationItem>
                        <PaginationNext href="#"
                          onClick={(e) => { e.preventDefault(); setPage((p) => Math.min(totalPages, p + 1)); }} />
                      </PaginationItem>
                    </PaginationContent>
                  </Pagination>
                </div>
              )}
            </div>
          )}
        </>
      )}

      <ContaSheet score={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

function ContaSheet({ score, onClose }: { score: Score | null; onClose: () => void }) {
  return (
    <Sheet open={!!score} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        {score && (
          <>
            <SheetHeader className="space-y-2">
              <div className="flex items-start justify-between gap-2">
                <SheetTitle className="font-display text-lg leading-tight">{score.name}</SheetTitle>
                <RiskBadge band={score.risk_band} />
              </div>
              <SheetDescription>{stageLabels[score.stage]}</SheetDescription>
            </SheetHeader>

            <div className="mt-6 space-y-6">
              <div className="rounded-xl bg-muted/40 p-4">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">Score de risco</div>
                <div className="mt-1 flex items-baseline gap-3">
                  <span className="font-display text-4xl font-bold tabular-nums">{score.score.toFixed(1)}</span>
                  <TrajectoryIcon t={score.trajectory} />
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>Confiança <strong className="tabular-nums text-foreground">{(score.confidence * 100).toFixed(0)}%</strong></span>
                  <span>·</span>
                  <span>{score.coverage_weeks} semanas de histórico</span>
                  {!score.evaluable && <CaveatChip text="Ainda não avaliável" tone="warning" />}
                </div>
              </div>

              {score.alert_sev && (
                <div>
                  <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Alerta ativo</div>
                  <SeverityBadge sev={score.alert_sev} />
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-border p-3">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">MRR</div>
                  <div className="mt-0.5 font-display text-lg font-bold tabular-nums">
                    {score.recurring_revenue != null ? formatBRL(score.recurring_revenue) : "—"}
                  </div>
                </div>
                <div className="rounded-xl border border-border p-3">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Squad</div>
                  <div className="mt-0.5 text-sm font-medium">{score.squad ?? "—"}</div>
                </div>
              </div>

              {score.reasons.length > 0 && (
                <div>
                  <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Motivos do score</div>
                  <ul className="space-y-2">
                    {score.reasons.map((r, i) => (
                      <li key={i} className="flex items-start gap-3 rounded-lg border border-border p-3">
                        <div className="flex min-w-[42px] flex-col items-center">
                          <span className="font-display text-sm font-bold tabular-nums text-foreground">{r.weight.toFixed(1)}</span>
                          <span className="text-[10px] text-muted-foreground">peso</span>
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="text-sm leading-snug text-foreground">{r.text}</p>
                          {r.leading && (
                            <span className="mt-1 inline-block text-[11px] text-primary">Motivo principal</span>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div>
                <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Diretriz de ação</div>
                <p className="rounded-lg border border-primary/20 bg-primary/[0.07] p-3 text-sm leading-relaxed text-foreground">
                  {score.recommendation}
                </p>
              </div>

              {score.exec_motivo && (
                <div>
                  <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Execução (ClickUp)</div>
                  <p className="rounded-lg bg-muted/50 p-3 text-sm leading-relaxed text-foreground">
                    {score.exec_motivo}
                    {score.exec_score != null && (
                      <span className="ml-2 text-muted-foreground">(nota: {score.exec_score.toFixed(0)}/100)</span>
                    )}
                  </p>
                </div>
              )}

              <div className="pt-2">
                <Button variant="outline" className="w-full" asChild>
                  <a href={`/growth/report?account_id=${score.account_id}`} target="_blank" rel="noopener">
                    Relatório completo da conta <ExternalLink className="ml-2 h-3.5 w-3.5" />
                  </a>
                </Button>
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
