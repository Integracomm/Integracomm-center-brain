import { cn } from "@/lib/utils";
import { NIVEL_BG, NIVEL_BORDA, type CentralPayload } from "./tipos";
import { valorComMeta } from "./formato";

// ANDAMENTO DAS ÁREAS — cards compactos lado a lado. Quais métricas entram em
// cada card é decisão do backend (_hub_area_cards, composição COMPLEMENTAR:
// sem número repetido entre áreas).

export function AndamentoAreas({ itens }: { itens: CentralPayload["areas"] }) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      {itens.map((a) => (
        <a key={a.area} href={a.href}
          className={cn("rounded-xl border border-l-4 border-border bg-card p-4 hover:bg-muted/40",
            NIVEL_BORDA[a.nivel])}>
          <div className="flex items-center justify-between gap-2">
            <h4 className="font-display text-sm font-semibold">{a.nome}</h4>
            <span className={cn("rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
              NIVEL_BG[a.nivel])}>
              {a.nivel_label}
            </span>
          </div>
          {a.metricas.length > 0 && (
            <dl className="mt-3 space-y-1.5">
              {a.metricas.map((m) => (
                <div key={m.rotulo} className="flex items-baseline justify-between gap-3 text-sm">
                  <dt className="min-w-0 truncate text-muted-foreground" title={m.rotulo}>{m.rotulo}</dt>
                  <dd className="shrink-0 font-display font-semibold tabular-nums">{valorComMeta(m)}</dd>
                </div>
              ))}
            </dl>
          )}
          <p className="mt-3 text-xs leading-snug text-muted-foreground">{a.detalhe}</p>
        </a>
      ))}
    </div>
  );
}
