import { AlertTriangle, ArrowRight, ArrowUpRight, ChevronRight } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { formatBRL, formatNumber } from "@/lib/format";

// Central (hub do admin) — /api/central COMPÕE as mesmas funções da tela HTML
// (_hub_saude, _hub_kpis, _hub_area_cards, _hub_horizonte, mini_cards_dados,
// _hub_mudancas_itens, _hub_lags) e os objetivos da semana com o impacto em R$.
// Nenhuma régua nova, nenhum número recalculado aqui.
//
// ORDEM CANÔNICA (reconstrução 22/07 — é a rotina de leitura diária do Otávio):
// prioridades → o que mudou → números-chave → saúde por área → raio-x compacto
// → cards de área → iniciativas de maior horizonte → defasagens (recolhida).

interface Impacto { faixa: [number, number] | null; janela: string | null; premissa: string }
interface Metrica {
  rotulo: string; valor: number | null; formato: string;
  meta: number | null; tom: string | null; texto: string | null;
}
interface Payload {
  stats: { monitored: number; evaluable: number; sev: Record<string, number>;
    mrr_risk: number; mrr_crit: number; non_eval: number };
  kpis: Metrica[];
  saude: Array<{ area: string; nome: string; href: string; nivel: string;
    nivel_label: string; motivo: string; pior: boolean }>;
  bundles: Array<{ bundle: string; meta: number | null; bookings: number;
    churn_precoce: number | null; ratio: number | null; nivel: string; pior: boolean }>;
  areas: Array<{ area: string; nome: string; href: string; nivel: string;
    nivel_label: string; metricas: Metrica[]; detalhe: string }>;
  horizonte: Array<{ titulo: string; descricao: string; nivel: string; href: string;
    faixa: [number, number] | null; premissa: string | null; defasagem: string | null }>;
  defasagens: Array<{ titulo: string; texto: string }>;
  mudancas: Array<{ texto: string; url: string; tom: string }>;
  fontes_paradas: string[];
  prioridades: Array<{ titulo: string; racional: string | null; metric: string | null;
    impacto: Impacto | null;
    acoes: Array<{ team: string; team_label: string; manchete: string; detalhe: string }> }>;
}

// ---- formatação (o QUE mostrar vem do endpoint; aqui só o COMO) -------------
const fmtValor = (v: number | null, formato: string) => {
  if (v == null) return "—";
  if (formato === "brl") return formatBRL(v);
  if (formato === "pct1") return `${(v * 100).toFixed(1).replace(".", ",")}%`;
  if (formato === "pct0") return `${(v * 100).toFixed(0)}%`;
  if (formato === "pctp") return `${v.toFixed(0)}%`;
  return formatNumber(Math.round(v)); // contagens e índices: inteiros, como no HTML
};
const mval = (m: Metrica) => (m.texto != null ? m.texto : fmtValor(m.valor, m.formato));

// tom da métrica (verde = no ritmo) e nível de saúde compartilham a paleta
const TOM_TXT: Record<string, string> = {
  ok: "text-success", medio: "text-warning",
  alto: "text-warning", critico: "text-destructive",
};
const NIVEL_TXT: Record<string, string> = {
  verde: "text-success", baixo: "text-success", medio: "text-warning",
  alto: "text-warning", critico: "text-destructive", semdados: "text-muted-foreground",
};
const NIVEL_BG: Record<string, string> = {
  verde: "bg-success/15 text-success", baixo: "bg-success/15 text-success",
  medio: "bg-warning/15 text-warning", alto: "bg-warning/15 text-warning",
  critico: "bg-destructive/15 text-destructive",
  semdados: "bg-muted text-muted-foreground",
};
const NIVEL_DOT: Record<string, string> = {
  verde: "bg-success", baixo: "bg-success", medio: "bg-warning",
  alto: "bg-warning", critico: "bg-destructive", semdados: "bg-muted-foreground",
};

const faixaBRL = (f: [number, number] | null | undefined) =>
  f ? `${formatBRL(f[0])} – ${formatBRL(f[1])}` : null;

