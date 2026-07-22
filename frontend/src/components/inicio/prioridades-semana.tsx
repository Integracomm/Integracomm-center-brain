import { Coins, Megaphone, PhoneCall, Handshake, TrendingUp, Target } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { formatBRL, formatNumber } from "@/lib/format";
import type { Impacto, Prioridade } from "./tipos";

// PRIORIDADES DA SEMANA — o bloco que resolve a parede de texto (redesenho
// 22/07): um CARD por objetivo em grid, escaneável em segundos. O conteúdo é o
// mesmo que a Central já mostrava; muda a hierarquia.
//
// A ordem vem do BACKEND (maior impacto pelo piso da faixa; sem estimativa por
// último) — o front não reordena, senão duas telas ordenariam diferente.

const TIME: Record<string, { icone: typeof Megaphone; cor: string }> = {
  marketing: { icone: Megaphone, cor: "text-chart-2" },
  prevendas: { icone: PhoneCall, cor: "text-chart-4" },
  vendas: { icone: Handshake, cor: "text-chart-1" },
  growth: { icone: TrendingUp, cor: "text-chart-3" },
};

function ImpactoChip({ impacto }: { impacto: Impacto | null }) {
  if (!impacto?.faixa) {
    // ausência de número NÃO é ausência de item — o card diz isso em vez de
    // inventar valor (Otávio 22/07)
    return (
      <span className="inline-flex items-center rounded-lg bg-muted px-3 py-1.5 text-xs font-medium italic text-muted-foreground">
        impacto não estimado
      </span>
    );
  }
  const [lo, hi] = impacto.faixa;
  return (
    <TooltipProvider delayDuration={100}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex cursor-help items-center gap-1.5 rounded-lg bg-success/15 px-3 py-1.5 text-success">
            <Coins className="h-3.5 w-3.5 shrink-0" />
            <span className="font-display text-sm font-bold tabular-nums">
              {formatBRL(lo, { compact: true })} – {formatBRL(hi, { compact: true })}/mês em jogo
            </span>
          </span>
        </TooltipTrigger>
        {/* a PREMISSA do valor mora aqui — número em R$ nunca aparece sozinho */}
        <TooltipContent className="max-w-xs text-xs">{impacto.premissa}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function ObjetivoCard({ p, i }: { p: Prioridade; i: number }) {
  return (
    <div className="flex flex-col rounded-2xl border border-border bg-card p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            <Target className="h-3.5 w-3.5 text-primary" />
            Objetivo{p.metric ? ` · ${p.metric}` : ""}
          </div>
          <h3 className="mt-1 font-display text-lg font-bold leading-tight">
            <span className="text-primary">{i} ·</span> {p.titulo}
          </h3>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <ImpactoChip impacto={p.impacto} />
          {p.target != null && (
            <Badge className="border-0 bg-primary/15 tabular-nums text-primary">
              Meta: {formatNumber(p.target)}
            </Badge>
          )}
        </div>
      </div>

      {/* o racional carrega ressalvas do backend (ex.: "resultado ainda em
          maturação (defasagem ~60 dias); não leia como falha da semana" no
          churn de B3) — nunca resumir nem cortar */}
      {p.racional && <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{p.racional}</p>}

      {p.acoes.length > 0 && (
        <div className="mt-4 space-y-2 border-t border-border pt-3">
          {p.acoes.map((a, j) => {
            const t = TIME[a.team] ?? { icone: TrendingUp, cor: "text-muted-foreground" };
            const Icone = t.icone;
            return (
              <div key={`${p.titulo}-${j}`} className="flex gap-3 rounded-lg bg-muted/40 p-3">
                <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-background", t.cor)}>
                  <Icone className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {a.team_label}
                  </span>
                  <div className="text-sm font-medium leading-snug">{a.manchete}</div>
                  {a.detalhe && (
                    <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{a.detalhe}</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function PrioridadesSemana({ itens }: { itens: Prioridade[] }) {
  if (!itens.length) return null;
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      {itens.map((p, i) => <ObjetivoCard key={p.titulo} p={p} i={i + 1} />)}
    </div>
  );
}
