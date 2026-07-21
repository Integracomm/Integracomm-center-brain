import { cn } from "@/lib/utils";

// Barra de progresso vs META com marcador — "realizado contra alvo" das
// telas de metas/forecast (aprovado no plano do redesenho, Otávio 21/07:
// mini-primitivo p/ não reinventar em 4 telas).
// Regras da biblioteca: rótulo de valor SEMPRE visível; cor + rótulo, nunca
// só cor; `pace` opcional marca onde o realizado DEVERIA estar hoje.
export function MetaBar({
  value,
  target,
  valueLabel,
  targetLabel,
  pacePct,
  className,
}: {
  value: number;
  target: number;
  valueLabel: string;            // ex.: "R$ 61,4 mil" | "590 leads"
  targetLabel: string;           // ex.: "meta R$ 96 mil"
  // % do alvo em que o realizado deveria estar HOJE (fração do período
  // decorrido, 0-100). Vem do backend — o componente não calcula ritmo.
  pacePct?: number;
  className?: string;
}) {
  const pct = target > 0 ? Math.min((value / target) * 100, 100) : 0;
  const cheio = target > 0 && value >= target;
  const atras = pacePct != null && target > 0 && (value / target) * 100 < pacePct - 5;
  const cor = cheio ? "bg-success" : atras ? "bg-warning" : "bg-primary";
  return (
    <div className={cn("w-full", className)}>
      <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
        <span className="font-display font-semibold tabular-nums">{valueLabel}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {targetLabel}
          {atras && <span className="ml-2 font-medium text-warning">atrás do ritmo</span>}
          {cheio && <span className="ml-2 font-medium text-success">meta batida</span>}
        </span>
      </div>
      <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all", cor)}
          style={{ width: `${pct}%` }}
        />
        {pacePct != null && pacePct > 0 && pacePct < 100 && (
          <div
            className="absolute top-[-2px] h-[14px] w-0.5 rounded bg-foreground/60"
            title={`ritmo esperado hoje: ${pacePct.toFixed(0)}% da meta`}
            style={{ left: `${pacePct}%` }}
          />
        )}
      </div>
    </div>
  );
}
