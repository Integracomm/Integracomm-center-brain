import { Route, Routes, useSearchParams } from "react-router-dom";
import { ThemeToggle } from "@/components/theme-toggle";
import { BibliotecaPage } from "@/pages/biblioteca";
import { GrowthContasPage } from "@/pages/growth/contas";
import { GrowthAlertasPage } from "@/pages/growth/alertas";
import { GrowthCancelamentosPage } from "@/pages/growth/cancelamentos";
import { PrevendasPage } from "@/pages/prevendas";
import { MelhorHorarioPage } from "@/pages/prevendas/melhor-horario";
import { VendasWinLossPage } from "@/pages/vendas/winloss";
import { VendasFunilPage } from "@/pages/vendas/funil";
import { VendasPontePage } from "@/pages/vendas/ponte";
import { VendasCicloPage } from "@/pages/vendas/ciclo";
import { MktCanaisPage } from "@/pages/marketing/canais";
import { MktOrigensPage } from "@/pages/marketing/origens";
import { MktVisaoPage } from "@/pages/marketing/visao";
import { MktMetasPage } from "@/pages/marketing/metas";
import { MktFunilPage } from "@/pages/marketing/funil";
import { MktMidiaPage } from "@/pages/marketing/midia";
import { MktLagPage } from "@/pages/marketing/lag";
import { MktPlanejadorPage } from "@/pages/marketing/planejador";
import { MktCriativosPage } from "@/pages/marketing/criativos";
import { MktCicloVidaPage } from "@/pages/marketing/ciclo-vida";
import { FinanceiroVisaoPage } from "@/pages/financeiro/visao";
import { RaioXPage } from "@/pages/raiox";
import { SemanaPage } from "@/pages/semana";
import { FocoSemana } from "@/components/blocks/foco-semana";
import { RodapeFonte, UsuarioRail } from "@/components/blocks/rodape-fonte";
import { CentralPage } from "@/pages/central";

// A aplicação atual navega por QUERY (?view=) dentro de cada área — o SPA
// respeita as MESMAS URLs (favoritos/links continuam valendo). Views ainda
// não migradas de /growth (carga, playbooks, relatorios) seguem no HTML:
// o backend só entrega o SPA para as views listadas em spa.py.
const SPA_GROWTH_VIEWS = ["contas", "alertas", "cancelamentos"] as const;

// itens SEM o prefixo da área (Otávio 21/07: já estamos dentro dela) —
// o cabeçalho do grupo diz onde o usuário está
const NAV: Array<{ href: string; label: string; spa: boolean; grupo?: string }> = [
  { href: "/growth?view=contas", label: "Contas", spa: true, grupo: "Growth / Assessoria" },
  { href: "/growth?view=alertas", label: "Alertas", spa: true },
  { href: "/growth?view=cancelamentos", label: "Cancelamentos", spa: true },
  { href: "/growth?view=carga", label: "Análise dos Squads", spa: false },
  { href: "/growth?view=playbooks", label: "Playbooks", spa: false },
  { href: "/growth?view=relatorios", label: "Relatórios", spa: false },
  { href: "/marketing?view=visao", label: "Visão Geral", spa: true, grupo: "Marketing" },
  { href: "/marketing?view=metas", label: "Metas do Semestre", spa: true },
  { href: "/marketing?view=funil", label: "Funil de Prospecção", spa: true },
  { href: "/marketing?view=canais", label: "Ranking de Canais", spa: true },
  { href: "/marketing?view=origens", label: "Origem de Leads", spa: true },
  { href: "/marketing?view=midia", label: "Mídia Paga", spa: true },
  { href: "/marketing?view=lag", label: "Tempo até Resultado", spa: true },
  { href: "/marketing?view=planejador", label: "Planejador", spa: true },
  { href: "/marketing?view=criativos", label: "Criativos e Públicos", spa: true },
  { href: "/marketing?view=ciclo", label: "Ciclo de Vida", spa: true },
  { href: "/prevendas?view=funil", label: "Qualificação & Speed", spa: true, grupo: "Pré-vendas" },
  { href: "/prevendas?view=horarios", label: "Melhor Horário", spa: true },
  { href: "/prevendas?view=ponte", label: "Ponte PV → Vendas", spa: true },
  { href: "/prevendas?view=sdrs", label: "Desempenho Individual", spa: false },
  { href: "/vendas?view=funil", label: "Funil de Fechamento", spa: true, grupo: "Vendas" },
  { href: "/vendas?view=ponte", label: "Ponte PV → Vendas", spa: true },
  { href: "/vendas?view=winloss", label: "Win/Loss", spa: true },
  { href: "/vendas?view=ciclo", label: "Ciclo & Empacados", spa: true },
  { href: "/vendas?view=horarios", label: "Melhor Horário", spa: false },
  { href: "/vendas?view=closers", label: "Desempenho Individual", spa: false },
  { href: "/vendas?view=forecast", label: "Performance & Meta", spa: false },
  { href: "/financeiro?view=visao", label: "Planejamento x Realizado", spa: true, grupo: "Financeiro" },
  { href: "/financeiro?view=receita", label: "Receita Recorrente", spa: false },
  { href: "/app", label: "Biblioteca (vitrine)", spa: true, grupo: "Redesenho" },
];

