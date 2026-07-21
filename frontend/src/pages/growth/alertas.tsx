import { useMemo, useState } from "react";
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
import { formatDatePtBR } from "@/lib/format";
import { RiskBadge, SeverityBadge, stageLabels } from "@/components/growth-badges";
import type { Alert, AlertsEnvelope, Severity } from "@/types/api";

// Growth · Alertas — fila nominal ACIONÁVEL: mantém tabela (regra do guia:
// lista nominal não vira gráfico). KPIs prontos do payload (/api/alerts.kpis).
// Sem referência no protótipo (placeholder) — composição própria da biblioteca.
export function GrowthAlertasPage() {
  const q = useApi<AlertsEnvelope & { kpis: { total: number; critico: number; alto: number; atencao: number } }>("/api/alerts");
  const [search, setSearch] = useState("");
  const [sev, setSev] = useState<"todos" | Severity>("todos");

  const alerts = q.data?.alerts ?? [];
  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    return alerts.filter((a) => {
      if (s && !a.name.toLowerCase().includes(s)) return false;
      if (sev !== "todos" && a.severity !== sev) return false;
      return true;
    });
  }, [alerts, search, sev]);

  const k = q.data?.kpis;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-2xl font-bold tracking-tight">Growth · Alertas</h1>
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
              <Input value={search} onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar por nome da conta…" className="pl-9" />
            </div>
            <Select value={sev} onValueChange={(v) => setSev(v as typeof sev)}>
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
                  {filtered.map((a: Alert) => (
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
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            Notas iniciadas com <b>[auto]</b> foram detectadas pelo agente no WhatsApp (confirmadas semanticamente) —
            conteúdo gerado automaticamente, não por um gestor.
          </p>
        </>
      )}
    </div>
  );
}
