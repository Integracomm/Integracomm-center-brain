import { AlertOctagon, ExternalLink, FileText, Send, ShieldAlert, Users } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { apiPost } from "@/api/client";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { KpiCard } from "@/components/kpi-card";
import { SectionCard } from "@/components/blocks/section-card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatBRL, formatNumber } from "@/lib/format";

// Growth · Relatórios (Lote 6) — /api/growth/relatorios devolve o MESMO
// `_report_from` de /api/reports/summary e do envio ao Slack. Uma régua só:
// se o número muda aqui, muda no Slack junto.

interface Payload {
  resumo: {
    data: string; monitoradas: number; avaliaveis: number; sem_dados: number;
    alertas: Record<string, number>; alertas_total: number;
    mrr_risco: number; mrr_critico: number; exec_atrasada: number;
    faixa: Record<string, number>; estagio: Record<string, number>;
    trajetoria: Record<string, number>;
    piores: Array<{ nome: string; score: number; estagio: string; mrr: number | null }>;
  };
  stage_labels: Record<string, string>;
  mes_referencia_padrao: string;
  contas: Array<{ id: string; nome: string }>;
  bundles_churn: string[];
}

const LBL_FAIXA: Record<string, string> = {
  baixo: "Baixo", medio: "Médio", alto: "Alto", critico: "Crítico", sem_dados: "Sem dados",
};
const LBL_TRAJ: Record<string, string> = {
  subindo: "Subindo", estavel: "Estável", caindo: "Caindo", piorando: "Piorando",
};
const COR_FAIXA: Record<string, string> = {
  baixo: "bg-success", medio: "bg-warning", alto: "bg-warning",
  critico: "bg-destructive", sem_dados: "bg-muted-foreground",
};
const COR_TRAJ: Record<string, string> = {
  subindo: "bg-success", estavel: "bg-muted-foreground",
  caindo: "bg-destructive", piorando: "bg-destructive",
};
const COR_ESTAGIO: Record<string, string> = {
  saudavel: "bg-success", desengajamento_inicial: "bg-warning",
  insatisfacao_latente: "bg-warning", insatisfacao_ativa: "bg-warning",
  intencao_de_saida: "bg-destructive", nao_avaliavel: "bg-muted-foreground",
};

