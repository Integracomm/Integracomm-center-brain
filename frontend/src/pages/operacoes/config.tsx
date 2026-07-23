import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { apiPost } from "@/api/client";
import { FiltroBar, useYearQuarter } from "./comum";

// Operações · Configurações — URLs do Notion por área, metas trimestrais por
// KPI e realizado manual (só onde não há fonte automática). As mutações reusam
// os mesmos POST do HTML (/api/operacoes/notion-config | kpi-target |
// kpi-monthly); leitura via /api/operacoes/config. Só admin escreve.

interface MesReal { month: number; label: string; realizado: number | null }
interface KpiDef {
  key: string; label: string; unit: string; direction: string;
  is_auto: boolean; meta: number | null; meses: MesReal[];
}
interface Payload {
  year: number; quarter: number; is_admin: boolean;
  areas_cfg: Array<{ slug: string; nome: string; database_id: string | null;
    database_name: string | null; gestor_filter: string | null }>;
  metas: Array<{ slug: string; nome: string; kpis: KpiDef[] }>;
  synclog: Array<{ area: string; ok: boolean; message: string; ts: string }>;
}

const inputCls = "rounded-md border border-border bg-background px-2 py-1.5 text-sm disabled:opacity-60";
const btnCls = "rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:border-primary hover:text-primary disabled:opacity-50";

function CfgAreaRow({ a, year, quarter, admin }: {
  a: Payload["areas_cfg"][number]; year: number; quarter: number; admin: boolean;
}) {
  const [url, setUrl] = useState(a.database_id ?? "");
  const [gestor, setGestor] = useState(a.gestor_filter ?? "");
  const [salvando, setSalvando] = useState(false);
  const salvar = async () => {
    setSalvando(true);
    try {
      await apiPost("/api/operacoes/notion-config",
        { area: a.slug, year, quarter, url: url || null, gestor: gestor || null });
    } catch (e) {
      alert(e instanceof Error ? e.message : "erro");
    } finally {
      setSalvando(false);
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-border py-2 first:border-t-0">
      <b className="w-[190px] text-sm">{a.nome}</b>
      <input className={`${inputCls} min-w-[240px] flex-1`} disabled={!admin}
        placeholder="cole a URL da página do trimestre…" value={url} onChange={(e) => setUrl(e.target.value)} />
      <input className={`${inputCls} w-[150px]`} disabled={!admin}
        title="p/ árvore compartilhada entre áreas: importa só as iniciativas da subpágina deste gestor"
        placeholder="gestor (opcional)" value={gestor} onChange={(e) => setGestor(e.target.value)} />
      {admin && <button className={btnCls} onClick={salvar} disabled={salvando}>salvar</button>}
      <span className="text-xs text-muted-foreground">
        {a.database_name || <span className="text-muted-foreground/60">não configurado</span>}
      </span>
    </div>
  );
}

function MetaKpiRow({ slug, k, year, quarter, admin }: {
  slug: string; k: KpiDef; year: number; quarter: number; admin: boolean;
}) {
  const [meta, setMeta] = useState(k.meta == null ? "" : String(k.meta));
  const [salvando, setSalvando] = useState(false);
  const salvarMeta = async () => {
    setSalvando(true);
    try {
      await apiPost("/api/operacoes/kpi-target",
        { area: slug, kpi_key: k.key, year, quarter, meta: meta === "" ? null : parseFloat(meta) });
    } catch (e) {
      alert(e instanceof Error ? e.message : "erro");
    } finally {
      setSalvando(false);
    }
  };
  const salvarReal = async (month: number, v: string) => {
    try {
      await apiPost("/api/operacoes/kpi-monthly",
        { area: slug, kpi_key: k.key, year, month, realizado: v === "" ? null : parseFloat(v) });
    } catch (e) {
      alert(e instanceof Error ? e.message : "erro");
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2 py-1.5">
      <span className="w-[210px] text-xs">
        {k.label}{!k.is_auto && <span className="text-muted-foreground/60"> (realizado manual)</span>}
      </span>
      <input type="number" step="any" className={`${inputCls} w-[190px]`} disabled={!admin}
        placeholder={`meta do trimestre (${k.unit})`} value={meta} onChange={(e) => setMeta(e.target.value)} />
      {admin && <button className={btnCls} onClick={salvarMeta} disabled={salvando}>salvar</button>}
      {!k.is_auto && k.meses.map((m) => (
        <input key={m.month} type="number" step="any" className={`${inputCls} w-[86px]`} disabled={!admin}
          placeholder={m.label} defaultValue={m.realizado == null ? "" : String(m.realizado)}
          onChange={(e) => salvarReal(m.month, e.target.value)} />
      ))}
    </div>
  );
}

export function OperacoesConfigPage() {
  const { year, quarter } = useYearQuarter();
  const q = useApi<Payload>(`/api/operacoes/config?year=${year}&quarter=${quarter}`);
  const d = q.data;
  const admin = !!d?.is_admin;
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">
            Configurações<Hint area="operacoes/iniciativas" titulo="Configuração" />
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            URLs do Notion, metas trimestrais e realizado manual — vale para Q{quarter}/{year}.
            {!admin && d && " (somente leitura — só o administrador edita)"}
          </p>
        </div>
        <FiltroBar onSynced={q.refetch} />
      </header>

      {q.loading && <LoadingSkeleton rows={4} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}

      {d && (
        <>
          <SectionCard title="URLs do Notion por área"
            subtitle={`vale para Q${quarter}/${year} · a página precisa estar compartilhada com a integração no Notion`}
            hint={<Hint area="operacoes/iniciativas" titulo="Configuração" />}>
            {d.areas_cfg.map((a) => (
              <CfgAreaRow key={a.slug} a={a} year={year} quarter={quarter} admin={admin} />
            ))}
          </SectionCard>

          <SectionCard title="Metas do trimestre por KPI"
            subtitle="meta trimestral (R$/qtde = soma dos meses; % = média) · KPIs marcados (realizado manual) ganham campos por mês — os demais preenchem sozinhos do banco">
            <div className="space-y-3">
              {d.metas.map((m) => (
                <div key={m.slug} className="border-t border-border pt-2 first:border-t-0">
                  <b className="text-sm">{m.nome}</b>
                  {m.kpis.map((k) => (
                    <MetaKpiRow key={k.key} slug={m.slug} k={k} year={year} quarter={quarter} admin={admin} />
                  ))}
                </div>
              ))}
            </div>
          </SectionCard>

          <SectionCard title="Últimas sincronizações"
            hint={<Hint area="operacoes/iniciativas" titulo="Últimas sincronizações" />}>
            {d.synclog.length === 0 ? (
              <p className="text-sm text-muted-foreground">nenhuma sincronização registrada ainda</p>
            ) : (
              <div className="space-y-0.5">
                {d.synclog.map((s, i) => (
                  <div key={i} className="text-xs text-muted-foreground">
                    {s.ok ? "✅" : "⚠️"} {s.area} — {s.message} <span className="text-muted-foreground/60">({s.ts})</span>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>
        </>
      )}
    </div>
  );
}
