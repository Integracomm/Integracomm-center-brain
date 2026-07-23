import { formatBRL } from "@/lib/format";
import { cn } from "@/lib/utils";
import { BlocoRetratil } from "./bloco-retratil";
import { NIVEL_DOT, type CentralPayload } from "./tipos";

// INICIATIVAS DE MAIOR HORIZONTE — o último degrau da densidade decrescente,
// RECOLHIDO por padrão. Ordem e conteúdo vêm do backend (_hub_horizonte, que
// já remove o que virou objetivo confirmado da semana).

export function IniciativasHorizonte({ itens }: { itens: CentralPayload["horizonte"] }) {
  return (
    <BlocoRetratil
      titulo="Iniciativas de maior horizonte"
      contagem={itens.length}
      sub="gargalos que NÃO viraram objetivo desta semana · potencial estimado, não promessa · ordenado por R$/mês">
      {itens.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">
          Nenhuma iniciativa além das prioridades da semana — os gargalos atuais já viraram
          objetivos confirmados.
        </p>
      ) : (
        <ul className="divide-y divide-border">
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
    </BlocoRetratil>
  );
}
