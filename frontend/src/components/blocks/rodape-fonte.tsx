import { useApi } from "@/hooks/use-api";

// Rodapé de FONTE da área (de onde vem o dado e qual a defasagem) + e-mail da
// sessão no rail. REGRESSÃO 22/07 (irmã do banner de foco): esses textos
// viviam inline em cada handler HTML e sumiram nas telas migradas. Agora vêm
// da fonte única (help_texts.RODAPES) via /api/rodape, servindo HTML e SPA.

interface Rodape {
  usuario: string; coleta: string; rodapes: Record<string, string>;
}

// pathname -> chave da área em RODAPES
const AREA_DA_ROTA: Record<string, string> = {
  "/growth": "growth",
  "/marketing": "marketing",
  "/prevendas": "prevendas",
  "/vendas": "vendas",
  "/financeiro": "financeiro",
  "/raiox": "raiox",
  "/semana": "semana",
};

export function useRodape() {
  return useApi<Rodape>("/api/rodape");
}

export function RodapeFonte({ pathname }: { pathname: string }) {
  const q = useRodape();
  const texto = q.data?.rodapes[AREA_DA_ROTA[pathname] ?? ""];
  if (!texto) return null;
  return <p className="mt-8 text-xs text-muted-foreground/70">{texto}</p>;
}

export function UsuarioRail() {
  const q = useRodape();
  if (!q.data) return null;
  return (
    <div className="text-[10px] leading-relaxed text-muted-foreground">
      <b className="text-muted-foreground">{q.data.usuario}</b>
      <br />
      {q.data.coleta}
    </div>
  );
}
