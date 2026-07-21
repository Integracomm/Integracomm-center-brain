import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RTooltip,
  Legend,
  LabelList,
  Cell,
} from "recharts";
import { ChartHeight } from "./chart-height";
import { axisProps, gridProps, tooltipStyle } from "./chart-theme";

// Definição de um segmento (série empilhada).
export interface StackedSegment {
  key: string;       // chave em `data[i][key]`
  label: string;     // rótulo exibido no legend e tooltip
  color: string;     // ex.: var(--success), var(--destructive), var(--chart-3)
}

export interface StackedBarItem {
  label: string;                  // categoria (eixo Y)
  maturacao?: boolean;            // backend marca — reduz opacidade + hachura
  [key: string]: unknown;         // valores por segmento (por key)
}

export interface StackedBarHProps<T extends StackedBarItem> {
  data: T[];
  segments: StackedSegment[];
  height?: number;
  width?: number;                 // largura da coluna de rótulos
  // Formatação do rótulo dentro de cada segmento (default: número pt-BR).
  // Retornar "" esconde o rótulo do segmento (útil quando pequeno demais).
  segmentLabel?: (v: number, item: T, segment: StackedSegment) => string;
  // Formatação do tooltip por segmento.
  tooltipFormatter?: (v: number, item: T, segment: StackedSegment) => [string, string];
  // Formatação do eixo X.
  xTickFormatter?: (v: number) => string;
  // Legendas customizadas de anotação (ex.: "hachura = em maturação").
  legendNote?: string;
}

// Barras horizontais empilhadas — proporção de um todo por categoria.
// Usar para: mix de status (ativo/precoce/tardio), composição de canais, etc.
// Regra: valor visível em segmentos relevantes; cor + rótulo.
// `maturacao` no item aplica opacidade menor + hachura (não é falha, é aviso).
export function StackedBarH<T extends StackedBarItem>({
  data,
  segments,
  height = 320,
  width = 160,
  segmentLabel = (v) => v.toLocaleString("pt-BR"),
  tooltipFormatter,
  xTickFormatter,
  legendNote,
}: StackedBarHProps<T>) {
  return (
    <div>
      <ChartHeight height={height}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 8, right: 24, bottom: 8, left: 24 }}
        >
          <CartesianGrid {...gridProps} horizontal={false} />
          <XAxis type="number" tickFormatter={xTickFormatter} {...axisProps} />
          <YAxis type="category" dataKey="label" width={width} {...axisProps} />
          <RTooltip
            cursor={{ fill: "var(--muted)" }}
            contentStyle={tooltipStyle}
            formatter={(v: number, name: string, item: { payload?: T }) => {
              const seg = segments.find((s) => s.label === name);
              if (tooltipFormatter && item?.payload && seg) {
                return tooltipFormatter(v, item.payload, seg);
              }
              return [v.toLocaleString("pt-BR"), name];
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {segments.map((seg, i) => (
            <Bar
              key={seg.key}
              dataKey={seg.key}
              name={seg.label}
              stackId="stack"
              fill={seg.color}
              radius={
                i === segments.length - 1
                  ? [0, 6, 6, 0]
                  : i === 0
                  ? [6, 0, 0, 6]
                  : [0, 0, 0, 0]
              }
            >
              {data.map((d, idx) => (
                <Cell
                  key={idx}
                  fill={seg.color}
                  opacity={d.maturacao ? 0.55 : 1}
                  style={
                    d.maturacao
                      ? {
                          backgroundImage:
                            "repeating-linear-gradient(45deg, transparent 0 4px, rgba(0,0,0,0.15) 4px 5px)",
                        }
                      : undefined
                  }
                />
              ))}
              <LabelList
                dataKey={seg.key}
                position="center"
                content={(props: any) => {
                  const { x, y, width: w, height: h, index } = props;
                  const item = data[index];
                  const raw = (item as any)?.[seg.key];
                  if (item == null || raw == null || w < 28) return null;
                  const text = segmentLabel(Number(raw), item, seg);
                  if (!text) return null;
                  return (
                    <text
                      x={Number(x) + Number(w) / 2}
                      y={Number(y) + Number(h) / 2}
                      textAnchor="middle"
                      dominantBaseline="middle"
                      className="fill-white text-[11px] font-medium"
                    >
                      {text}
                    </text>
                  );
                }}
              />
            </Bar>
          ))}
        </BarChart>
      </ChartHeight>
      {legendNote && (
        <div className="mt-2 text-[11px] text-muted-foreground flex items-center gap-2">
          <span
            className="inline-block h-3 w-3 rounded-sm border border-border/60"
            style={{
              backgroundImage:
                "repeating-linear-gradient(45deg, transparent 0 3px, rgba(0,0,0,0.2) 3px 4px)",
              opacity: 0.55,
            }}
          />
          {legendNote}
        </div>
      )}
    </div>
  );
}
