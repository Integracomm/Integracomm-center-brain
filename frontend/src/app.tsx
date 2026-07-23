import { Route, Routes, useSearchParams } from "react-router-dom";
import { ThemeToggle } from "@/components/theme-toggle";
import { BibliotecaPage } from "@/pages/biblioteca";
import { GrowthContasPage } from "@/pages/growth/contas";
import { GrowthAlertasPage } from "@/pages/growth/alertas";
import { GrowthCancelamentosPage } from "@/pages/growth/cancelamentos";
import { GrowthPlaybooksPage } from "@/pages/growth/playbooks";
import { GrowthSquadsPage } from "@/pages/growth/squads";
import { GrowthRelatoriosPage } from "@/pages/growth/relatorios";
import { PrevendasPage } from "@/pages/prevendas";
import { MelhorHorarioPage } from "@/pages/prevendas/melhor-horario";
import { PrevendasSdrsPage } from "@/pages/prevendas/sdrs";
import { VendasWinLossPage } from "@/pages/vendas/winloss";
import { VendasFunilPage } from "@/pages/vendas/funil";
import { VendasPontePage } from "@/pages/vendas/ponte";
import { VendasCicloPage } from "@/pages/vendas/ciclo";
import { VendasClosersPage } from "@/pages/vendas/closers";
import { VendasForecastPage } from "@/pages/vendas/forecast";
import { VendasHorariosPage } from "@/pages/vendas/horarios";
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
import { FinanceiroReceitaPage } from "@/pages/financeiro/receita";
import { OperacoesVisaoPage } from "@/pages/operacoes/visao";
import { OperacoesAreaPage } from "@/pages/operacoes/area";
import { OperacoesConfigPage } from "@/pages/operacoes/config";
import { SLUGS as OP_SLUGS } from "@/pages/operacoes/comum";
import { RaioXPage } from "@/pages/raiox";
import { SemanaPage } from "@/pages/semana";
import { FocoSemana } from "@/components/blocks/foco-semana";
import { RodapeFonte, UsuarioRail } from "@/components/blocks/rodape-fonte";
import { CentralPage } from "@/pages/central";
import { HomePage, type HomePayload } from "@/pages/home";
import { useApi } from "@/hooks/use-api";

// A aplicação atual navega por QUERY (?view=) dentro de cada área — o SPA
// respeita as MESMAS URLs (favoritos/links continuam valendo). Views ainda
// não migradas de /growth (carga, playbooks, relatorios) seguem no HTML:
// o backend só entrega o SPA para as views listadas em spa.py.
const SPA_GROWTH_VIEWS = ["contas", "alertas", "cancelamentos", "playbooks",
  "relatorios", "carga"] as const;

// itens SEM o prefixo da área (Otávio 21/07: já estamos dentro dela) —
// o cabeçalho do grupo diz onde o usuário está
type ItemNav = { href: string; label: string; spa: boolean; grupo?: string; selo?: number };

const NAV: Array<ItemNav> = [
  { href: "/growth?view=contas", label: "Contas", spa: true, grupo: "Growth / Assessoria" },
  { href: "/growth?view=alertas", label: "Alertas", spa: true },
  { href: "/growth?view=cancelamentos", label: "Cancelamentos", spa: true },
  { href: "/growth?view=carga", label: "Análise dos Squads", spa: true },
  { href: "/growth?view=playbooks", label: "Playbooks", spa: true },
  { href: "/growth?view=relatorios", label: "Relatórios", spa: true },
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
  { href: "/prevendas?view=sdrs", label: "Desempenho Individual", spa: true },
  { href: "/vendas?view=funil", label: "Funil de Fechamento", spa: true, grupo: "Vendas" },
  { href: "/vendas?view=ponte", label: "Ponte PV → Vendas", spa: true },
  { href: "/vendas?view=winloss", label: "Win/Loss", spa: true },
  { href: "/vendas?view=ciclo", label: "Ciclo & Empacados", spa: true },
  { href: "/vendas?view=horarios", label: "Melhor Horário", spa: true },
  { href: "/vendas?view=closers", label: "Desempenho Individual", spa: true },
  { href: "/vendas?view=forecast", label: "Performance & Meta", spa: true },
  { href: "/financeiro?view=visao", label: "Planejamento x Realizado", spa: true, grupo: "Financeiro" },
  { href: "/financeiro?view=receita", label: "Receita Recorrente", spa: true },
  { href: "/operacoes?view=visao", label: "Visão Geral", spa: true, grupo: "Operações" },
  { href: "/operacoes?view=financeiro", label: "Financeiro", spa: true },
  { href: "/operacoes?view=comercial", label: "Comercial", spa: true },
  { href: "/operacoes?view=assessoria", label: "Assessoria", spa: true },
  { href: "/operacoes?view=marketing", label: "Marketing", spa: true },
  { href: "/operacoes?view=rh", label: "RH", spa: true },
  { href: "/operacoes?view=growth", label: "Growth", spa: true },
  { href: "/operacoes?view=config", label: "Configurações", spa: true },
  { href: "/app", label: "Biblioteca (vitrine)", spa: true, grupo: "Redesenho" },
];

