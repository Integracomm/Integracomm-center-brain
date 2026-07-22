import { ChevronDown } from "lucide-react";
import { formatBRL } from "@/lib/format";
import { cn } from "@/lib/utils";
import { NIVEL_DOT, type CentralPayload } from "./tipos";

// INICIATIVAS DE MAIOR HORIZONTE — o último degrau da densidade decrescente,
// RECOLHIDO por padrão. Ordem e conteúdo vêm do backend (_hub_horizonte, que
// já remove o que virou objetivo confirmado da semana).

export function IniciativasHorizonte({ itens }: { itens: CentralPayload["horizonte"] }) {
  return (
    <details className="group rounded-2xl border border-border bg-card">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4">
        <div>
          <div className="font-display text-base font-semibold">
            Iniciativas de maior horizonte
            <span className="ml-2 text-xs font-normal text-muted-foreground">({itens.length})</span>
          </div>
          <div className="text-xs italic text-muted-foreground">
            gargalos que NÃO viraram objetivo desta semana · potencial estimado, não promessa · ordenado por R$/mês
          </div>
        </div>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      {itens.length === 0 ? (
        <p className="border-t border-border px-5 py-4 text-sm text-muted-foreground">
          Nenhuma iniciativa além das prioridades da semana — os gargalos atuais já viraram
          objetivos confirmados.
        </p>
      ) : (
        <ul className="divide-y divide-border border-t border-border">
          {itens.map((it) => (
            <li key={it.titulo} className="px-5 py-4">
              <a href={it.href} className="block hover:opacity-80">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="flex items-center gap-2 font-medium">
                    <span className={cn("h-2 w-2 shrink-0 rounded-full", NIVEL_DOT[it.nivel])} />
                    {it.titulo}
                  </span>
                  {it.faixa && (
                    <span className="rounded-lg bg-success/15 px-2.5 py-1 font-display text-sm font-bold tabular-nums text-success">
                      {formatBRL(it.faixa[0], { compact: true })} – {formatBRL(it.faixa[1], { compact: true })}/mês
                    </span>
                  )}
                </div>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{it.descricao}</p>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs italic text-muted-foreground">
                  {it.premissa && <span>Premissa: {it.premissa}</span>}
                  {it.defasagem && <span>{it.defasagem}</span>}
                </div>
              </a>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
