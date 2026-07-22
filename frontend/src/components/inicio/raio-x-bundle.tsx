import { cn } from "@/lib/utils";
import { NIVEL_TXT, type CentralPayload } from "./tipos";

// RAIO-X COMPACTO POR BUNDLE — mesmos números do Raio-X completo.
// `aviso` (coorte pequena) e `nota` (por que a soma dos bundles não fecha com
// o total de Vendas) vêm PRONTOS do backend: são ressalvas, não decoração.

export function RaioXBundle({ itens, nota }: { itens: CentralPayload["bundles"]; nota: string }) {
  if (!itens.length) return null;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {itens.map((b) => {
          const pct = b.meta && b.meta > 0 ? Math.min(100, Math.round((b.bookings / b.meta) * 100)) : null;
          return (
            <a key={b.bundle} href={`/raiox?b=${b.bundle}`}
              className={cn("rounded-xl border bg-card p-4 hover:bg-muted/40",
                b.pior ? "border-destructive/50 ring-2 ring-destructive/20" : "border-border")}>
              <div className="flex items-center justify-between gap-1">
                <span className="font-display text-lg font-bold">{b.bundle}</span>
                {b.pior && (
                  <span className="rounded bg-destructive/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-destructive">
                    mais fora da meta
                  </span>
                )}
              </div>
              <div className="mt-3">
                <div className="flex items-baseline justify-between text-xs text-muted-foreground">
                  <span>Bookings</span>
                  <span className={cn("font-medium tabular-nums", NIVEL_TXT[b.nivel])}>
                    {b.bookings}{b.meta != null ? `/${b.meta.toFixed(0)}` : ""}
                  </span>
                </div>
                {pct != null && (
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                    <div className={cn("h-full rounded-full",
                      pct >= 100 ? "bg-success" : pct >= 60 ? "bg-primary" : "bg-warning")}
                      style={{ width: `${pct}%` }} />
                  </div>
                )}
              </div>
              <div className="mt-3 flex items-baseline justify-between gap-1 text-xs">
                <span className="shrink-0 text-muted-foreground">Churn precoce</span>
                {b.churn_precoce != null ? (
                  <span className={cn("font-medium tabular-nums",
                    b.churn_precoce > 0.15 ? "text-destructive" : "text-foreground")}>
                    {(b.churn_precoce * 100).toFixed(0)}%
                  </span>
                ) : (
                  <span className="text-right text-[10px] italic leading-tight text-muted-foreground">
                    {b.aviso ?? "sem dados"}
                  </span>
                )}
              </div>
            </a>
          );
        })}
      </div>
      {nota && <p className="text-xs italic leading-relaxed text-muted-foreground">{nota}</p>}
    </div>
  );
}