// Nav da CENTRAL (/): as portas de entrada de cada área + visões transversais
const NAV_CENTRAL: Array<{ href: string; label: string; spa: boolean; grupo?: string }> = [
  { href: "/semana", label: "Ações da Semana", spa: true, grupo: "Visões transversais" },
  { href: "/raiox", label: "Raio-X por Bundle", spa: true },
  { href: "/growth?view=contas", label: "Growth / Assessoria", spa: true, grupo: "Áreas" },
  { href: "/marketing?view=visao", label: "Marketing", spa: true },
  { href: "/prevendas?view=funil", label: "Pré-vendas", spa: true },
  { href: "/vendas?view=funil", label: "Vendas", spa: true },
  { href: "/financeiro?view=visao", label: "Financeiro", spa: true },
  { href: "/operacoes", label: "Operações", spa: false },
  { href: "/admin", label: "Administrativo", spa: false, grupo: "Admin" },
  { href: "/allhands", label: "All Hands", spa: false },
];

function PrevendasRouter() {
  const [params] = useSearchParams();
  const view = params.get("view") ?? "funil";
  if (view === "horarios") return <MelhorHorarioPage />;
  if (view === "ponte") return <VendasPontePage />; // MESMA tela nas duas áreas (HTML idem)
  return <PrevendasPage />; // funil e speed viraram UMA página no redesenho
}

function MarketingRouter() {
  const [params] = useSearchParams();
  const view = params.get("view") ?? "visao";
  if (view === "origens") return <MktOrigensPage />;
  if (view === "canais") return <MktCanaisPage />;
  if (view === "metas") return <MktMetasPage />;
  if (view === "funil") return <MktFunilPage />;
  if (view === "midia") return <MktMidiaPage />;
  if (view === "lag") return <MktLagPage />;
  if (view === "planejador") return <MktPlanejadorPage />;
  if (view === "criativos") return <MktCriativosPage />;
  if (view === "ciclo") return <MktCicloVidaPage />;
  return <MktVisaoPage />; // view padrão da área (Lote 4: Marketing 100% no SPA)
}

function VendasRouter() {
  const [params] = useSearchParams();
  const view = params.get("view") ?? "funil";
  if (view === "winloss") return <VendasWinLossPage />;
  if (view === "ponte") return <VendasPontePage />;
  if (view === "ciclo") return <VendasCicloPage />;
  return <VendasFunilPage />; // view padrão da área (Lote 3)
}

function GrowthRouter() {
  const [params] = useSearchParams();
  const view = params.get("view") ?? "contas";
  if (view === "alertas") return <GrowthAlertasPage />;
  if (view === "cancelamentos") return <GrowthCancelamentosPage />;
  if (view === "contas" || !SPA_GROWTH_VIEWS.includes(view as never)) return <GrowthContasPage />;
  return <GrowthContasPage />;
}

function Shell({ children }: { children: React.ReactNode }) {
  const [params] = useSearchParams();
  // A nav mostra SÓ a área atual (feedback Otávio 21/07: dentro de Growth
  // apareciam também os itens de PV/Vendas — o painel sempre foi 1 nav por
  // área). A vitrine só aparece quando se está nela.
  const area = window.location.pathname;
  // A CENTRAL (/) é a porta de entrada do admin: em vez da nav de uma área,
  // lista as áreas + as visões transversais (o hub HTML fazia o mesmo).
  const itens = area === "/" ? NAV_CENTRAL
    : NAV.filter((n) => (area === "/app" ? n.href === "/app" : n.href.startsWith(`${area}?`)));
  const viewPadrao = area === "/prevendas" || area === "/vendas" ? "funil"
    : area === "/marketing" || area === "/financeiro" ? "visao" : "contas";
  const atual = `${area}?view=${params.get("view") ?? viewPadrao}`;
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-sidebar p-4">
        <div className="mb-6 flex items-center gap-2">
          <span className="inline-block h-6 w-6 rounded-full bg-primary" />
          <span className="font-display text-sm font-bold">Integracomm IA</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1">
          {itens.map((n) => {
            const ativa = n.spa && (n.href === atual || (n.href === "/app" && window.location.pathname === "/app"));
            const cab = n.grupo ? (
              <div key={`g-${n.grupo}`} className="mb-1 mt-4 px-3 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70 first:mt-0">
                {n.grupo}
              </div>
            ) : null;
            // âncora comum de propósito: views não-migradas precisam de request
            // ao servidor (HTML antigo); as migradas também funcionam via full
            // load — simplicidade > SPA-navigation no Lote 1
            return (
              <span key={n.href} className="contents">
              {cab}
              <a href={n.href}
                className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  ativa ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}>
                {n.label}{!n.spa && <span className="ml-1 text-[10px] text-muted-foreground/60">(HTML)</span>}
              </a>
              </span>
            );
          })}
          {area !== "/" && (
            <a href="/" className="rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
              ← Início (central)
            </a>
          )}
        </nav>
        <div className="space-y-2 border-t border-border pt-3">
          {/* e-mail da sessão + origem do dado — estavam no rail do HTML */}
          <UsuarioRail />
          <div className="flex items-center justify-between">
            <a href="/logout" className="text-xs text-muted-foreground hover:text-foreground">sair</a>
            <ThemeToggle />
          </div>
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-6 lg:p-8">
        {/* foco da semana do time da área — antes vinha do _shell HTML */}
        <FocoSemana pathname={area} />
        {children}
        {/* procedência do dado + defasagem — estava no rodapé do HTML */}
        <RodapeFonte pathname={area} />
      </main>
    </div>
  );
}

export function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/growth" element={<GrowthRouter />} />
        <Route path="/marketing" element={<MarketingRouter />} />
        <Route path="/financeiro" element={<FinanceiroVisaoPage />} />
        <Route path="/raiox" element={<RaioXPage />} />
        <Route path="/semana" element={<SemanaPage />} />
        <Route path="/" element={<CentralPage />} />
        <Route path="/prevendas" element={<PrevendasRouter />} />
        <Route path="/vendas" element={<VendasRouter />} />
        <Route path="/app" element={<BibliotecaPage />} />
        <Route path="*" element={<BibliotecaPage />} />
      </Routes>
    </Shell>
  );
}
