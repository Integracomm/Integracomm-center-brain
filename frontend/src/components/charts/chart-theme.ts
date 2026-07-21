// Tokens visuais compartilhados por todos os gráficos Recharts.
// Mantém tooltip, eixos e paleta consistentes entre telas.

export const tooltipStyle: React.CSSProperties = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: "0.5rem",
  fontSize: "12px",
  color: "var(--popover-foreground)",
};

export const axisProps = {
  tickLine: false,
  axisLine: false,
  stroke: "var(--muted-foreground)",
  fontSize: 12,
} as const;

export const gridProps = {
  strokeDasharray: "3 3",
  stroke: "var(--border)",
} as const;

// Paleta ordenada — usar por índice ou nomeadamente pelo semântico.
export const chartColors = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

export const semanticColors = {
  success: "var(--success)",
  warning: "var(--warning)",
  destructive: "var(--destructive)",
  primary: "var(--primary)",
  accent: "var(--accent)",
  muted: "var(--muted)",
} as const;
