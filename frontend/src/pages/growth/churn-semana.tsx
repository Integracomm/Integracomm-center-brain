import { AlertTriangle, ArrowRight, CalendarClock, TrendingDown, Users } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { KpiCard } from "@/components/kpi-card";
import { formatBRL, formatNumber } from "@/lib/format";

// Cancelamentos da semana — o guia da reunião semanal de cancelamentos
// (Otávio 27/07: mesmo papel que as Ações da Semana têm hoje). Estrutura:
// o que aconteceu na semana que passou + o que fazer nesta. Tudo vem de
// /api/growth/churn-semana, que EMBRULHA as réguas já existentes.

interface Conta {
  cliente: string; plano: string | null; gc: string | null;
  motivo: string; grupo: string; meses_casa: number | null;
}
interface Grupo { base: number; saidas: number; taxa: number | null }
interface Payload {
  semana: { ini: string; fim: string };
  semana_anterior: { ini: string; fim: string };
  anterior: {
    total: number; mrr_perdido: number; revertidos: number; contas: Conta[];
    por_grupo: { novos: Grupo; antigos: Grupo; recorrentes: Grupo };
    b1_fora: { base: number; saidas: number };
    sem_dia_lancado: number;
  };
  em_curso: { total: number; mrr_perdido: number; contas: Conta[] };
  acoes: Array<{ prioridade: number; tipo: string; titulo: string;
    porque: string; contas: string[]; link: string }>;
  base_viva: number;
  regua: string;
}

const dia = (iso: string) => {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
};

const ROTULO_GRUPO: Record<string, string> = {
  novo: "novo (B2-B5)", antigo: "antigo", b1: "B1/Start", sem_tag: "sem tag",
};

function LinhaGrupo({ rot, g, sub }: { rot: string; g: Grupo; sub?: string }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border py-2 last:border-b-0">
      <div>
        <span className="font-medium">{rot}</span>
        <div className="text-xs text-muted-foreground">
          {g.saidas} saída(s) sobre base de {formatNumber(g.base)}{sub ? ` · ${sub}` : ""}
        </div>
      </div>
      <span className="whitespace-nowrap font-semibold tabular-nums">
        {g.taxa != null ? `${(g.taxa * 100).toFixed(2)}%` : "—"}
      </span>
    </div>
  );
}

