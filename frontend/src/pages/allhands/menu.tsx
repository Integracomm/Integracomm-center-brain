import { BarChart3, Presentation } from "lucide-react";

// All Hands · porta de entrada (Otávio 24/07). Duas opções:
//  - Dados do mês: SPA (esta área);
//  - Apresentação: segue em HTML por decisão (gerador de slides/PPTX) — o
//    link faz full page load de propósito.
export function AllHandsMenuPage() {
  const card = "block rounded-xl border border-border bg-card p-6 transition-colors hover:border-primary/50";
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-2xl font-bold tracking-tight">All Hands</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          o fechamento do mês e a apresentação mensal, num lugar só.
        </p>
      </header>
      <div className="grid max-w-2xl gap-4">
        <a href="/allhands?view=dados" className={card}>
          <div className="flex items-center gap-2 font-display text-base font-semibold">
            <BarChart3 className="h-5 w-5 text-primary" /> Dados do mês (fechamento por área)
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            Marketing, Pré-vendas, Vendas, Assessoria e Estratégia num relatório só, nas mesmas
            réguas do painel — o consolidado que os coordenadores montam à mão todo mês.
            O que não tem fonte automática aparece marcado.
          </p>
        </a>
        <a href="/allhands?view=apresentacao" className={card}>
          <div className="flex items-center gap-2 font-display text-base font-semibold">
            <Presentation className="h-5 w-5 text-primary" /> Apresentação do All Hands
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            Gera os slides no design do deck: dados automáticos + destaques, novos colaboradores,
            orientações e slides extras. Exporta em PDF ou PPTX.
          </p>
        </a>
      </div>
    </div>
  );
}
