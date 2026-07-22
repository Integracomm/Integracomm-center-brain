import { cn } from "@/lib/utils";
import { NIVEL_BG, NIVEL_DOT, type CentralPayload } from "./tipos";

// SAÚDE POR ÁREA — a ordem vem do backend (a que mais demanda atenção primeiro).
// Cor SEMPRE acompanhada de rótulo.

export function SaudePorArea({ itens }: { itens: CentralPayload["saude"] }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-card">
      <ul className="divide-y divide-border">
        {itens.map((s) => (
          <li key={s.area}>
            <a href={s.href} className="flex items-center gap-4 px-5 py-3.5 hover:bg-muted/40">
              <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", NIVEL_DOT[s.nivel])} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{s.nome}</span>
                  <span className={cn("rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                    NIVEL_BG[s.nivel])}>
                    {s.nivel_label}
                  </span>
                  {s.pior && (
                    <span className="rounded-md bg-destructive px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-destructive-foreground">
                      maior atenção agora
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-sm text-muted-foreground">{s.motivo}</p>
              </div>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
