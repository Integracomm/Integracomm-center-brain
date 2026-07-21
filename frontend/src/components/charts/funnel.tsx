import { ArrowRight } from "lucide-react";
import { formatNumber } from "@/lib/format";
import { chartColors } from "./chart-theme";

// Etapa genérica do funil. Cada tela pode ter tipos próprios; o componente
// aceita o mínimo que precisa desenhar.
export interface FunnelStep {
  key: string;
  label: string;
  volume: number;
  // Conversão da etapa anterior (0-100). Null na primeira etapa.
  conversao_da_anterior_pct: number | null;
}

// Funil de etapas com conversão entre passagens.
// Regra: conversão total NÃO é calculada aqui — vem via prop `conversaoTotalPct`
// (ver _shapes.md — agregados vêm do payload). Se undefined, a linha some.
export function Funnel({
  etapas,
  conversaoTotalPct,
  colors = chartColors,
}: {
  etapas: FunnelStep[];
  conversaoTotalPct?: number;
  colors?: string[];
}) {
  const max = Math.max(...etapas.map((e) => e.volume), 1);
  return (
    <div className="space-y-4">
      {etapas.map((e, i) => {
        const pct = (e.volume / max) * 100;
        const conv = e.conversao_da_anterior_pct;
        return (
          <div key={e.key} className="space-y-1.5">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">{e.label}</span>
              <div className="flex items-center gap-3">
                {conv != null && (
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {conv.toFixed(1)}% conv.
                  </span>
                )}
                <span className="font-display font-bold tabular-nums">
                  {formatNumber(e.volume)}
                </span>
              </div>
            </div>
            <div className="h-10 w-full rounded-lg bg-muted overflow-hidden">
              <div
                className="h-full rounded-lg transition-all duration-700 ease-out"
                style={{
                  width: `${pct}%`,
                  backgroundColor: colors[i % colors.length],
                  minWidth: "2rem",
                }}
              />
            </div>
          </div>
        );
      })}
      {conversaoTotalPct != null && etapas.length > 1 && (
        <div className="pt-2 mt-2 border-t border-border flex items-center gap-2 text-xs text-muted-foreground">
          <ArrowRight className="h-3 w-3" />
          Conversão total {etapas[0].label.toLowerCase()} →{" "}
          {etapas[etapas.length - 1].label.toLowerCase()}:{" "}
          <strong className="text-foreground tabular-nums">
            {conversaoTotalPct.toFixed(1)}%
          </strong>
        </div>
      )}
    </div>
  );
}
