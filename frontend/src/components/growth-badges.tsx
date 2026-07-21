import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { RiskBand, Severity, Stage } from "@/types/api";

// Rótulos e selos compartilhados das telas de Growth (Contas, Alertas,
// Cancelamentos). Regra da biblioteca: cor SEMPRE acompanhada de rótulo.

export const stageLabels: Record<Stage, string> = {
  saudavel: "Saudável",
  insatisfacao_latente: "Insatisfação latente",
  desengajamento_inicial: "Desengajamento inicial",
  insatisfacao_ativa: "Insatisfação ativa",
  intencao_de_saida: "Intenção de saída",
};

export const riskLabels: Record<RiskBand, string> = {
  alto: "Alto",
  medio: "Médio",
  baixo: "Baixo",
  sem_dados: "Sem dados",
};

export const severityLabels: Record<Severity, string> = {
  critico: "Crítico",
  alto: "Alto",
  atencao: "Atenção",
};

export function RiskBadge({ band }: { band: RiskBand }) {
  const cls: Record<RiskBand, string> = {
    alto: "bg-destructive/15 text-destructive",
    medio: "bg-warning/15 text-warning",
    baixo: "bg-success/15 text-success",
    sem_dados: "bg-muted text-muted-foreground",
  };
  return <Badge className={cn("border-0 font-medium", cls[band])}>{riskLabels[band]}</Badge>;
}

export function SeverityBadge({ sev }: { sev: Severity | null }) {
  if (!sev) return <span className="text-xs text-muted-foreground">—</span>;
  const cls: Record<Severity, string> = {
    critico: "bg-destructive/15 text-destructive",
    alto: "bg-warning/15 text-warning",
    atencao: "bg-chart-3/15 text-chart-3",
  };
  return <Badge className={cn("border-0 font-medium", cls[sev])}>{severityLabels[sev]}</Badge>;
}

export function TrajectoryIcon({ t }: { t: string }) {
  const map: Record<string, { Icon: typeof TrendingUp; cls: string; label: string }> = {
    piorando: { Icon: TrendingDown, cls: "text-destructive", label: "Piorando" },
    caindo: { Icon: TrendingDown, cls: "text-warning", label: "Caindo" },
    estavel: { Icon: Minus, cls: "text-muted-foreground", label: "Estável" },
    subindo: { Icon: TrendingUp, cls: "text-success", label: "Subindo" },
  };
  const m = map[t] ?? map.estavel;
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs", m.cls)} title={m.label}>
      <m.Icon className="h-3.5 w-3.5" /> {m.label}
    </span>
  );
}