function PrevendasRouter() {
  const [params] = useSearchParams();
  const view = params.get("view") ?? "funil";
  if (view === "horarios") return <MelhorHorarioPage />;
  if (view === "ponte") return <VendasPontePage />; // MESMA tela nas duas áreas (HTML idem)
  if (view === "sdrs") return <PrevendasSdrsPage />;
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
  if (view === "closers") return <VendasClosersPage />;
  // NÃO é a mesma tela de PV, apesar do nome (Otávio 23/07): lá a pergunta é
  // quando o lead ATENDE; aqui é em que horário a REUNIÃO fecha
  if (view === "horarios") return <VendasHorariosPage />;
  if (view === "forecast") return <VendasForecastPage />;
  return <VendasFunilPage />; // view padrão da área (Lote 3)
}

function FinanceiroRouter() {
  const [params] = useSearchParams();
  const view = params.get("view") ?? "visao";
  if (view === "receita") return <FinanceiroReceitaPage />;
  return <FinanceiroVisaoPage />; // visao = view padrão da área
}

function OperacoesRouter() {
  const [params] = useSearchParams();
  const view = params.get("view") ?? "visao";
  if (view === "config") return <OperacoesConfigPage />;
  if ((OP_SLUGS as readonly string[]).includes(view)) return <OperacoesAreaPage />;
  return <OperacoesVisaoPage />; // visao = view padrão da área
}

function GrowthRouter() {
  const [params] = useSearchParams();
  const view = params.get("view") ?? "contas";
  if (view === "alertas") return <GrowthAlertasPage />;
  if (view === "cancelamentos") return <GrowthCancelamentosPage />;
  if (view === "carga") return <GrowthSquadsPage />;
  if (view === "playbooks") return <GrowthPlaybooksPage />;
  if (view === "relatorios") return <GrowthRelatoriosPage />;
  if (view === "contas" || !SPA_GROWTH_VIEWS.includes(view as never)) return <GrowthContasPage />;
  return <GrowthContasPage />;
}

