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


// ---- Lote 2: /api/prevendas ----
export interface PrevendasPayload {
  periodo: { ini: string; fim: string };
  funil: {
    etapas: Array<{ key: string; label: string; volume: number; conversao_da_anterior_pct: number | null }>;
    conversao_total_pct: number | null;
    receita_bookings: number | null;
  };
  kpis: {
    leads: number; sql: number; taxa_lead_sql_pct: number | null;
    speed_mediano_min: number | null; pct_15min: number | null;
    p75_min: number | null; sem_contato: number;
  };
  dias: Array<{ dia: number; dia_label: string; leads: number; agendaram: number;
    taxa_pct: number | null; best: boolean; worst: boolean }>;
  origens: Array<{ origem: string; leads: number; reunioes: number; taxa_pct: number; amostra_pequena: boolean }>;
  desq: Array<{ motivo: string; deals: number }>;
  sem_motivo_desq: number;
  velocidade: {
    faixas: Array<{ faixa: string; ordem: string; leads: number; agendaram: number; taxa_pct: number | null }>;
    razao_15min_vs_24h: number | null;
  };
  tipos_contato: Array<{ tipo: string; leads: number; agendaram: number; taxa_pct: number | null }>;
  por_responsavel: Array<{ nome: string; leads: number; mediana_min: number; pct_15min: number }>;
  por_origem_speed: Array<{ nome: string; leads: number; mediana_min: number; pct_15min: number }>;
  tem_first_touch: boolean;
  evolucao: Array<{ mes: string; leads: number; sql: number; taxa_pct: number | null; speed_min: number | null }>;
  diagnostico: { persona: string; itens: string[] };
}

// ---- Lote 2: /api/vendas/winloss ----
export interface WinLossPayload {
  periodo: { ini: string; fim: string };
  kpis: { deals_perdidos: number; mrr_perdido: number; motivo_top: string | null };
  motivos_perda: Array<{ motivo: string; deals: number; mrr_perdido: number | null }>;
  sem_motivo: number;
  por_bundle: Array<{ bundle: string; perdas: number; mrr_perdido: number;
    motivos: Array<{ motivo: string; deals: number; mrr: number | null; pct: number }>;
    outros_motivos: number }>;
  heatmap_origem_x_motivo: { rows: string[]; cols: string[];
    cells: Array<{ row: string; col: string; col_full?: string; value: number | null; n?: number; amostra_pequena?: boolean }>; unit: string };
  heatmap_closer_x_motivo: { rows: string[]; cols: string[];
    cells: Array<{ row: string; col: string; col_full?: string; value: number | null; n?: number; amostra_pequena?: boolean }>; unit: string };
  evolucao: { meses: string[]; series: Array<{ motivo: string; valores: number[] }> };
  diagnostico: { motivo: string; deals: number; leitura: string;
    concentracao: string | null; fonte: string } | null;
}

// ---- Lote 2: /api/prevendas/horarios ----
export interface HorariosPayload {
  periodo: { ini: string; fim: string; bundle: string };
  total: number;
  celulas: Array<{ dow: number; hora: number; n: number }>;
  celulas_taxa: Array<{ dow: number; hora: number; n: number }>;
  agend_sem_ligacao: number;
  ligacoes: Array<{ dow: number; hora: number; n: number }>;
  taxa_ini: string | null;
  por_bundle: Record<string, Array<{ dow: number; hora: number; n: number }>>;
  por_origem: Record<string, Array<{ dow: number; hora: number; n: number }>>;
  por_colab: Record<string, Array<{ hora: number; n: number }>>;
}

// ---- Lote 3: /api/vendas/funil ----
export interface VendasFunilPayload {
  periodo: { ini: string; fim: string };
  kpis: {
    reunioes: number; oportunidades: number; bookings: number; receita: number | null;
    conv_oport_booking_pct: number | null; meta_pct: number;
  };
  funil: {
    etapas: Array<{ key: string; label: string; volume: number; conversao_da_anterior_pct: number | null }>;
    leads: number; receita: number | null; conversao_total_pct: number | null;
  };
  por_bundle: Array<{ bundle: string; oportunidades: number; mix_pct: number;
    bookings: number; conv_pct: number | null }>;
  origem_x_plano: {
    planos: string[];
    linhas: Array<{ origem: string; por_plano: Record<string, number>; total: number;
      leads: number; tx_lead_booking_pct: number | null }>;
  };
  tendencia: Array<{ mes: string; oportunidades: number; bookings: number;
    conv_pct: number | null; na_meta: boolean }>;
  diagnostico: { persona: string; itens: string[]; fonte: string };
}

// ---- Lote 3: /api/vendas/ponte ----
export interface PonteSegItem {
  rotulo: string; oports: number; fechadas: number; perdidas: number;
  em_aberto: number; taxa_pct: number | null; amostra_pequena: boolean;
}
export interface VendasPontePayload {
  periodo: { ini: string; fim: string };
  kpis: { oportunidades: number; fechadas: number; decididas: number;
    em_aberto: number; fechamento_pct: number | null };
  leitura: { texto: string; fonte: string };
  por_sla: PonteSegItem[];
  por_tempo_qualificacao: PonteSegItem[];
  por_origem: PonteSegItem[];
  por_sdr: PonteSegItem[];
  por_closer: PonteSegItem[];
}

// ---- Lote 3: /api/marketing/canais ----
export interface MktCanaisPayload {
  periodo: { ini: string; fim: string; dias: number };
  canais: Array<{ canal: string; gasto: number | null; leads: number;
    var_leads_pct: number | null; cpl: number | null;
    conv_lead_oport_pct: number | null; bookings: number;
    conv_lead_book_pct: number | null; receita: number | null;
    cac: number | null; roas: number | null }>;
  meses: string[];
  evolucao: Array<{ canal: string;
    meses: Array<{ mes: string; leads: number; cpl: number | null; cac: number | null }> }>;
}

// ---- Lote 3: /api/marketing/origens ----
export interface MktOrigensPayload {
  periodo: { ini: string; fim: string };
  origem: string | null;
  midia: string;
  totais?: { leads: number; bookings: number };
  linhas?: Array<{ origem: string; tag: "escalar?" | "revisar" | null;
    leads: number; oport: number; oport_pct: number; bookings: number;
    conv_pct: number; receita: number | null }>;
  detalhe?: Array<{ campanha: string; criativo: string; leads: number;
    oport: number; bookings: number; receita: number | null }>;
}

// ---- Lote 3: /api/vendas/ciclo ----
export interface VendasCicloPayload {
  periodo: { ini: string; fim: string };
  kpis: { ciclo_mediano_d: number | null; p25_d: number | null; p75_d: number | null;
    n_ganhos: number; abertos: number; empacados: number; limiar_dias: number };
  empacados: Array<{ deal_id: number; dono: string; plano: string; valor: number | null; dias: number }>;
}
