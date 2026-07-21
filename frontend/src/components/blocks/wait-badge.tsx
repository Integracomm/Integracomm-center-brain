import { Clock } from "lucide-react";
import { cn } from "@/lib/utils";

export type WaitTone = "muted" | "warning" | "destructive";

export interface WaitThreshold {
  // Valor mínimo (inclusivo) em que este tom se aplica.
  gte: number;
  tone: WaitTone;
}

// Badge de tempo escalonado. Recebe thresholds ordenados por gte crescente.
// Ex.: [{gte:24,tone:"warning"},{gte:48,tone:"destructive"}]
// Antes de 24h → muted. 24–47h → warning. ≥48h → destructive.
export function WaitBadge({
  value,
  unit = "h",
  thresholds,
  icon = true,
}: {
  value: number;
  unit?: string;
  thresholds: WaitThreshold[];
  icon?: boolean;
}) {
  const sorted = [...thresholds].sort((a, b) => a.gte - b.gte);
  let tone: WaitTone = "muted";
  for (const t of sorted) {
    if (value >= t.gte) tone = t.tone;
  }
  const cls: Record<WaitTone, string> = {
    muted: "bg-muted text-muted-foreground",
    warning: "bg-warning/15 text-warning",
    destructive: "bg-destructive/15 text-destructive",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
        cls[tone],
      )}
    >
      {icon && <Clock className="h-3 w-3" />}
      {value.toLocaleString("pt-BR")}
      {unit}
    </span>
  );
}