function Shell({ children }: { children: React.ReactNode }) {
  const [params] = useSearchParams();
  // A nav mostra SÓ a área atual (feedback Otávio 21/07: dentro de Growth
  // apareciam também os itens de PV/Vendas — o painel sempre foi 1 nav por
  // área). A vitrine só aparece quando se está nela.
  const area = window.location.pathname;
  // HOME ÚNICA (/) e CENTRAL (/central): a nav mostra SÓ o que ESTA pessoa
  // acessa — as áreas dela + as visões da empresa (+ Admin, se for admin). Vem
  // de /api/home, que deriva das áreas liberadas para a conta; nada é fixo por
  // papel (Otávio 22/07). A Central usa a MESMA nav: com a lista fixa antiga
  // (NAV_CENTRAL) ela "voltava no tempo" ao ser aberta — sem o item Início e
  // com Ações da Semana nas Visões da empresa, de onde já tinha saído.
  // Visões da empresa (/semana, /raiox) usam a nav GERAL, como a home e a
  // Central: elas não são áreas e não têm ?view=, então o filtro por
  // `href.startsWith("/semana?")` devolvia lista vazia e o sidebar sumia
  // (Otávio 23/07).
  const comNavGeral = ["/", "/central", "/semana", "/raiox"].includes(area);
  const home = useApi<HomePayload>(comNavGeral ? "/api/home" : "");
  const navHome: Array<ItemNav> = [
    { href: "/", label: "Início", spa: true },
    ...(home.data?.areas ?? []).map((a, i) => ({
      href: a.href, label: a.nome, spa: true, grupo: i === 0 ? "Áreas" : undefined })),
    ...(home.data?.visoes ?? []).map((v, i) => ({
      href: v.href, label: v.nome, spa: true, grupo: i === 0 ? "Visões da empresa" : undefined })),
    ...(home.data?.admin ?? []).map((a, i) => ({
      href: a.href, label: a.nome, spa: a.slug === "central" || a.slug === "semana",
      grupo: i === 0 ? "Admin" : undefined, selo: a.pendencias })),
  ];
  const itens = comNavGeral ? navHome
    : NAV.filter((n) => (area === "/app" ? n.href === "/app" : n.href.startsWith(`${area}?`)));
  const viewPadrao = area === "/prevendas" || area === "/vendas" ? "funil"
    : area === "/marketing" || area === "/financeiro" || area === "/operacoes" ? "visao" : "contas";
  const viewAtual = params.get("view") ?? viewPadrao;
  // Marcador de "onde estou" (Otávio 22/07): compara ROTA + view, e vale
  // também para as páginas ainda em HTML — antes só item do SPA acendia, e a
  // Central (/) nunca acendia porque comparava contra "/?view=…".
  const ehAtiva = (href: string) => {
    const [rota, qs] = href.split("?");
    if (rota !== area) return false;
    const v = new URLSearchParams(qs ?? "").get("view");
    return v ? v === viewAtual : true;
  };
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-sidebar p-4">
        {/* a MARCA da Integracomm no lugar do circulo azul generico (Otávio
            22/07) — mesmo arquivo do favicon; o miolo entre os dois circulos é
            vazado, então serve em tema claro e escuro */}
        <a href="/" className="mb-6 flex items-center gap-2">
          <img src="/spa/favicon.png" alt="" className="h-6 w-6 shrink-0" />
          <span className="font-display text-sm font-bold">Integracomm IA</span>
        </a>
        {/* itens COLADOS dentro do grupo e respiro MAIOR entre grupos (Otávio
            22/07, 2ª volta). O `first:mt-0` de antes NUNCA funcionava: cada par
            cabeçalho+item mora num <span class=contents>, então TODO cabeçalho
            era :first-child do seu span e ficava sem margem — a distância entre
            irmãos acabava maior que a distância entre blocos. Agora o respiro é
            decidido pelo ÍNDICE, e o rótulo do grupo tem cor própria. */}
        <nav className="flex flex-1 flex-col">
          {itens.map((n, i) => {
            const ativa = ehAtiva(n.href);
            const cab = n.grupo ? (
              <div key={`g-${n.grupo}`}
                className={`mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-widest text-primary/75 ${
                  i === 0 ? "" : "mt-8"
                }`}>
                {n.grupo}
              </div>
            ) : null;
            // âncora comum de propósito: views não-migradas precisam de request
            // ao servidor (HTML antigo); as migradas também funcionam via full
            // load — simplicidade > SPA-navigation no Lote 1
            return (
              <span key={n.href} className="contents">
              {cab}
              <a href={n.href} aria-current={ativa ? "page" : undefined}
                className={`rounded-lg py-1.5 pl-3 pr-3 text-sm font-medium transition-colors ${
                  ativa
                    // acento dourado à esquerda, como no painel HTML
                    ? "border-l-2 border-primary bg-primary/10 pl-[10px] text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}>
                {n.label}{!n.spa && <span className="ml-1 text-[10px] text-muted-foreground/60">(HTML)</span>}
                {/* pendências do admin (pedido de senha, cadastro a aprovar):
                    sem aviso no grupo do Slack, é aqui que ele fica sabendo */}
                {!!n.selo && (
                  <span className="ml-1.5 rounded-full bg-destructive px-1.5 py-0.5 text-[10px] font-bold text-destructive-foreground">
                    {n.selo}
                  </span>
                )}
              </a>
              </span>
            );
          })}
          {!comNavGeral && (
            <a href="/" className="mt-9 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
              ← Início
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
        <Route path="/financeiro" element={<FinanceiroRouter />} />
        <Route path="/operacoes" element={<OperacoesRouter />} />
        <Route path="/raiox" element={<RaioXPage />} />
        <Route path="/semana" element={<SemanaPage />} />
        <Route path="/" element={<HomePage />} />
        <Route path="/central" element={<CentralPage />} />
        <Route path="/prevendas" element={<PrevendasRouter />} />
        <Route path="/vendas" element={<VendasRouter />} />
        <Route path="/app" element={<BibliotecaPage />} />
        <Route path="*" element={<BibliotecaPage />} />
      </Routes>
    </Shell>
  );
}
