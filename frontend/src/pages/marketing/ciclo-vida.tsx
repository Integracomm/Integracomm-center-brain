import { Users, UserCheck, UserX } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { SectionCard } from "@/components/blocks/section-card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatBRL, formatPct } from "@/lib/format";

// Marketing · Ciclo de Vida (Lote 4) — /api/marketing/ciclo-vida embrulha
// _ciclo_coorte (a MESMA coorte que o Raio-X por Bundle usa). Liga aquisição
// (canal/criativo) a retenção (churn precoce ≤3m / tardio).

interface Payload {
  vazio: boolean;
  kpis: { clientes: number; ativos_pct: number | null; precoce_pct: number | null };
  leitura: string;
  cobertura: { canc_casados: number; n_cancs: number; sem_origem: number };
  canais: Array<{ canal: string; clientes: number; ativos_pct: number | null; precoce_pct: number | null;
    tardio_pct: number | null; mrr_retido: number; mrr_perdido: number;
    cac: number | null; cac_ajustado: number | null }>;
  criativos: Array<{ criativo: string; clientes: number; ativos_pct: number | null;
    precoce_pct: number | null; amostra_pequena: boolean }>;
  canal_x_bundle: { bundles: string[];
    linhas: Array<{ canal: string; cels: Array<{ bundle: string; precoce_pct: number | null; n: number; alerta: boolean }> }> };
  safras: Array<{ safra: string; clientes: number; ativos_pct: number | null;
    precoce_pct: number | null; tardio_pct: number | null; em_maturacao: boolean }>;
}

const thCls = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
const numCls = "text-right tabular-nums";
const pct = (v: number | null) => (v != null ? formatPct(v, 1) : "—");

