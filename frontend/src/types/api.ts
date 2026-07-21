// Tipos dos payloads REAIS da API (docs/api-contract + endpoints do Lote 1).
// Regra do redesenho: agregados vêm prontos do backend; o frontend só formata.

export type RiskBand = "alto" | "medio" | "baixo" | "sem_dados";
export type Severity = "critico" | "alto" | "atencao";
export type Stage =
  | "saudavel"
  | "insatisfacao_latente"
  | "desengajamento_inicial"
  | "insatisfacao_ativa"
  | "intencao_de_saida";

export interface ScoreReason {
  text: string;
  leading: boolean;
  weight: number;
}

export interface Score {
  id: string;
  account_id: string;
  name: string;
  score: number;
  risk_band: RiskBand;
  stage: Stage;
  trajectory: string;
  confidence: number;
  coverage_weeks: number;
  evaluable: boolean;
  recommendation: string;
  computed_at: string;
  recurring_revenue: number | null;
  is_legacy: boolean;
  exec_score: number | null;
  exec_motivo: string | null;
  alert_sev: Severity | null;
  reasons: ScoreReason[];
  squad: string | null;
  responsavel: string | null;
  atrasadas: number | null;
  clickup_inativo: string | null;
}

export interface ScoresKpis {
  monitoradas: number;
  avaliaveis: number;
  criticos: number;
  mrr_em_risco: number;
  mrr_em_risco_contas: number;
  mrr_em_risco_sem_dados: number;
  sem_cobertura: number;
}

export interface ScoresEnvelope {
  agents: string[];
  scores: Score[];
  kpis: ScoresKpis;
}

export interface Alert {
  id: string;
  name: string;
  severity: Severity;
  risk_band: RiskBand;
  stage: Stage;
  created_at: string;
  status: string;
  notes: string | null;
  case_note: string | null;
  case_note_at: string | null;
  case_note_by: string | null;
}

export interface AlertsEnvelope {
  alerts: Alert[];
}

// ---- /api/growth/cancelamentos (Lote 1) ----
export interface CancTaxaBundle {
  bundle: string;
  recorrente: boolean;
  base_atual: number;
  saidas: number;
  janela_meses: number;
  mrr_perdido: number;
  mrr_base: number | null;
  mrr_base_estimado: boolean;
  mrr_base_com_valor: number;
  taxa_clientes_pct: number | null;
  taxa_faturamento_pct: number | null;
  aviso: string | null;
}

export interface CancelamentosPayload {
  periodo: { ini: string; fim: string };
  meses_disponiveis: string[];
  kpis: {
    saidas_mes: number;
    mrr_perdido_mes: number;
    em_tratativa: number;
    revertidos: number;
    tempo_casa_mediano: number | null;
    tempo_casa_n: number;
  };
  por_mes: Array<{
    mes: string;
    mes_label: string;
    saidas: number;
    mrr_perdido: number;
    saidas_novos: number;
    saidas_antigos: number;
    ticket_medio: number | null;
    tempo_casa_mediano: number | null;
    terminos_start: number;
  }>;
  taxa_bundle: CancTaxaBundle[];
  taxa_geral: CancTaxaBundle;
  motivos: Array<{ motivo: string; saidas: number }>;
  sem_motivo: number;
  casos_com_motivo: Array<{ mes: string; cliente: string; plano: string | null; motivo: string }>;
  tratativas: Array<{ cliente: string; gc: string | null; plano: string | null; situacao: string }>;
  por_plano: Array<{ nome: string; saidas: number; mrr_perdido: number; tempo_casa_mediano: number | null }>;
  por_equipe: Array<{ nome: string; saidas: number; mrr_perdido: number; tempo_casa_mediano: number | null }>;
}
