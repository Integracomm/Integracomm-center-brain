import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { apiPost } from "@/api/client";
import { formatBRL, formatNumber } from "@/lib/format";

// Operações · peças compartilhadas das 3 telas (Visão Geral, área, Config).
// Réplica do app Lovable "Metas e Iniciativas" — a régua vive no backend
// (operacoes/ui.py + metas.py); aqui só a apresentação.

export const SLUGS = ["financeiro", "comercial", "assessoria", "marketing", "rh", "growth"] as const;

// cor do semáforo (backend manda "verde/amarelo/vermelho/cinza") → classe
export const SEM_TEXT: Record<string, string> = {
  verde: "text-success", amarelo: "text-warning",
  vermelho: "text-destructive", cinza: "text-muted-foreground",
};
export const SEM_BG: Record<string, string> = {
  verde: "bg-success", amarelo: "bg-warning",
  vermelho: "bg-destructive", cinza: "bg-muted-foreground/50",
};
export const SEM_BORDER: Record<string, string> = {
  verde: "border-success/40 text-success",
  amarelo: "border-warning/40 text-warning",
  vermelho: "border-destructive/40 text-destructive",
  cinza: "border-border text-muted-foreground",
};

// MT.fmt_val do backend, transcrito
export function fmtVal(v: number | null | undefined, unit: string): string {
  if (v == null) return "—";
  if (unit === "BRL") return formatBRL(v);
  if (unit === "pct") return `${v.toFixed(1).replace(".", ",")}%`;
  return formatNumber(Math.round(v));
}

export function fmtData(iso: string | null): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

// ano/trimestre vivem na URL (?year=&quarter=) — favoritos/links continuam
// valendo, como no HTML; o default é o trimestre corrente
export function useYearQuarter() {
  const [params, setParams] = useSearchParams();
  const hoje = new Date();
  const year = Number(params.get("year")) || hoje.getFullYear();
  const quarter = Number(params.get("quarter")) || Math.floor(hoje.getMonth() / 3) + 1;
  const set = (patch: { year?: number; quarter?: number }) => {
    const next = new URLSearchParams(params);
    if (patch.year != null) next.set("year", String(patch.year));
    if (patch.quarter != null) next.set("quarter", String(patch.quarter));
    setParams(next);
  };
  return { year, quarter, set };
}

const selCls = "rounded-md border border-border bg-background px-2 py-1 text-sm";

// barra de filtros: ano/trimestre + Sincronizar Notion (POST reusa o endpoint
// do HTML). `area` = slug quando na página de uma área; null na Visão/Config.
export function FiltroBar({ area, onSynced }: { area?: string | null; onSynced?: () => void }) {
  const { year, quarter, set } = useYearQuarter();
  const [sincronizando, setSincronizando] = useState(false);
  const sync = async () => {
    setSincronizando(true);
    try {
      const r = await apiPost<{ errors?: string[] }>("/api/operacoes/initiatives/sync",
        { year, quarter, area: area ?? null });
      if (r.errors && r.errors.length) alert(r.errors.join("\n"));
      onSynced?.();
    } catch (e) {
      alert(e instanceof Error ? e.message : "falha de rede");
    } finally {
      setSincronizando(false);
    }
  };
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-xs text-muted-foreground">
        ano
        <select className={selCls} value={year} onChange={(e) => set({ year: Number(e.target.value) })}>
          {[2025, 2026, 2027].map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted-foreground">
        trimestre
        <select className={selCls} value={quarter} onChange={(e) => set({ quarter: Number(e.target.value) })}>
          {[1, 2, 3, 4].map((q) => <option key={q} value={q}>Q{q}</option>)}
        </select>
      </label>
      <button type="button" onClick={sync} disabled={sincronizando}
        className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
        <RefreshCw className={`h-3.5 w-3.5 ${sincronizando ? "animate-spin" : ""}`} />
        {sincronizando ? "sincronizando…" : "Sincronizar Notion"}
      </button>
    </div>
  );
}
