import { useApi } from "@/hooks/use-api";

// "Seu foco desta semana" no topo da ÁREA — o gestor vê o foco do próprio
// time sem abrir a central. REGRESSÃO 22/07: este banner era injetado pelo
// _shell HTML de cada área; quando a view passou a ser servida pelo SPA, o
// shell deixou de rodar e o foco sumiu das áreas migradas. Agora vive no
// shell do SPA e vale para TODAS as áreas de uma vez.

interface Foco {
  team: string; team_label: string | null;
  acoes: Array<{ manchete: string; detalhe: string; lag: string | null;
    objetivo: string | null; links: Array<{ url: string; label: string }> }>;
}

// pathname -> time (mesmo mapa do _shell antigo, + growth que vinha do api.py)
const TIME_DA_ROTA: Record<string, string> = {
  "/marketing": "marketing",
  "/prevendas": "prevendas",
  "/vendas": "vendas",
  "/growth": "growth",
};

export function FocoSemana({ pathname }: { pathname: string }) {
  const team = TIME_DA_ROTA[pathname];
  // hook sempre chamado (regra dos hooks); sem time, a URL vazia não busca
  const q = useApi<Foco>(team ? `/api/semana/foco?team=${team}` : "");
  if (!team || !q.data?.acoes.length) return null;
  return (
    <div className="mb-6 rounded-xl border border-border bg-card p-4">
      <div className="text-[10px] font-semibold uppercase tracking-widest text-primary">
        Seu foco desta semana{" "}
        <a href="/semana" className="font-normal normal-case tracking-normal text-muted-foreground hover:underline">
          · ver Ações da Semana →
        </a>
      </div>
      {q.data.acoes.map((a, i) => (
        <div key={i} className="pt-1.5 text-sm leading-relaxed">
          → <b>{a.manchete}</b>
          {a.detalhe && <span className="text-xs text-muted-foreground"> — {a.detalhe}</span>}
          {a.lag && <span className="text-[10px] text-muted-foreground/70"> ({a.lag})</span>}
          {a.links.map((l) => (
            <a key={l.url} href={l.url} className="ml-2 text-[11px] text-primary hover:underline">
              {l.label} →
            </a>
          ))}
        </div>
      ))}
    </div>
  );
}
