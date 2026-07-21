import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RTooltip,
  Legend,
  ReferenceLine,
  ReferenceDot,
} from "recharts";
import { ChartHeight } from "./chart-height";
import { axisProps, gridProps, tooltipStyle } from "./chart-theme";

// Definição de uma série no tempo.
export interface TimeSeriesLine {
  key: string;                    // chave em `data[i][key]`
  label: string;                  // rótulo (legend/tooltip)
  color: string;                  // ex.: var(--chart-1), var(--success)
  kind?: "line" | "area";         // default: line
  dashed?: boolean;               // linha tracejada
  strokeWidth?: number;           // default: 2
  yAxis?: "left" | "right";       // default: "left"
  // Formatação do valor no tooltip (default: pt-BR). Ex.: (v) => `${v}%`.
  valueFormatter?: (v: number) => string;
}

// Linha de referência horizontal (ex.: ISR=100, Quick Ratio=1).
export interface TimeSeriesReference {
  yAxis?: "left" | "right";       // default: "left"
  value: number;
  label?: string;
  color?: string;                 // default: var(--muted-foreground)
  dashed?: boolean;               // default: true
}

// Anotação em um ponto específico (ex.: crossover, evento).
export interface TimeSeriesAnnotation {
  x: string | number;             // valor no eixo X (bate com data[i].x)
  seriesKey: string;              // série a qual o ponto pertence
  yAxis?: "left" | "right";
  label: string;
  color?: string;                 // default: var(--accent)
}

// Ponto individual com ressalva (aviso — não é falha).
// Marca pontos com base pequena/alta variância com ponto oco.
// ARRAY (não Set): o mapa vem direto do payload JSON do backend.
export type CaveatMap = Record<string, Array<string | number>>;

export interface TimeSeriesProps<T> {
  data: T[];                                  // ordem cronológica asc
  xKey: keyof T & string;                     // ex.: "month_label"
  series: TimeSeriesLine[];
  references?: TimeSeriesReference[];
  annotations?: TimeSeriesAnnotation[];
  // Pontos com ressalva por série: caveats[key] = Set(xValues).
  // Backend informa; frontend só marca.
  caveats?: CaveatMap;
  // Escala do eixo direito, se houver série `yAxis:"right"`.
  rightDomain?: [number | "auto", number | "auto"];
  leftDomain?: [number | "auto", number | "auto"];
  leftTickFormatter?: (v: number) => string;
  rightTickFormatter?: (v: number) => string;
  height?: number;
}

// Evolução no tempo (linha ou área) com linhas de referência e anotações.
// Regras:
// - Eixo Y duplo quando séries têm unidades diferentes (%/absoluto).
// - `references` para metas/thresholds (ex.: 100 no ISR, 1 no Quick Ratio).
// - `annotations` para pontos-chave (ex.: crossover).
// - `caveats` marca pontos com base pequena (ponto oco), sem esconder o dado.
export function TimeSeries<T>({
  data,
  xKey,
  series,
  references,
  annotations,
  caveats,
  rightDomain,
  leftDomain,
  leftTickFormatter,
  rightTickFormatter,
  height = 320,
}: TimeSeriesProps<T>) {
  const hasRight = series.some((s) => s.yAxis === "right");

  return (
    <ChartHeight height={height}>
      <ComposedChart data={data} margin={{ top: 16, right: 24, bottom: 8, left: 0 }}>
        <CartesianGrid {...gridProps} vertical={false} />
        <XAxis dataKey={xKey as string} {...axisProps} />
        <YAxis
          yAxisId="left"
          domain={leftDomain}
          tickFormatter={leftTickFormatter}
          {...axisProps}
        />
        {hasRight && (
          <YAxis
            yAxisId="right"
            orientation="right"
            domain={rightDomain}
            tickFormatter={rightTickFormatter}
            {...axisProps}
          />
        )}
        <RTooltip
          contentStyle={tooltipStyle}
          formatter={(v: number, name: string) => {
            const s = series.find((x) => x.label === name);
            return [s?.valueFormatter ? s.valueFormatter(v) : v.toLocaleString("pt-BR"), name];
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />

        {references?.map((r, i) => (
          <ReferenceLine
            key={`ref-${i}`}
            yAxisId={r.yAxis ?? "left"}
            y={r.value}
            stroke={r.color ?? "var(--muted-foreground)"}
            strokeDasharray={r.dashed === false ? undefined : "4 4"}
            label={
              r.label
                ? { value: r.label, position: "insideTopRight", fill: "var(--muted-foreground)", fontSize: 11 }
                : undefined
            }
          />
        ))}

        {series.map((s) => {
          const common = {
            key: s.key,
            yAxisId: s.yAxis ?? "left",
            dataKey: s.key,
            name: s.label,
            stroke: s.color,
            strokeWidth: s.strokeWidth ?? 2,
            strokeDasharray: s.dashed ? "4 4" : undefined,
            type: "monotone" as const,
            isAnimationActive: false,
          };
          const dot = (props: any) => {
            const { cx, cy, payload } = props;
            if (cx == null || cy == null) return <g key={`d-${props.index}`} />;
            const x = payload?.[xKey as string];
            const isCaveat = caveats?.[s.key]?.includes(x);
            return (
              <circle
                key={`d-${props.index}`}
                cx={cx}
                cy={cy}
                r={3.5}
                fill={isCaveat ? "var(--background)" : s.color}
                stroke={s.color}
                strokeWidth={1.5}
              />
            );
          };
          if (s.kind === "area") {
            return (
              <Area
                {...common}
                fill={s.color}
                fillOpacity={0.15}
                dot={dot}
                activeDot={{ r: 5 }}
              />
            );
          }
          return <Line {...common} dot={dot} activeDot={{ r: 5 }} />;
        })}

        {annotations?.map((a, i) => {
          const point = data.find((d) => (d as any)[xKey] === a.x);
          const yVal = point ? Number((point as any)[a.seriesKey]) : null;
          if (yVal == null || Number.isNaN(yVal)) return null;
          return (
            <ReferenceDot
              key={`ann-${i}`}
              yAxisId={a.yAxis ?? "left"}
              x={a.x as any}
              y={yVal}
              r={6}
              fill={a.color ?? "var(--accent)"}
              stroke="var(--background)"
              strokeWidth={2}
              label={{
                value: a.label,
                position: "top",
                fill: a.color ?? "var(--accent)",
                fontSize: 11,
                fontWeight: 600,
              }}
            />
          );
        })}
      </ComposedChart>
    </ChartHeight>
  );
}