export function MktCicloVidaPage() {
  const q = useApi<Payload>("/api/marketing/ciclo-vida");
  const d = q.data;
  const cobPct = d && d.cobertura.n_cancs
    ? (d.cobertura.canc_casados / d.cobertura.n_cancs) * 100 : 0;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Ciclo de Vida — Aquisição → Retenção<Hint area="marketing/ciclo" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Segue cada cliente FECHADO da origem ao desfecho atual (ativo · churn precoce ≤3 meses ·
          tardio) — qual canal traz cliente que FICA? · vínculo por nome booking↔cancelamento.
        </p>
      </header>
      {q.loading && <LoadingSkeleton rows={6} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && d.vazio && (
        <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
          Sem bookings rastreados ainda.
        </p>
      )}
      {d && !d.vazio && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
            <KpiCard icon={Users} tone="primary" title="Clientes na coorte"
              value={d.kpis.clientes.toLocaleString("pt-BR")} />
            <KpiCard icon={UserCheck} tone="success" title="Ainda ativos" value={pct(d.kpis.ativos_pct)} />
            <KpiCard icon={UserX} tone="destructive" title="Churn precoce (≤3m)"
              value={pct(d.kpis.precoce_pct)}
              caveat={`conclusões baseadas em ${d.cobertura.canc_casados} de ${d.cobertura.n_cancs} cancelamentos vinculados a um booking rastreado (${cobPct.toFixed(0)}%) — clientes pré-2025 não têm vínculo`} />
          </div>

          <SectionCard hint={<Hint area="marketing/ciclo" titulo="Leitura do especialista" />}
            title="Leitura do especialista"
            subtitle="gerada por regras determinísticas (canais com 8+ clientes) — hipótese, não veredito">
            <p className="text-sm leading-relaxed">→ {d.leitura}</p>
          </SectionCard>

          <SectionCard hint={<Hint area="marketing/ciclo" titulo="Desfecho por canal de origem" />}
            title="Desfecho por canal de origem"
            subtitle="CAC aj. = CAC ÷ taxa de retenção — o custo REAL por cliente que fica (corrige a ilusão do canal barato) · CAC só p/ canais com gasto rastreado">
            <p className="mb-2 text-xs text-muted-foreground">
              Conclusões baseadas em <b>{d.cobertura.canc_casados} de {d.cobertura.n_cancs}</b> cancelamentos
              vinculados a um booking rastreado ({cobPct.toFixed(0)}%) — os sem vínculo (clientes pré-2025)
              podem alterar este quadro; “canal X retém melhor” é leitura da parte vinculada.
            </p>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Canal</TableHead>
                    <TableHead className={`${thCls} text-right`}>Clientes</TableHead>
                    <TableHead className={`${thCls} text-right`}>Ativos</TableHead>
                    <TableHead className={`${thCls} text-right`}>Precoce</TableHead>
                    <TableHead className={`${thCls} text-right`}>Tardio</TableHead>
                    <TableHead className={`${thCls} text-right`}>MRR retido</TableHead>
                    <TableHead className={`${thCls} text-right`}>MRR perdido</TableHead>
                    <TableHead className={`${thCls} text-right`}>CAC</TableHead>
                    <TableHead className={`${thCls} text-right`}>CAC aj.</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.canais.map((c) => (
                    <TableRow key={c.canal}>
                      <TableCell className="font-medium">{c.canal}</TableCell>
                      <TableCell className={numCls}>{c.clientes}</TableCell>
                      <TableCell className={numCls}>{pct(c.ativos_pct)}</TableCell>
                      <TableCell className={`${numCls} text-destructive`}>{pct(c.precoce_pct)}</TableCell>
                      <TableCell className={numCls}>{pct(c.tardio_pct)}</TableCell>
                      <TableCell className={numCls}>{formatBRL(c.mrr_retido)}</TableCell>
                      <TableCell className={numCls}>{formatBRL(c.mrr_perdido)}</TableCell>
                      <TableCell className={numCls}>{c.cac != null ? formatBRL(c.cac) : "—"}</TableCell>
                      <TableCell className={`${numCls} font-semibold`}>{c.cac_ajustado != null ? formatBRL(c.cac_ajustado) : "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </SectionCard>

          <SectionCard hint={<Hint area="marketing/ciclo" titulo="Criativos que trazem churn precoce" />}
            title="Criativos que trazem churn precoce (mídia paga)"
            subtitle="ordenado do pior — criativo que promete demais traz cliente que sai cedo · amostra <8 mostra o dado, sem diagnóstico">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className={thCls}>Criativo</TableHead>
                  <TableHead className={`${thCls} text-right`}>Clientes</TableHead>
                  <TableHead className={`${thCls} text-right`}>Ativos</TableHead>
                  <TableHead className={`${thCls} text-right`}>Precoce</TableHead>
                  <TableHead className={thCls}></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.criativos.map((c) => (
                  <TableRow key={c.criativo}>
                    <TableCell>{c.criativo}</TableCell>
                    <TableCell className={numCls}>{c.clientes}</TableCell>
                    <TableCell className={numCls}>{pct(c.ativos_pct)}</TableCell>
                    <TableCell className={`${numCls} text-destructive`}>{pct(c.precoce_pct)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {c.amostra_pequena ? "amostra pequena — sem diagnóstico" : ""}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </SectionCard>

          <SectionCard hint={<Hint area="marketing/ciclo" titulo="Churn precoce por canal × plano" />}
            title="Churn precoce por canal × plano"
            subtitle="de onde vêm os clientes que saem cedo em cada bundle · vermelho = ≥40% com n≥5">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className={thCls}>Canal</TableHead>
                    {d.canal_x_bundle.bundles.map((b) => (
                      <TableHead key={b} className={`${thCls} text-center`}>{b}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.canal_x_bundle.linhas.map((l) => (
                    <TableRow key={l.canal}>
                      <TableCell className="font-medium">{l.canal}</TableCell>
                      {l.cels.map((c) => (
                        <TableCell key={c.bundle} className={`text-center tabular-nums ${c.alerta ? "text-destructive" : ""}`}>
                          {c.precoce_pct != null ? (
                            <>{formatPct(c.precoce_pct, 0)}<span className="text-[10px] text-muted-foreground"> ({c.n})</span></>
                          ) : <span className="text-muted-foreground">—</span>}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </SectionCard>

          <SectionCard hint={<Hint area="marketing/ciclo" titulo="Safras por mês de fechamento" />}
            title="Safras por mês de fechamento"
            subtitle="safra recente ainda não teve tempo de churnar — “(em maturação)” = leitura parcial">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className={thCls}>Safra</TableHead>
                  <TableHead className={`${thCls} text-right`}>Clientes</TableHead>
                  <TableHead className={`${thCls} text-right`}>Ativos</TableHead>
                  <TableHead className={`${thCls} text-right`}>Precoce</TableHead>
                  <TableHead className={`${thCls} text-right`}>Tardio</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.safras.map((s) => (
                  <TableRow key={s.safra}>
                    <TableCell className="font-medium">
                      {s.safra}
                      {s.em_maturacao && <span className="ml-2 text-xs text-muted-foreground">(em maturação)</span>}
                    </TableCell>
                    <TableCell className={numCls}>{s.clientes}</TableCell>
                    <TableCell className={numCls}>{pct(s.ativos_pct)}</TableCell>
                    <TableCell className={numCls}>{pct(s.precoce_pct)}</TableCell>
                    <TableCell className={numCls}>{pct(s.tardio_pct)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <p className="mt-3 text-xs text-muted-foreground">
              Cobertura do vínculo: {d.cobertura.canc_casados}/{d.cobertura.n_cancs} cancelamentos casados com
              um booking rastreado · {d.cobertura.sem_origem} booking(s) sem origem atribuída.
            </p>
          </SectionCard>
        </>
      )}
    </div>
  );
}
