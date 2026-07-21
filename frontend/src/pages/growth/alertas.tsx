import { useMemo, useState } from "react";
import { TimeSeries } from "@/components/charts/time-series";
import { formatBRL, formatDatePtBR } from "@/lib/format";
import { AlertOctagon, BellRing, Flame, Search, ShieldAlert } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { LoadingSkeleton, ErrorState, EmptyState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Pagination, PaginationContent, PaginationItem, PaginationLink,
  PaginationNext, PaginationPrevious,
} from "@/components/ui/pagination";
import { RiskBadge, SeverityBadge, stageLabels } from "@/components/growth-badges";
import type { Alert, AlertsEnvelope, Severity } from "@/types/api";

// Growth · Alertas — fila nominal ACIONÁVEL: mantém tabela (regra do guia:
// lista nominal não vira gráfico). KPIs prontos do payload (/api/alerts.kpis).
// Sem referência no protótipo (placeholder) — composição própria da biblioteca.
export function GrowthAlertasPage() {
  const q = useApi<AlertsEnvelope & { kpis: { total: number; critico: number; alto: number; atencao: number } }>("/api/alerts");
  const [search, setSearch] = useState("");
  const [sev, setSev] = useState<"todos" | Severity>("todos");
  const [modeloAberto, setModeloAberto] = useState(false);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 25;

  const alerts = q.data?.alerts ?? [];
  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    return alerts.filter((a) => {
      if (s && !a.name.toLowerCase().includes(s)) return false;
      if (sev !== "todos" && a.severity !== sev) return false;
      return true;
    });
  }, [alerts, search, sev]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pageRows = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  const k = q.data?.kpis;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-2xl font-bold tracking-tight">Alertas</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Fila de alertas abertos, do mais grave para o mais recente — a última nota do caso vem junto.
        </p>
      </header>

      {q.loading && <LoadingSkeleton rows={5} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {q.data && k && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <KpiCard icon={BellRing} tone="primary" title="Abertos" value={k.total.toLocaleString("pt-BR")} />
            <KpiCard icon={Flame} tone="destructive" title="Críticos" value={k.critico.toLocaleString("pt-BR")} />
            <KpiCard icon={AlertOctagon} tone="warning" title="Altos" value={k.alto.toLocaleString("pt-BR")} />
            <KpiCard icon={ShieldAlert} tone="muted" title="Atenção" value={k.atencao.toLocaleString("pt-BR")} />
          </div>

          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
            <div className="relative min-w-[220px] flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                placeholder="Buscar por nome da conta…" className="pl-9" />
            </div>
            <Select value={sev} onValueChange={(v) => { setSev(v as typeof sev); setPage(1); }}>
              <SelectTrigger className="w-[180px]"><SelectValue placeholder="Severidade" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="todos">Todas</SelectItem>
                <SelectItem value="critico">Crítico</SelectItem>
                <SelectItem value="alto">Alto</SelectItem>
                <SelectItem value="atencao">Atenção</SelectItem>
              </SelectContent>
            </Select>
            <div className="ml-auto text-xs text-muted-foreground">
              <strong className="tabular-nums text-foreground">{filtered.length}</strong> de{" "}
              <span className="tabular-nums">{alerts.length}</span> alertas
            </div>
          </div>

          {filtered.length === 0 ? (
            <EmptyState title="Nenhum alerta no filtro" description="A carteira está em dia — ou ajuste o filtro." />
          ) : (
            <div className="overflow-hidden rounded-xl border border-border bg-card">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    {["Conta", "Severidade", "Faixa", "Estágio", "Aberto em", "Última nota do caso"].map((h) => (
                      <TableHead key={h} className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{h}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pageRows.map((a: Alert) => (
                    <TableRow key={a.id}>
                      <TableCell className="max-w-[300px]"><span className="block truncate font-medium">{a.name}</span></TableCell>
                      <TableCell><SeverityBadge sev={a.severity} /></TableCell>
                      <TableCell><RiskBadge band={a.risk_band} /></TableCell>
                      <TableCell className="text-sm">{stageLabels[a.stage]}</TableCell>
                      <TableCell className="whitespace-nowrap text-sm tabular-nums">{formatDatePtBR(a.created_at)}</TableCell>
                      <TableCell className="max-w-[380px]">
                        {a.case_note ? (
                          <span className="block truncate text-sm text-muted-foreground" title={a.case_note}>
                            {a.case_note}
                            {a.case_note_by && <span className="text-muted-foreground/70"> · {a.case_note_by}</span>}
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
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
          <p className="text-xs text-muted-foreground">
            Notas iniciadas com <b>[auto]</b> foram detectadas pelo agente no WhatsApp (confirmadas semanticamente) —
            conteúdo gerado automaticamente, não por um gestor.
          </p>

          {/* Consulta eventual (Otávio 21/07): colapsado para não poluir o
              dia a dia — os dados só são buscados quando a seção abre. */}
          <details className="rounded-xl border border-border bg-card"
            onToggle={(e) => setModeloAberto((e.target as HTMLDetailsElement).open)}>
            <summary className="cursor-pointer p-4 text-sm font-medium text-foreground">
              Precisão do modelo e evolução do risco da carteira
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                consulta eventual — abre sob demanda
              </span>
            </summary>
            <div className="border-t border-border p-4">
              {modeloAberto && <ModeloSection />}
            </div>
          </details>
        </>
      )}
    </div>
  );
}


// ---- Precisão do modelo + risco da carteira (dados de /api/growth/modelo —
// mesmos _modelo_precisao e grw_risk_snapshot da tela HTML) ----
interface ModeloPayload {
  modelo: {
    alertadas: number; com_desf: number; cancel: number; retidas: number;
    negoc: number; retidas_int: number; crit_cancel: number; crit_desf: number;
    mrr_salvo: number;
  } | null;
  risco: Array<{ dia: string; criticos: number; altos: number; atencao: number; mrr_risco: number }>;
}

function ModeloSection() {
  const q = useApi<ModeloPayload>("/api/growth/modelo");
  if (q.loading) return <LoadingSkeleton rows={2} />;
  if (q.error) return <ErrorState message={q.error} onRetry={q.refetch} />;
  const m = q.data?.modelo;
  const risco = q.data?.risco ?? [];
  return (
    <div className="space-y-6">
      {m ? (
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Precisão do modelo — previsões × desfechos registrados
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              ["Contas alertadas", m.alertadas, null],
              ["Com desfecho registrado", m.com_desf, "registre desfechos na aba Contas — é o que alimenta esta medição"],
              ["Cancelaram (o alerta acertou)", m.cancel, null],
              ["Retidas COM intervenção", m.retidas_int, "o melhor resultado: alerta + ação + cliente ficou"],
              ["Retidas no total", m.retidas, null],
              ["Em negociação", m.negoc, null],
              ["Críticos com desfecho", m.crit_desf, `${m.crit_cancel} cancelaram`],
              ["MRR salvo (retidas)", formatBRL(m.mrr_salvo), null],
            ].map(([rot, val, nota]) => (
              <div key={String(rot)} className="rounded-lg border border-border p-3">
                <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{rot}</div>
                <div className="mt-0.5 font-display text-xl font-bold tabular-nums">{val as React.ReactNode}</div>
                {nota && <div className="mt-1 text-[11px] leading-snug text-muted-foreground">{nota}</div>}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Sem medição ainda — registre desfechos na aba Contas.</p>
      )}
      <div>
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Evolução do risco da carteira — 1 snapshot por dia
        </div>
        {risco.length >= 2 ? (
          <TimeSeries
            height={220}
            data={risco}
            xKey="dia"
            series={[
              { key: "criticos", label: "Críticos", color: "var(--destructive)" },
              { key: "altos", label: "Altos", color: "var(--warning)" },
              { key: "atencao", label: "Atenção", color: "var(--chart-3)" },
              { key: "mrr_risco", label: "MRR em risco", color: "var(--chart-2)", yAxis: "right",
                dashed: true, valueFormatter: (v) => formatBRL(v) },
            ]}
            rightTickFormatter={(v) => formatBRL(v, { compact: true })}
          />
        ) : (
          <p className="text-sm text-muted-foreground">
            Série iniciada agora ({risco.length} snapshot) — em poucas semanas este quadro responde se as
            intervenções estão reduzindo o risco da carteira.
          </p>
        )}
      </div>
    </div>
  );
}