// Distribuição: barra proporcional + rótulo — nunca só cor
function Distribuicao({ titulo, dist, cores, labels }: {
  titulo: string; dist: Record<string, number>;
  cores: Record<string, string>; labels: Record<string, string>;
}) {
  const total = Object.values(dist).reduce((s, v) => s + v, 0) || 1;
  return (
    <div>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {titulo}
      </div>
      <div className="space-y-2">
        {Object.entries(dist).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
          <div key={k}>
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <span className="flex items-center gap-1.5">
                <span className={cn("h-2 w-2 shrink-0 rounded-full", cores[k] ?? "bg-muted-foreground")} />
                {labels[k] ?? k}
              </span>
              <span className="tabular-nums text-muted-foreground">
                {v} <span className="text-xs">({((v / total) * 100).toFixed(0)}%)</span>
              </span>
            </div>
            <div className="mt-1 h-1 overflow-hidden rounded bg-muted">
              <div className={cn("h-full rounded", cores[k] ?? "bg-muted-foreground")}
                style={{ width: `${(v / total) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function GrowthRelatoriosPage() {
  const q = useApi<Payload>("/api/growth/relatorios");
  const d = q.data;
  const [envio, setEnvio] = useState<{ estado: "idle" | "enviando" | "ok" | "erro"; msg?: string }>(
    { estado: "idle" });

  async function enviarSlack() {
    setEnvio({ estado: "enviando" });
    try {
      await apiPost("/api/reports/send-slack", {});
      setEnvio({ estado: "ok" });
    } catch (e) {
      setEnvio({ estado: "erro", msg: e instanceof Error ? e.message : String(e) });
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">
          Relatórios
          <Hint area="growth/relatorios" titulo="_intro" />
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Estado atual da carteira — <b>mesma base do envio ao Slack</b>. Se o número muda aqui, muda
          no relatório do grupo junto.
        </p>
      </header>

      {q.loading && <LoadingSkeleton rows={5} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && (
        <>
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
            <Button onClick={enviarSlack} disabled={envio.estado === "enviando"}>
              <Send className="mr-1.5 h-4 w-4" />
              {envio.estado === "enviando" ? "Enviando…" : "Enviar ao Slack agora"}
            </Button>
            <span className={cn("text-sm",
              envio.estado === "ok" ? "text-success"
                : envio.estado === "erro" ? "text-destructive" : "text-muted-foreground")}>
              {envio.estado === "ok" ? "enviado ao grupo ✓"
                : envio.estado === "erro" ? (envio.msg || "falha no envio")
                  : "posta este resumo no grupo dos gestores"}
            </span>
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <KpiCard icon={Users} tone="primary" title="Contas monitoradas"
              value={formatNumber(d.resumo.monitoradas)}
              subtitle={`${d.resumo.avaliaveis} avaliáveis · ${d.resumo.sem_dados} sem dados`} />
            <KpiCard icon={AlertOctagon} tone="destructive" title="Alertas abertos"
              value={formatNumber(d.resumo.alertas_total)}
              subtitle={`${d.resumo.alertas.critico ?? 0} crítico · ${d.resumo.alertas.alto ?? 0} alto · ${d.resumo.alertas.atencao ?? 0} atenção`} />
            <KpiCard icon={ShieldAlert} tone="warning" title="MRR com alerta aberto"
              value={formatBRL(d.resumo.mrr_risco)}
              subtitle={`crítico: ${formatBRL(d.resumo.mrr_critico)}`} />
            <KpiCard icon={FileText} tone="muted" title="Execução crítica (ClickUp)"
              value={formatNumber(d.resumo.exec_atrasada)} subtitle="contas com entrega atrasada" />
          </div>

          <SectionCard hint={<Hint area="growth/relatorios" titulo="Piores contas" />}
            title="Piores contas" subtitle="menor score = pior · MRR quando conhecido">
            <ol className="divide-y divide-border">
              {d.resumo.piores.map((p, i) => (
                <li key={p.nome} className="flex items-baseline justify-between gap-3 py-2 text-sm">
                  <span className="min-w-0 truncate" title={p.nome}>
                    <b className="text-muted-foreground">{i + 1}.</b> {p.nome}
                  </span>
                  <span className="shrink-0 tabular-nums text-muted-foreground">
                    {p.score.toFixed(1)} · {d.stage_labels[p.estagio] ?? p.estagio}
                    {p.mrr ? ` · ${formatBRL(p.mrr)}` : ""}
                  </span>
                </li>
              ))}
            </ol>
          </SectionCard>

          <SectionCard hint={<Hint area="growth/relatorios" titulo="Distribuições" />}
            title="Distribuições" subtitle="faixa de risco · estágio · trajetória">
            <div className="grid gap-6 md:grid-cols-3">
              <Distribuicao titulo="Faixa de risco" dist={d.resumo.faixa}
                cores={COR_FAIXA} labels={LBL_FAIXA} />
              <Distribuicao titulo="Estágio" dist={d.resumo.estagio}
                cores={COR_ESTAGIO} labels={d.stage_labels} />
              <Distribuicao titulo="Trajetória" dist={d.resumo.trajetoria}
                cores={COR_TRAJ} labels={LBL_TRAJ} />
            </div>
          </SectionCard>

          <SectionCard hint={<Hint area="growth/relatorios" titulo="Relatório de Churn por Bundle" />}
            title="Relatório de Churn por Bundle"
            subtitle="dossiê apresentável por plano — casos, relacionamento, entrega e canal">
            <div className="flex flex-wrap items-center gap-2">
              {d.bundles_churn.map((b) => (
                <a key={b} href={`/growth/churn-report?b=${b}`} target="_blank" rel="noopener"
                  className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/40 px-4 py-2 text-sm font-semibold hover:border-primary/50 hover:text-primary">
                  Gerar {b}<ExternalLink className="h-3 w-3" />
                </a>
              ))}
            </div>
            {/* ressalva de custo: a 1ª geração é lenta e isso precisa estar dito ANTES do clique */}
            <p className="mt-3 text-xs text-muted-foreground">
              Abre em nova aba · a 1ª geração demora alguns minutos (analisa as mensagens do
              WhatsApp); depois fica em cache por 20h. Associação não é causa comprovada — use como
              pauta de investigação, não como veredito.
            </p>
          </SectionCard>

          {/* O Relatório de Assessoria (seleção de clientes + geração em lote)
              segue na tela anterior: é um fluxo de GERAÇÃO com estado de sessão,
              não uma visualização — registrado no PENDENCIAS para decidir. */}
          <SectionCard title="Relatório de Assessoria"
            subtitle="relatório mensal individual por cliente — faturamento, atividades e saúde">
            <p className="text-sm text-muted-foreground">
              A geração em lote ({d.contas.length} clientes disponíveis · mês de referência padrão{" "}
              {d.mes_referencia_padrao.split("-").reverse().join("/")}) continua na versão anterior
              desta tela.{" "}
              <a href="/growth?view=relatorios&legado=1" className="text-primary hover:underline">
                abrir
              </a>
            </p>
          </SectionCard>
        </>
      )}
    </div>
  );
}
