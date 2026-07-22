import { Fragment, useMemo } from "react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { CaveatChip } from "@/components/caveat";

// Célula de cruzamento (row × col). `value` null = sem dado.
export interface HeatmapCell {
  row: string;
  col: string;
  value: number | null;
  n?: number;                 // amostra (para marcar pequena)
  amostra_pequena?: boolean;  // backend marca; frontend NÃO recalcula
}

export interface HeatmapProps {
  rows: string[];               // ordem do eixo Y
  cols: string[];               // ordem do eixo X
  cells: HeatmapCell[];         // matriz esparsa (rows × cols)
  // Escala de intensidade. `min`/`max` já vêm do backend quando possível.
  scale?: { min: number; max: number };
  // Cor base — a intensidade é aplicada como alfa 10% → 90%.
  color?: string;               // default: var(--destructive)
  // Formatação do valor dentro da célula. Vazio ("") esconde o rótulo.
  valueLabel?: (v: number) => string;
  // 2ª linha DENTRO da célula, menor e apagada — para quando o valor principal
  // é relativo e sozinho engana (ex.: % de atendimento sobre 3 ligações).
  // Devolver null/"" omite a linha naquela célula.
  subLabel?: (cell: HeatmapCell) => string | null;
  // Célula mais alta. Precisa ser LIGADA NOS DOIS mapas quando eles ficam lado
  // a lado: um mapa com `subLabel` e o outro sem desalinharia as linhas.
  tall?: boolean;
  // Tooltip: texto completo (row × col + contexto).
  tooltipLabel?: (cell: HeatmapCell) => string;
  // Rótulo curto acima da legenda (ex.: "% de perdas", "leads").
  legendLabel?: string;
  // Largura mínima da coluna de rótulos das linhas.
  rowLabelWidth?: number;
  // Denso: muitas colunas (ex.: 14 horas) SEM scroll horizontal — célula
  // estreita, fonte menor (regra Otávio 21/07: nunca rolar para ver o dado).
  dense?: boolean;
  // Intensidade normalizada POR LINHA (compara o padrão de cada linha,
  // independente do volume) + contorno no pico da linha. Usado nas grades
  // colaborador×hora / origem×hora (Lote 2).
  rowScale?: boolean;
}

