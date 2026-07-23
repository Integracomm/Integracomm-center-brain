import { AlertTriangle } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { PrioridadesSemana } from "@/components/inicio/prioridades-semana";
import { MudouDesdeOntem } from "@/components/inicio/mudou-desde-ontem";
import { KpisMes } from "@/components/inicio/kpis-mes";
import { SaudePorArea } from "@/components/inicio/saude-por-area";
import { RaioXBundle } from "@/components/inicio/raio-x-bundle";
import { AndamentoAreas } from "@/components/inicio/andamento-areas";
import { IniciativasHorizonte } from "@/components/inicio/iniciativas-horizonte";
import { BlocoRetratil } from "@/components/inicio/bloco-retratil";
import type { CentralPayload } from "@/components/inicio/tipos";

// CENTRAL (hub do admin) — redesenho 22/07.
//
// O que mudou: só a HIERARQUIA VISUAL. O layout anterior tinha tudo com o mesmo
// peso (parede de texto); agora vale DENSIDADE DECRESCENTE — as prioridades da
// semana dominam o topo em cards escaneáveis, e o detalhe desce em camadas de
// peso menor até as iniciativas de horizonte, recolhidas.
//
// O que NÃO mudou: os dados. Tudo vem de /api/central, que embrulha as mesmas
// funções puras da tela HTML (_hub_saude, _hub_kpis, _hub_area_cards,
// _hub_horizonte, _hub_defasagem_linhas, raiox.mini_cards_dados). Trocar o
// layout não pode mexer em régua — e o check de paridade confirma isso.

// Cabeçalho de seção. Todos os títulos com o MESMO tamanho (Otávio 23/07: os
// de Raio-X e Andamento pareciam menores que os outros) — a densidade
// decrescente fica por conta do conteúdo e dos blocos recolhidos no fim, não
// de encolher o título.
function Secao({ titulo, sub, hint, children }: {
  titulo: string; sub?: string; hint?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section>
      <div className="mb-3">
        <h2 className="font-display inline-flex items-center gap-1.5 text-base font-semibold">
          {titulo}{hint}
        </h2>
        {sub && <p className="mt-0.5 max-w-4xl text-xs leading-relaxed text-muted-foreground">{sub}</p>}
      </div>
      {children}
    </section>
  );
}

export function CentralPage() {
  const q = useApi<CentralPayload>("/api/central");
  const d = q.data;

  return (
    <div className="space-y-8">
      <header>
        <h1 className="font-display text-2xl font-bold tracking-tight">Central</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          O cockpit da empresa: as prioridades da semana primeiro; abaixo, em ordem de detalhe, o que
          mudou, os números do mês, a saúde de cada área e de cada bundle, e as iniciativas de
          horizonte maior.
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

          {/* 1 · PRIORIDADES — o topo, em cards */}
          {d.prioridades.length > 0 && (
            <Secao titulo="Prioridades da semana"
              sub="objetivos confirmados, em ordem de impacto estimado em R$ (pelo cenário conservador) · estimativas indicativas, não promessas — a premissa de cada valor está no ⓘ do chip">
              <PrioridadesSemana itens={d.prioridades} />
              <p className="mt-3 text-xs">
                <a href="/semana" className="text-primary hover:underline">ver Ações da Semana →</a>
              </p>
            </Secao>
          )}

          {/* 2 · O QUE MUDOU */}
          {d.mudancas.length > 0 && (
            <Secao titulo="O que mudou desde ontem"
              hint={<Hint area="growth/contas" titulo="Contas por risco" />}
              sub="deltas das últimas 24h / última rodada — clique para abrir o recorte exato">
              <MudouDesdeOntem itens={d.mudancas} />
            </Secao>
          )}

          {/* 3 · NÚMEROS-CHAVE */}
          <Secao titulo="Números-chave do mês"
            sub="retenção (Growth) e aquisição (Marketing/Vendas) — o termômetro rápido antes do detalhe por área">
            <KpisMes kpis={d.kpis} />
          </Secao>

          {/* 4 · SAÚDE POR ÁREA */}
          <Secao titulo="Saúde por área"
            sub="diagnóstico automático do mês corrente, da área que mais demanda atenção para a mais saudável">
            <SaudePorArea itens={d.saude} />
          </Secao>

          {/* 5 · RAIO-X POR BUNDLE */}
          {d.bundles.length > 0 && (
            <Secao titulo="Raio-X compacto por bundle"
              sub="bookings × meta do mês e churn precoce da coorte — os mesmos números do Raio-X completo">
              <RaioXBundle itens={d.bundles} nota={d.bundles_nota} />
              <p className="mt-3 text-xs">
                <a href="/raiox" className="text-primary hover:underline">visão da empresa toda →</a>
              </p>
            </Secao>
          )}

          {/* 6 · ANDAMENTO DAS ÁREAS */}
          <Secao titulo="Andamento das áreas"
            sub="resumo de cada área — clique para abrir o painel completo; verde = no ritmo da meta, vermelho = atenção">
            <AndamentoAreas itens={d.areas} />
          </Secao>

          {/* 7 · HORIZONTE — recolhido */}
          <IniciativasHorizonte itens={d.horizonte} />

          {/* 8 · DEFASAGENS — referência, recolhida (mesmo molde do bloco acima) */}
          <BlocoRetratil
            titulo="Defasagem esperada das correções"
            contagem={d.defasagens.length}
            sub="referência de quando cobrar resultado · medida no NOSSO histórico (medianas) — onde não há base, está dito">
            <ul className="divide-y divide-border">
              {d.defasagens.map((l) => (
                <li key={l.titulo} className="px-5 py-3">
                  <div className="text-sm font-medium">{l.titulo}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{l.texto}</div>
                </li>
              ))}
            </ul>
          </BlocoRetratil>
        </>
      )}
    </div>
  );
}
