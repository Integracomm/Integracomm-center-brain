import { formatBRL, formatNumber } from "@/lib/format";
import type { Metrica } from "./tipos";

// O QUE mostrar vem do endpoint (rótulo, valor, meta, tom); aqui só o COMO.
export const fmtValor = (v: number | null, formato: string) => {
  if (v == null) return "\u2014";
  if (formato === "brl") return formatBRL(v);
  if (formato === "pct1") return `${(v * 100).toFixed(1).replace(".", ",")}%`;
  if (formato === "pct0") return `${(v * 100).toFixed(0)}%`;
  if (formato === "pctp") return `${v.toFixed(0)}%`;
  return formatNumber(Math.round(v));
};

export const mval = (m: Metrica) => (m.texto != null ? m.texto : fmtValor(m.valor, m.formato));

export const valorComMeta = (m: Metrica) =>
  m.meta != null && m.valor != null
    ? `${mval(m)} / ${fmtValor(m.meta, m.formato)}`
    : mval(m);
