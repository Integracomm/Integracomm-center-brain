import { ChevronDown } from "lucide-react";

// Bloco recolhido — o último degrau da densidade decrescente.
// UM componente para os dois blocos retráteis da Central (iniciativas de
// horizonte e defasagens): eles eram irmãos com formatação diferente, o que
// fazia parecer dois padrões (Otávio 23/07).

export function BlocoRetratil({ titulo, contagem, sub, children }: {
  titulo: string;
  contagem?: number;
  sub?: string;
  children: React.ReactNode;
}) {
  return (
    <details className="group rounded-2xl border border-border bg-card">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4">
        <div className="min-w-0">
          <div className="font-display text-base font-semibold">
            {titulo}
            {contagem != null && (
              <span className="ml-2 text-xs font-normal text-muted-foreground">({contagem})</span>
            )}
          </div>
          {sub && <div className="mt-0.5 text-xs italic text-muted-foreground">{sub}</div>}
        </div>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-border">{children}</div>
    </details>
  );
}
