import { cn } from "@/lib/utils";
import { NIVEL_BG, NIVEL_BORDA, type CentralPayload, type Metrica } from "./tipos";
import { fmtValor, mval } from "./formato";

// Métrica do card: VALOR grande, "/meta" apagado ao lado, rótulo miúdo embaixo.
// O formato lista (rótulo à esquerda, valor à direita, ambos pequenos) deixava
// o número menos visível — o Otávio preferiu este (23/07).
function Metric({ m }: { m: Metrica }) {
  return (
    <div className="min-w-0">
      <div className="font-display text-xl font-bold leading-none tabular-nums">
        {mval(m)}
        {m.meta != null && m.valor != null && (
          <span className="text-sm font-semibold text-muted-foreground/70">
            /{fmtValor(m.meta, m.formato)}
          </span>
        )}
      </div>
      <div className="mt-1 text-[10px] uppercase leading-tight tracking-wide text-muted-foreground">
        {m.rotulo}
      </div>
    </div>
  );
}

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
            <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-3">
              {a.metricas.map((m) => <Metric key={m.rotulo} m={m} />)}
            </div>
          )}
          <p className="mt-3 text-xs leading-snug text-muted-foreground">{a.detalhe}</p>
        </a>
      ))}
    </div>
  );
}