// Cruzamento de duas dimensões (motivo × bundle, canal × plano etc.).
// Regras:
// - Valor legível dentro da célula (cor + rótulo, nunca só cor).
// - `amostra_pequena` marca a célula com hachura + opacidade + ressalva.
// - `scale` deve vir do payload quando o eixo é comparável entre telas.
export function Heatmap({
  rows,
  cols,
  cells,
  scale,
  color = "var(--destructive)",
  valueLabel = (v) => v.toLocaleString("pt-BR"),
  subLabel,
  tall = false,
  tooltipLabel,
  legendLabel,
  rowLabelWidth = 160,
  rowScale = false,
  dense = false,
}: HeatmapProps) {
  const { lookup, min, max } = useMemo(() => {
    const lookup = new Map<string, HeatmapCell>();
    let min = scale?.min ?? Number.POSITIVE_INFINITY;
    let max = scale?.max ?? Number.NEGATIVE_INFINITY;
    for (const c of cells) {
      lookup.set(`${c.row}||${c.col}`, c);
      if (!scale && c.value != null) {
        if (c.value < min) min = c.value;
        if (c.value > max) max = c.value;
      }
    }
    if (!isFinite(min)) min = 0;
    if (!isFinite(max) || max === min) max = min + 1;
    return { lookup, min, max };
  }, [cells, scale]);

  const alphaFor = (v: number) => {
    const t = Math.max(0, Math.min(1, (v - min) / (max - min)));
    return 0.1 + t * 0.8; // 10% → 90%
  };
  // por linha: max da própria linha (rowScale)
  const rowMax = useMemo(() => {
    const m = new Map<string, number>();
    if (rowScale) {
      for (const c of cells) {
        if (c.value != null) m.set(c.row, Math.max(m.get(c.row) ?? 0, c.value));
      }
    }
    return m;
  }, [cells, rowScale]);
  const alphaRow = (row: string, v: number) => {
    const mx = rowMax.get(row) || 1;
    return 0.1 + Math.max(0, Math.min(1, v / mx)) * 0.8;
  };

  return (
    <div className="w-full">
      <div className={dense ? "" : "overflow-x-auto"}>
        <div
          className="grid gap-1"
          style={{
            gridTemplateColumns: `${rowLabelWidth}px repeat(${cols.length}, minmax(${dense ? 28 : 72}px, 1fr))`,
          }}
        >
          {/* Header row */}
          <div />
          {cols.map((c) => (
            <div
              key={c}
              className={`${dense ? "text-[9px]" : "text-[11px]"} uppercase tracking-wide text-muted-foreground text-center pb-1`}
            >
              {c}
            </div>
          ))}

          {/* Body */}
          <TooltipProvider delayDuration={100}>
            {rows.map((row) => (
              // key no Fragment (bug do protótipo: <> sem key gerava warning
              // e re-render instável das linhas)
              <Fragment key={row}>
                <div
                  className="text-xs text-foreground/80 pr-2 flex items-center truncate"
                  title={row}
                >
                  {row}
                </div>
                {cols.map((col) => {
                  const cell = lookup.get(`${row}||${col}`);
                  const v = cell?.value ?? null;
                  const small = cell?.amostra_pequena;
                  const alpha = v == null ? 0 : (rowScale ? alphaRow(row, v) : alphaFor(v));
                  const pico = rowScale && v != null && v === (rowMax.get(row) ?? -1) && v > 0;
                  const bg =
                    v == null
                      ? "var(--muted)"
                      : `color-mix(in oklab, ${color} ${Math.round(alpha * 100)}%, transparent)`;
                  const sub = cell && v != null && subLabel ? subLabel(cell) : null;
                  const tooltipText =
                    tooltipLabel && cell
                      ? tooltipLabel(cell)
                      : v == null
                      ? `${row} × ${col}: sem dado`
                      : `${row} × ${col}: ${valueLabel(v)}${cell?.n != null ? ` (n=${cell.n})` : ""}`;
                  return (
                    <Tooltip key={`${row}-${col}`}>
                      <TooltipTrigger asChild>
                        <div
                          className={`relative ${dense ? (tall ? "h-11" : "h-8") + " text-[10px]" : (tall ? "h-12" : "h-10") + " text-xs"} rounded-md flex flex-col items-center justify-center leading-tight font-medium tabular-nums cursor-default border border-border/40`}
                          style={{
                            background: bg,
                            boxShadow: pico ? `inset 0 0 0 1.5px ${color}` : undefined,
                            backgroundImage: small
                              ? "repeating-linear-gradient(45deg, transparent 0 4px, color-mix(in oklab, var(--foreground) 22%, transparent) 4px 5px)"
                              : undefined,
                            opacity: small ? 0.85 : 1,
                          }}
                        >
                          {v == null ? (
                            <span className="text-muted-foreground/60">—</span>
                          ) : (
                            <>
                              <span className="text-foreground">{valueLabel(v)}</span>
                              {sub && (
                                // legível de relance: a 2ª linha é dado, não
                                // enfeite (Otávio 22/07 — estava apagada demais)
                                <span className="text-[10px] font-medium text-foreground/80">{sub}</span>
                              )}
                            </>
                          )}
                        </div>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="text-xs">
                        <div>{tooltipText}</div>
                        {small && (
                          <div className="mt-1 text-[11px] text-muted-foreground">
                            Amostra pequena — interpretar com cautela.
                          </div>
                        )}
                      </TooltipContent>
                    </Tooltip>
                  );
                })}
              </Fragment>
            ))}
          </TooltipProvider>
        </div>
      </div>

      {/* Legenda de escala */}
      <div className="mt-3 flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
            {legendLabel ?? "Escala"}
          </span>
          <span className="text-[11px] tabular-nums text-muted-foreground">{valueLabel(min)}</span>
          <div
            className="h-2 w-32 rounded"
            style={{
              background: `linear-gradient(to right, color-mix(in oklab, ${color} 10%, transparent), color-mix(in oklab, ${color} 90%, transparent))`,
            }}
          />
          <span className="text-[11px] tabular-nums text-muted-foreground">{valueLabel(max)}</span>
        </div>
        <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
          <span
            className="inline-block h-3 w-3 rounded-sm border border-border/60"
            style={{
              backgroundImage:
                "repeating-linear-gradient(45deg, transparent 0 3px, color-mix(in oklab, var(--foreground) 30%, transparent) 3px 4px)",
            }}
          />
          <CaveatChip text="Amostra pequena — diagnóstico suprimido" />
        </div>
      </div>
    </div>
  );
}
