import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RTooltip,
  Legend,
  LabelList,
} from "recharts";
import { ChartHeight } from "./chart-height";
import { axisProps, gridProps, tooltipStyle } from "./chart-theme";

// Item genérico: precisa de rótulo (categoria) e valor da barra.
// Campos extras podem ser exibidos via `secondaryLabel` (rótulo da barra) e tooltip.
export interface BarListItem {
  label: string;
  value: number;
  [key: string]: unknown;
}

// Barras horizontais ordenadas — padrão para "comparar categorias" e Pareto.
// - Ordenação: a lista é desenhada na ordem recebida. Ordene antes se necessário.
// - Rótulo do valor: sempre visível (regra da aplicação — nunca só no tooltip).
export function BarListH<T extends BarListItem>({
  data,
  color = "var(--chart-2)",
  height = 320,
  width = 150,
  xTickFormatter,
  valueLabel = (v) => v.toLocaleString("pt-BR"),
  tooltipFormatter,
}: {
  data: T[];
  color?: string;
  height?: number;
  width?: number;
  xTickFormatter?: (v: number) => string;
  // Formatação do rótulo à direita da barra (recebe valor + payload da linha).
  valueLabel?: (v: number, item: T) => string;
  // Tooltip: retorna [conteúdo, título]. Default = valueLabel.
  tooltipFormatter?: (v: number, item: T) => [string, string];
}) {
  return (
    <ChartHeight height={height}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 80, bottom: 4, left: 24 }}
      >
        <CartesianGrid {...gridProps} horizontal={false} />
        <XAxis type="number" tickFormatter={xTickFormatter} {...axisProps} />
        <YAxis
          type="category"
          dataKey="label"
          width={width}
          {...axisProps}
        />
        <RTooltip
          cursor={{ fill: "var(--muted)" }}
          contentStyle={tooltipStyle}
          formatter={(v: number, _n, item: { payload?: T }) =>
            tooltipFormatter && item?.payload
              ? tooltipFormatter(v, item.payload)
              : [valueLabel(v, item?.payload as T), ""]
          }
        />
        <Bar dataKey="value" fill={color} radius={[0, 6, 6, 0]}>
          <LabelList
            dataKey="value"
            position="right"
            content={(props: any) => {
              const { x, y, width: w, height: h, index } = props;
              const item = data[index];
              if (item == null || x == null || y == null) return null;
              return (
                <text
                  x={Number(x) + Number(w) + 6}
                  y={Number(y) + Number(h) / 2}
                  dominantBaseline="middle"
                  className="fill-foreground text-xs font-medium"
                >
                  {valueLabel(item.value, item)}
                </text>
              );
            }}
          />
        </Bar>
      </BarChart>
    </ChartHeight>
  );
}

// Série de uma variante agrupada (2+ barras lado a lado por categoria).
export interface BarListSeries {
  key: string;                    // chave em data[i][key]
  label: string;                  // legenda
  color: string;                  // ex.: var(--chart-2)
}

// Barras horizontais AGRUPADAS — comparar 2+ medidas da mesma categoria
// (CAC vs CAC ajustado, bookings vs meta). Aprovado no plano do redesenho
// (Otávio 21/07): variante no mesmo arquivo, mesmas regras do BarListH
// (ordem = ordem recebida; rótulo sempre visível via tooltip + legenda).
export function BarListHGrouped<T extends { label: string }>({
  data,
  series,
  height = 320,
  width = 150,
  xTickFormatter,
  valueLabel = (v) => v.toLocaleString("pt-BR"),
}: {
  data: T[];
  series: BarListSeries[];
  height?: number;
  width?: number;
  xTickFormatter?: (v: number) => string;
  valueLabel?: (v: number) => string;
}) {
  return (
    <ChartHeight height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 24 }}>
        <CartesianGrid {...gridProps} horizontal={false} />
        <XAxis type="number" tickFormatter={xTickFormatter} {...axisProps} />
        <YAxis type="category" dataKey="label" width={width} {...axisProps} />
        <RTooltip
          cursor={{ fill: "var(--muted)" }}
          contentStyle={tooltipStyle}
          formatter={(v: number, name: string) => [valueLabel(v), name]}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {series.map((s) => (
          <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} radius={[0, 4, 4, 0]} />
        ))}
      </BarChart>
    </ChartHeight>
  );
}
