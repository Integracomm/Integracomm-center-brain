import { NavLink, Route, Routes } from "react-router-dom";
import { ThemeToggle } from "@/components/theme-toggle";
import { BibliotecaPage } from "@/pages/biblioteca";

// Áreas do produto — mesmas rotas do painel atual. Durante a migração, cada
// rota só é atendida pelo SPA quando o backend a chaveia (app/spa.py);
// as demais seguem no HTML server-side. `/app` é a vitrine do Lote 0.
const NAV = [
  { to: "/app", label: "Biblioteca (Lote 0)" },
  // as telas migradas entram aqui lote a lote:
  // { to: "/growth", label: "Growth / Assessoria" }, …
];

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-sidebar p-4">
        <div className="mb-6 flex items-center gap-2">
          <span className="inline-block h-6 w-6 rounded-full bg-primary" />
          <span className="font-display text-sm font-bold">Integracomm IA</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
          <a
            href="/"
            className="rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            ← Painel atual (HTML)
          </a>
        </nav>
        <div className="flex items-center justify-between border-t border-border pt-3">
          <a href="/logout" className="text-xs text-muted-foreground hover:text-foreground">
            sair
          </a>
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
        <Route path="/app" element={<BibliotecaPage />} />
        <Route path="*" element={<BibliotecaPage />} />
      </Routes>
    </Shell>
  );
}
