import { AlertTriangle, ArrowRight, ArrowUpRight } from "lucide-react";
import type { CentralPayload } from "./tipos";

// O QUE MUDOU DESDE ONTEM — o `tom` vem do backend e a tela SEPARA "exige
// ação" de "informativo": conta que entrou em crítico é a 1ª ligação do dia e
// não pode ter o peso de uma oportunidade nova (Otávio 22/07).

export function MudouDesdeOntem({ itens }: { itens: CentralPayload["mudancas"] }) {
  const acao = itens.filter((m) => m.tom === "acao");
  const info = itens.filter((m) => m.tom !== "acao");
  if (!itens.length) return null;

  return (
    <div className="space-y-3">
      {acao.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-destructive/30 bg-card">
          <div className="flex items-center gap-2 border-b border-destructive/20 bg-destructive/10 px-4 py-2">
            <AlertTriangle className="h-3.5 w-3.5 text-destructive" />
            <span className="text-[11px] font-bold uppercase tracking-wider text-destructive">Exige ação</span>
          </div>
          <ul className="divide-y divide-border">
            {acao.map((m) => (
              <li key={m.texto}>
                <a href={m.url} className="flex items-center gap-3 px-4 py-3 hover:bg-muted/40">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-destructive/15 text-destructive">
                    <ArrowUpRight className="h-4 w-4" />
                  </span>
                  <span className="flex-1 text-sm font-medium">{m.texto}</span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
      {info.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-border bg-card">
          <div className="border-b border-border px-4 py-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Informativo
            </span>
          </div>
          <ul className="divide-y divide-border">
            {info.map((m) => (
              <li key={m.texto}>
                <a href={m.url} className="flex items-center gap-3 px-4 py-2.5 hover:bg-muted/40">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                    <ArrowRight className="h-3.5 w-3.5" />
                  </span>
                  <span className="flex-1 text-sm text-muted-foreground">{m.texto}</span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
