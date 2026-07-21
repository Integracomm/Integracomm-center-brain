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

// Execução (ClickUp): mesmas faixas da tela HTML — >=70 em dia · 40-69 atenção
// · <40 crítica. Cliente pausado/concluído ganha selo próprio (não é atraso).
export function ExecBadge({ score, inativo }: { score: number | null; inativo: string | null }) {
  if (inativo) {
    const rot = inativo.includes("pausada") ? "pausado" : "concluído";
    return <Badge className="border-0 bg-muted font-medium text-muted-foreground"
      title={`cliente ${inativo} no ClickUp — serviço suspenso`}>{rot}</Badge>;
  }
  if (score == null) return <span className="text-xs text-muted-foreground">—</span>;
  const [cls, rot] = score >= 70
    ? ["bg-success/15 text-success", "em dia"]
    : score >= 40
      ? ["bg-warning/15 text-warning", "atenção"]
      : ["bg-destructive/15 text-destructive", "crítica"];
  return <Badge className={cn("border-0 font-medium tabular-nums", cls)}>{score.toFixed(0)} · {rot}</Badge>;
}

// Atrasos: entregas ABERTAS com vencimento estourado (regra da Análise dos
// Squads — pausados não contam e aparecem no ExecBadge).
export function AtrasosBadge({ n, execScore, inativo }: {
  n: number | null; execScore: number | null; inativo: string | null;
}) {
  if (inativo) return <span className="text-xs text-muted-foreground">—</span>;
  if (n == null || execScore == null) return <span className="text-xs text-muted-foreground">—</span>;
  if (n > 0) {
    return <Badge className="border-0 bg-destructive/15 font-medium tabular-nums text-destructive"
      title="entregas abertas com vencimento estourado — nomes e responsáveis no relatório da conta">{n} atrasada(s)</Badge>;
  }
  return <Badge className="border-0 bg-success/15 font-medium text-success">em dia</Badge>;
}