// Métrica de card compacto: valor grande, "/meta" apagado ao lado, rótulo miúdo
function Metric({ m }: { m: Metrica }) {
  return (
    <div className="min-w-0">
      <div className={cn("font-display text-xl font-bold tabular-nums leading-none",
        m.tom ? TOM_TXT[m.tom] : "text-foreground")}>
        {mval(m)}
        {m.meta != null && m.valor != null && (
          <span className="text-sm font-semibold text-muted-foreground/70">/{fmtValor(m.meta, m.formato)}</span>
        )}
      </div>
      <div className="mt-1 text-[10px] uppercase leading-tight tracking-wide text-muted-foreground">
        {m.rotulo}
      </div>
    </div>
  );
}

export function CentralPage() {
  const q = useApi<Payload>("/api/central");
  const d = q.data;
  // "exige ação" separado do informativo (Otávio 22/07): conta que ENTROU em
  // crítico é a 1ª ligação do dia — não pode ter o peso de uma oportunidade nova
  const acao = d?.mudancas.filter((m) => m.tom === "acao") ?? [];
  const resto = d?.mudancas.filter((m) => m.tom !== "acao") ?? [];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-2xl font-bold tracking-tight">Central</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          O cockpit da empresa: as prioridades da semana e o que mudou primeiro; abaixo, os números do
          mês, a saúde de cada área e de cada bundle, e as iniciativas de horizonte maior.
        </p>
      </header>

      {q.loading && <LoadingSkeleton rows={6} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && (
        <>
          {d.fontes_paradas.length > 0 && (
            <div className="flex items-start gap-2 rounded-xl border border-warning/40 bg-card p-4 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              <span>
                <b>Fonte de dados parada:</b> {d.fontes_paradas.slice(0, 3).join(" · ")} — diagnósticos
                podem estar desatualizados.{" "}
                <a href="/admin" className="text-primary hover:underline">ver Saúde das integrações</a>
              </span>
            </div>
          )}

          {/* 1. PRIORIDADES DA SEMANA — o impacto em R$ é a âncora visual */}
          {d.prioridades.length > 0 && (
            <SectionCard title="Prioridades da semana"
              subtitle="objetivos confirmados, em ordem de impacto estimado em R$ (pelo cenário conservador) · estimativas indicativas, não promessas">
              <div className="space-y-3">
                {d.prioridades.map((p, i) => (
                  <div key={p.titulo} className="overflow-hidden rounded-xl border border-border">
                    <div className="flex flex-wrap items-start gap-4 bg-muted/30 p-4">
                      <span className="font-display text-2xl font-bold leading-none text-muted-foreground/50">
                        {i + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="font-display text-base font-semibold leading-tight">{p.titulo}</div>
                        {p.racional && (
                          <p className="mt-1 text-sm text-muted-foreground">{p.racional}</p>
                        )}
                      </div>
                      {/* âncora de valor: número grande à direita, não um chip solto */}
                      <div className="shrink-0 text-right">
                        {p.impacto?.faixa ? (
                          <>
                            <div className="font-display text-lg font-bold tabular-nums leading-none text-primary">
                              {faixaBRL(p.impacto.faixa)}
                            </div>
                            <div className="mt-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                              em jogo por mês
                            </div>
                          </>
                        ) : (
                          // ausência de número não é ausência de item (Otávio 22/07)
                          <Badge variant="outline" className="text-muted-foreground">
                            impacto não estimado
                          </Badge>
                        )}
                      </div>
                    </div>
                    {p.impacto?.premissa && (
                      <details className="border-t border-border px-4 py-2">
                        <summary className="cursor-pointer text-xs text-primary">como estimamos o valor</summary>
                        <p className="mt-1 text-xs text-muted-foreground">{p.impacto.premissa}</p>
                      </details>
                    )}
                    {p.acoes.length > 0 && (
                      // ações por área legíveis de relance: rótulo da área à
                      // esquerda, manchete em negrito, detalhe abaixo
                      <div className="divide-y divide-border border-t border-border">
                        {p.acoes.map((a, j) => (
                          <div key={`${p.titulo}-${j}`}
                            className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
                            <span className="w-24 shrink-0 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                              {a.team_label}
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="font-medium leading-snug">{a.manchete}</div>
                              {a.detalhe && <div className="text-xs text-muted-foreground">{a.detalhe}</div>}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs">
                <a href="/semana" className="text-primary hover:underline">ver Ações da Semana →</a>
              </p>
            </SectionCard>
          )}

          {/* 2. O QUE MUDOU — exige ação primeiro, informativo depois */}
          {d.mudancas.length > 0 && (
            <SectionCard hint={<Hint area="growth/contas" titulo="Contas por risco" />}
              title="O que mudou desde ontem"
              subtitle="deltas das últimas 24h / última rodada — clique para abrir o recorte exato">
              {acao.length > 0 && (
                <div className="mb-3 space-y-1.5">
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-destructive">
                    exige ação
                  </div>
                  {acao.map((m) => (
                    <a key={m.texto} href={m.url}
                      className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/[0.06] p-3 text-sm hover:bg-destructive/10">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                      <span className="min-w-0 flex-1 font-medium">{m.texto}</span>
                      <ArrowUpRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                    </a>
                  ))}
                </div>
              )}
              {resto.length > 0 && (
                <div className="space-y-0">
                  {acao.length > 0 && (
                    <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                      informativo
                    </div>
                  )}
                  {resto.map((m) => (
                    <a key={m.texto} href={m.url}
                      className="flex items-start gap-2 border-t border-border py-2 text-sm text-muted-foreground first:border-t-0 hover:bg-muted/40">
                      <ArrowRight className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>{m.texto}</span>
                    </a>
                  ))}
                </div>
              )}
            </SectionCard>
          )}

          {/* 3. NÚMEROS-CHAVE DO MÊS */}
          <SectionCard title="Números-chave do mês"
            subtitle="retenção (Growth) e aquisição (Marketing/Vendas) — o termômetro rápido antes do detalhe por área">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
              {d.kpis.map((k) => (
                <div key={k.rotulo} className="rounded-xl border border-border bg-muted/20 p-4">
                  <Metric m={k} />
                </div>
              ))}
            </div>
          </SectionCard>

          {/* 4. SAÚDE POR ÁREA — pior primeiro (onde olhar agora) */}
          <SectionCard title="Saúde por área"
            subtitle="diagnóstico automático do mês corrente, da área que mais demanda atenção para a mais saudável — clique para abrir">
            <div className="grid gap-3 md:grid-cols-2">
              {d.saude.map((s) => (
                <a key={s.area} href={s.href}
                  className={cn("flex items-start gap-3 rounded-xl border p-3.5 hover:bg-muted/40",
                    s.pior ? "border-destructive/60 bg-destructive/[0.04]" : "border-border")}>
                  <span className={cn("mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full", NIVEL_DOT[s.nivel])} />
                  <div className="min-w-0">
                    <div className="font-display text-sm font-semibold">
                      {s.nome} · <span className={NIVEL_TXT[s.nivel]}>{s.nivel_label}</span>
                      {s.pior && (
                        <span className="ml-2 rounded-full border border-destructive px-2 py-0.5 text-[9px] uppercase tracking-wide text-destructive">
                          maior atenção agora
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 text-xs leading-snug text-muted-foreground">{s.motivo}</div>
                  </div>
                </a>
              ))}
            </div>
          </SectionCard>

          {/* 5. RAIO-X COMPACTO POR BUNDLE */}
          {d.bundles.length > 0 && (
            <SectionCard title="Raio-X compacto por bundle"
              subtitle="bookings × meta do mês (cor pelo ritmo) e churn precoce da coorte — os mesmos números do Raio-X completo">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                {d.bundles.map((b) => (
                  <a key={b.bundle} href={`/raiox?b=${b.bundle}`}
                    className={cn("rounded-xl border p-3.5 hover:bg-muted/40",
                      b.pior ? "border-destructive/60 bg-destructive/[0.04]" : "border-border")}>
                    <div className="flex items-baseline justify-between gap-1">
                      <b className="font-display text-sm">{b.bundle}</b>
                      {b.pior && (
                        <span className="text-[9px] uppercase tracking-wide text-destructive">
                          mais fora da meta
                        </span>
                      )}
                    </div>
                    <div className={cn("mt-1.5 font-display text-xl font-bold tabular-nums leading-none",
                      NIVEL_TXT[b.nivel])}>
                      {b.bookings}
                      {b.meta != null && (
                        <span className="text-sm font-semibold text-muted-foreground/70">
                          /{b.meta.toFixed(0)}
                        </span>
                      )}
                    </div>
                    <div className="mt-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                      bookings × meta
                    </div>
                    <div className="mt-1.5 text-xs text-muted-foreground">
                      {b.churn_precoce != null
                        ? `${(b.churn_precoce * 100).toFixed(0)}% churn precoce`
                        : "coorte pequena p/ churn"}
                    </div>
                  </a>
                ))}
              </div>
              <p className="mt-3 text-xs">
                <a href="/raiox" className="text-primary hover:underline">visão da empresa toda →</a>
              </p>
            </SectionCard>
          )}

          {/* 6. ÁREAS — cards COMPACTOS lado a lado (não seções grandes) */}
          <SectionCard title="Áreas"
            subtitle="resumo do andamento de cada área — clique para abrir o painel completo; verde = no ritmo da meta, vermelho = atenção">
            <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
              {d.areas.map((a) => (
                <a key={a.area} href={a.href}
                  className="flex flex-col rounded-xl border border-border p-4 hover:bg-muted/40">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-display text-sm font-semibold">{a.nome}</div>
                    <Badge className={cn("border-0 text-[10px] font-medium", NIVEL_BG[a.nivel])}>
                      {a.nivel_label}
                    </Badge>
                  </div>
                  {a.metricas.length > 0 && (
                    <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-3">
                      {a.metricas.map((m) => <Metric key={m.rotulo} m={m} />)}
                    </div>
                  )}
                  <div className="mt-3 text-xs leading-snug text-muted-foreground">{a.detalhe}</div>
                </a>
              ))}
            </div>
          </SectionCard>

          {/* 7. INICIATIVAS DE MAIOR HORIZONTE */}
          <SectionCard title="Iniciativas de maior horizonte"
            subtitle="gargalos medidos que NÃO viraram objetivo desta semana — ordenados pelo impacto estimado em R$/mês, com premissa e defasagem">
            {d.horizonte.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nenhuma iniciativa além das prioridades da semana — os gargalos atuais já viraram
                objetivos confirmados.
              </p>
            ) : (
              <div className="divide-y divide-border">
                {d.horizonte.map((h) => (
                  <a key={h.titulo} href={h.href}
                    className="flex items-start gap-3 py-3 first:pt-0 hover:bg-muted/40">
                    <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", NIVEL_DOT[h.nivel])} />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold">{h.titulo}</div>
                      <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{h.descricao}</div>
                      {h.faixa && (
                        <div className="mt-1 text-xs leading-relaxed text-muted-foreground">
                          <b className="text-primary">≈ {faixaBRL(h.faixa)}/mês em jogo</b> · potencial
                          estimado, não promessa · premissa: {h.premissa} · {h.defasagem}
                        </div>
                      )}
                      {!h.faixa && h.defasagem && (
                        <div className="mt-1 text-xs text-muted-foreground">{h.defasagem}</div>
                      )}
                    </div>
                    <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                  </a>
                ))}
              </div>
            )}
          </SectionCard>

          {/* 8. DEFASAGENS — referência de consulta, recolhida por padrão */}
          <details className="rounded-xl border border-border bg-card p-4 shadow-sm">
            <summary className="cursor-pointer font-display text-sm font-semibold">
              Defasagem esperada das correções{" "}
              <span className="text-xs font-normal text-muted-foreground">
                (referência — quando cobrar resultado)
              </span>
            </summary>
            <p className="mt-2 text-xs text-muted-foreground">
              medida no NOSSO histórico (medianas) — onde não há base, está dito
            </p>
            <div className="mt-2 divide-y divide-border">
              {d.defasagens.map((l) => (
                <div key={l.titulo} className="py-2">
                  <div className="text-sm font-medium">{l.titulo}</div>
                  <div className="text-xs text-muted-foreground">{l.texto}</div>
                </div>
              ))}
            </div>
          </details>
        </>
      )}
    </div>
  );
}
