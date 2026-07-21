import { Route, Routes, useSearchParams } from "react-router-dom";
import { ThemeToggle } from "@/components/theme-toggle";
import { BibliotecaPage } from "@/pages/biblioteca";
import { GrowthContasPage } from "@/pages/growth/contas";
import { GrowthAlertasPage } from "@/pages/growth/alertas";
import { GrowthCancelamentosPage } from "@/pages/growth/cancelamentos";

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
  { href: "/app", label: "Biblioteca (vitrine)", spa: true, grupo: "Redesenho" },
];

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
  const atual = `${window.location.pathname}?view=${params.get("view") ?? "contas"}`;
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-sidebar p-4">
        <div className="mb-6 flex items-center gap-2">
          <span className="inline-block h-6 w-6 rounded-full bg-primary" />
          <span className="font-display text-sm font-bold">Integracomm IA</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map((n) => {
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
          <a href="/" className="rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
            ← Início (central)
          </a>
        </nav>
        <div className="flex items-center justify-between border-t border-border pt-3">
          <a href="/logout" className="text-xs text-muted-foreground hover:text-foreground">sair</a>
          <ThemeToggle />
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-6 lg:p-8">{children}</main>
    </div>
  );
}

export function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/growth" element={<GrowthRouter />} />
        <Route path="/app" element={<BibliotecaPage />} />
        <Route path="*" element={<BibliotecaPage />} />
      </Routes>
    </Shell>
  );
}