export function GrowthChurnSemanaPage() {
  const q = useApi<Payload>("/api/growth/churn-semana");
  const d = q.data;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-2xl font-bold tracking-tight">
          Cancelamentos da semana
          {d && <span className="text-primary"> · {dia(d.semana.ini)} a {dia(d.semana.fim)}</span>}
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          O guia da reunião semanal: o que saiu na semana passada e o que precisa
          de ação nesta. Mesmas réguas do painel de Cancelamentos e do All Hands —
          B1/Start fica fora das taxas (é semestral à vista, não recorrente).
        </p>
      </header>

      {q.loading && !d && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <LoadingSkeleton rows={1} /><LoadingSkeleton rows={1} />
            <LoadingSkeleton rows={1} /><LoadingSkeleton rows={1} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2"><LoadingSkeleton rows={4} /><LoadingSkeleton rows={4} /></div>
        </>
      )}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}

      {d && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard icon={TrendingDown} tone="destructive" title="Saídas na semana passada"
              value={formatNumber(d.anterior.total)}
              subtitle={`${dia(d.semana_anterior.ini)} a ${dia(d.semana_anterior.fim)}`} />
            <KpiCard icon={TrendingDown} tone="warning" title="MRR perdido"
              value={formatBRL(d.anterior.mrr_perdido)} subtitle="na semana passada" />
            <KpiCard icon={Users} tone="accent" title="Carteira viva"
              value={formatNumber(d.base_viva)} subtitle="base das taxas (sem encerradas)" />
            <KpiCard icon={CalendarClock} tone="primary" title="Saídas nesta semana"
              value={formatNumber(d.em_curso.total)}
              subtitle={d.em_curso.total ? formatBRL(d.em_curso.mrr_perdido) : "até agora"} />
          </div>

          {/* AÇÕES primeiro: é o que a reunião precisa decidir */}
          <SectionCard title="O que fazer nesta semana"
            subtitle="fila em ordem de prioridade, montada a partir do risco medido — não é lista genérica">
            {d.acoes.length === 0 ? (
              <p className="py-2 text-sm text-muted-foreground">
                Nenhuma frente aberta: sem alertas críticos, tratativas ou execução crítica.
              </p>
            ) : d.acoes.map((a) => (
              <div key={a.tipo} className="border-b border-border py-3 last:border-b-0">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-medium">{a.titulo}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{a.porque}</p>
                    <p className="mt-1 text-xs">
                      {a.contas.slice(0, 6).join(" · ")}
                      {a.contas.length > 6 && ` … +${a.contas.length - 6}`}
                    </p>
                  </div>
                  <a href={a.link}
                    className="flex shrink-0 items-center gap-1 text-xs text-primary hover:underline">
                    abrir <ArrowRight className="h-3 w-3" />
                  </a>
                </div>
              </div>
            ))}
          </SectionCard>

          <div className="grid items-start gap-4 lg:grid-cols-2">
            <SectionCard title="Taxa da semana passada" headerClassName="min-h-[46px]"
              subtitle="novos e antigos separados e juntos — B1/Start fora das duas pontas">
              <LinhaGrupo rot="Novos (B2-B5)" g={d.anterior.por_grupo.novos} />
              <LinhaGrupo rot="Antigos (runoff)" g={d.anterior.por_grupo.antigos} />
              <LinhaGrupo rot="Recorrentes (juntos)" g={d.anterior.por_grupo.recorrentes}
                sub="novos + antigos" />
              <p className="mt-2 text-xs text-muted-foreground">
                Taxa semanal (saídas da semana ÷ carteira viva) — não confundir com a
                mensal do painel de Cancelamentos. B1/Start: {d.anterior.b1_fora.base} conta(s)
                na base e {d.anterior.b1_fora.saidas} saída(s), fora de todas as taxas acima.
                {d.anterior.sem_dia_lancado > 0 && (
                  <> ⚠ {d.anterior.sem_dia_lancado} cancelamento(s) do mês sem data de saída
                  lançada na planilha — entram no total do mês, mas não dá para atribuí-los
                  a uma semana.</>
                )}
              </p>
            </SectionCard>

            <SectionCard title="Quem saiu na semana passada" headerClassName="min-h-[46px]"
              subtitle={d.anterior.revertidos > 0
                ? `${d.anterior.total} saída(s) · ${d.anterior.revertidos} revertida(s)`
                : `${d.anterior.total} saída(s) formalizada(s)`}>
              {d.anterior.contas.length === 0 ? (
                <p className="py-2 text-sm text-muted-foreground">
                  Nenhuma saída com data na semana passada.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-muted-foreground">
                        <th className="border-b border-border py-1.5 pr-2 font-medium">Cliente</th>
                        <th className="border-b border-border py-1.5 pr-2 font-medium">Grupo</th>
                        <th className="border-b border-border py-1.5 pr-2 font-medium">GC</th>
                        <th className="border-b border-border py-1.5 text-right font-medium">Casa</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.anterior.contas.map((c) => (
                        <tr key={c.cliente}>
                          <td className="border-b border-border/50 py-1.5 pr-2">
                            {c.cliente}
                            {c.motivo && <div className="text-muted-foreground">{c.motivo}</div>}
                          </td>
                          <td className="border-b border-border/50 py-1.5 pr-2">
                            {ROTULO_GRUPO[c.grupo] ?? c.grupo}
                          </td>
                          <td className="border-b border-border/50 py-1.5 pr-2">{c.gc ?? "—"}</td>
                          <td className="border-b border-border/50 py-1.5 text-right tabular-nums">
                            {c.meses_casa != null ? `${c.meses_casa.toFixed(0)}m` : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </SectionCard>
          </div>

          {d.em_curso.total > 0 && (
            <SectionCard title="Já saiu nesta semana"
              subtitle="formalizações com data dentro da semana corrente">
              {d.em_curso.contas.map((c) => (
                <div key={c.cliente} className="flex items-start justify-between gap-3 border-b border-border py-2 last:border-b-0">
                  <div>
                    <span className="text-sm font-medium">{c.cliente}</span>
                    <div className="text-xs text-muted-foreground">
                      {ROTULO_GRUPO[c.grupo] ?? c.grupo}{c.gc ? ` · ${c.gc}` : ""}
                      {c.motivo ? ` · ${c.motivo}` : ""}
                    </div>
                  </div>
                  <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
                </div>
              ))}
            </SectionCard>
          )}

          <p className="text-xs text-muted-foreground">Régua: {d.regua}.</p>
        </>
      )}
    </div>
  );
}
