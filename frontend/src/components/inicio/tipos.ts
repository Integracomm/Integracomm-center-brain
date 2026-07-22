// Tipos do payload de /api/central — a Central nova (redesenho 22/07) consome o
// MESMO endpoint da anterior. Ele já embrulha as funções puras compartilhadas
// com a tela HTML (_hub_saude, _hub_kpis, _hub_area_cards, _hub_horizonte,
// raiox.mini_cards_dados), então o redesenho é só de LAYOUT: nenhum número
// muda de régua ao trocar a hierarquia visual.

export interface Metrica {
  rotulo: string; valor: number | null; formato: string;
  meta: number | null; tom: string | null; texto: string | null;
}
export interface Impacto { faixa: [number, number] | null; janela: string | null; premissa: string }
export interface Prioridade {
  titulo: string; racional: string | null; metric: string | null;
  target: number | null; impacto: Impacto | null;
  acoes: Array<{ team: string; team_label: string; manchete: string; detalhe: string }>;
}
export interface CentralPayload {
  stats: { monitored: number; evaluable: number; sev: Record<string, number>;
    mrr_risk: number; mrr_crit: number; non_eval: number };
  kpis: Metrica[];
  saude: Array<{ area: string; nome: string; href: string; nivel: string;
    nivel_label: string; motivo: string; pior: boolean }>;
  bundles: Array<{ bundle: string; meta: number | null; bookings: number;
    churn_precoce: number | null; ratio: number | null; nivel: string;
    pior: boolean; aviso: string | null }>;
  bundles_nota: string;
  areas: Array<{ area: string; nome: string; href: string; nivel: string;
    nivel_label: string; metricas: Metrica[]; detalhe: string }>;
  horizonte: Array<{ titulo: string; descricao: string; nivel: string; href: string;
    faixa: [number, number] | null; premissa: string | null; defasagem: string | null }>;
  defasagens: Array<{ titulo: string; texto: string }>;
  mudancas: Array<{ texto: string; url: string; tom: string }>;
  fontes_paradas: string[];
  prioridades: Prioridade[];
}

// ---- paleta compartilhada pelos blocos (cor SEMPRE com rótulo) -------------
export const NIVEL_TXT: Record<string, string> = {
  verde: "text-success", baixo: "text-success", medio: "text-warning",
  alto: "text-warning", critico: "text-destructive", semdados: "text-muted-foreground",
};
export const NIVEL_BG: Record<string, string> = {
  verde: "bg-success/15 text-success", baixo: "bg-success/15 text-success",
  medio: "bg-warning/15 text-warning", alto: "bg-warning/15 text-warning",
  critico: "bg-destructive/15 text-destructive",
  semdados: "bg-muted text-muted-foreground",
};
export const NIVEL_DOT: Record<string, string> = {
  verde: "bg-success", baixo: "bg-success", medio: "bg-warning",
  alto: "bg-warning", critico: "bg-destructive", semdados: "bg-muted-foreground",
};
export const NIVEL_BORDA: Record<string, string> = {
  verde: "border-l-success", baixo: "border-l-success", medio: "border-l-warning",
  alto: "border-l-warning", critico: "border-l-destructive",
  semdados: "border-l-muted-foreground",
};
