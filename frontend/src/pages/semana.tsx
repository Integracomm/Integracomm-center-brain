import { Check, Plus, RotateCw, X } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

// Ações da Semana (Lote 5) — /api/semana/painel devolve o ESTADO INTEIRO com
// a MESMA orquestração do handler HTML (inclusive a prévia da decomposição
// antes de confirmar). As ações de ESCRITA vão para o POST /semana/salvar já
// existente — mesma regra do form de metas do funil: o SPA não duplica lógica.

interface Objetivo {
  id: string; title: string; metric: string | null; target: number | null;
  rationale: string | null; source: string; status: string; times: string[];
}
interface Acao {
  team: string; team_label: string; objetivo: string; manchete: string;
  detalhe: string; links: Array<{ url: string; label: string }>; lag: string | null;
}
interface Payload {
  week: string; week_label: string; week_anterior_label: string;
  edita: boolean; confirmada: boolean;
  objetivos: Objetivo[]; acoes: Acao[]; times_ordem: string[];
  revisao: Array<{ objetivo: string; nota: string; maturacao: boolean }>;
  metricas: Array<{ v: string; lbl: string }>;
}

export function SemanaPage() {
  const q = useApi<Payload>("/api/semana/painel");
  const d = q.data;
  const [titulo, setTitulo] = useState("");
  const [metric, setMetric] = useState("");
  const [enviando, setEnviando] = useState("");

  // POST no MESMO endpoint da tela HTML (form-encoded) e refetch
  const salvar = async (acao: string, extra: Record<string, string> = {}) => {
    setEnviando(acao);
    const body = new URLSearchParams({ acao, ...extra });
    await fetch("/semana/salvar", { method: "POST", body, credentials: "same-origin" });
    setEnviando("");
    if (acao === "add") { setTitulo(""); setMetric(""); }
    q.refetch();
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">Ações da Semana<Hint area="semana" titulo="_intro" /></h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Os objetivos da EMPRESA na semana e o foco de cada time derivado deles. O sistema propõe a
          partir dos gaps já medidos; o admin edita e CONFIRMA — nada vira foco de time sem confirmação
          humana. As ações citam dados reais e a defasagem esperada de cada correção.
        </p>
      </header>

      {q.loading && <LoadingSkeleton rows={6} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && (
        <>
          <SectionCard hint={<Hint area="semana" titulo="Objetivos da semana" />}
            title={`Objetivos da semana de ${d.week_label}`}
            subtitle="o objetivo central da empresa em cima; abaixo de cada um, as áreas que o puxam — os focos por área CONVERSAM entre si para chegar no objetivo comum">
            <div className="mb-3">
              {d.confirmada ? (
                <Badge variant="outline" className="border-success/50 text-success">semana CONFIRMADA</Badge>
              ) : (
                <Badge variant="outline" className="border-warning/50 text-warning">proposta — pendente de confirmação</Badge>
              )}
            </div>

            {d.objetivos.length === 0 && (
              <p className="text-sm text-muted-foreground">
                Sem gaps relevantes detectados — adicione um objetivo manual se necessário.
              </p>
            )}
            <div className="space-y-1">
              {d.objetivos.map((o) => (
                <div key={o.id} className="border-t border-border py-2.5 first:border-t-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <b className="text-sm">{o.title}</b>
                    <Badge variant="outline"
                      className={o.status === "confirmado" ? "border-success/50 text-success" : "border-warning/50 text-warning"}>
                      {o.status}
                    </Badge>
                    {d.edita && !d.confirmada && (
                      <button onClick={() => salvar("del", { obj_id: o.id })}
                        title="remover objetivo"
                        className="text-destructive hover:opacity-70" disabled={!!enviando}>
                        <X className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                  <div className="mt-0.5 text-sm text-muted-foreground">
                    {o.rationale}
                    <span className="text-muted-foreground/70">
                      {" "}· {o.source === "sistema" ? "proposto pelo sistema" : o.source === "manual" ? "adicionado manualmente" : o.source}
                    </span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px]">
                    {o.times.length ? (
                      <>
                        <span className="text-muted-foreground/70">áreas que puxam este objetivo:</span>
                        {o.times.map((t) => <Badge key={t} variant="outline" className="text-muted-foreground">{t}</Badge>)}
                      </>
                    ) : (
                      <span className="text-muted-foreground/70">
                        nenhuma área com alavanca direta detectada — objetivo estratégico/manual
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {d.edita && (
              <div className="mt-4 space-y-3 border-t border-border pt-4">
                {!d.confirmada ? (
                  <>
                    <div className="flex flex-wrap gap-2">
                      <Button onClick={() => salvar("confirmar")} disabled={!!enviando}>
                        <Check className="mr-1 h-4 w-4" />
                        {enviando === "confirmar" ? "Confirmando…" : "Confirmar objetivos e gerar o foco dos times"}
                      </Button>
                      <Button variant="outline" onClick={() => salvar("repropor")} disabled={!!enviando}>
                        <RotateCw className="mr-1 h-4 w-4" /> repropor do zero
                      </Button>
                    </div>
                    <div className="flex flex-wrap items-end gap-3">
                      <label className="min-w-[260px] flex-1 text-xs uppercase text-muted-foreground">
                        objetivo manual (curto e mensurável)
                        <Input className="mt-1" maxLength={90} placeholder="ex.: Fechar +2 B4"
                          value={titulo} onChange={(e) => setTitulo(e.target.value)} />
                      </label>
                      <label className="text-xs uppercase text-muted-foreground">
                        métrica
                        <Select value={metric || "__livre"} onValueChange={(v) => setMetric(v === "__livre" ? "" : v)}>
                          <SelectTrigger className="mt-1 w-[180px]"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {d.metricas.map((m) => (
                              <SelectItem key={m.v || "__livre"} value={m.v || "__livre"}>{m.lbl}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </label>
                      <Button variant="outline" disabled={!titulo.trim() || !!enviando}
                        onClick={() => salvar("add", { titulo, metric })}>
                        <Plus className="mr-1 h-4 w-4" /> adicionar
                      </Button>
                    </div>
                  </>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" onClick={() => salvar("decompor")} disabled={!!enviando}>
                      <RotateCw className="mr-1 h-4 w-4" /> regenerar o foco dos times
                    </Button>
                    <Button variant="outline" onClick={() => salvar("reabrir")} disabled={!!enviando}>
                      reabrir objetivos
                    </Button>
                  </div>
                )}
              </div>
            )}
          </SectionCard>

          {d.objetivos.length > 0 && d.acoes.length > 0 && (
            <SectionCard hint={<Hint area="semana" titulo="Foco por área" />}
              title={`Foco por área${d.confirmada ? "" : " — prévia"}`}
              subtitle={(d.confirmada
                ? "derivado dos objetivos confirmados — "
                : "PRÉVIA calculada da proposta acima (será efetivada na confirmação; muda se você editar os objetivos) — ")
                + "só áreas com alavanca real; máx. 2 ações por área; cada ação diz para QUAL objetivo contribui, com o dado que a fundamenta, o link de execução e a defasagem esperada"}>
              <div className="space-y-4">
                {d.times_ordem
                  .filter((t) => d.acoes.some((a) => a.team === t))
                  .map((t) => {
                    const doTime = d.acoes.filter((a) => a.team === t);
                    return (
                      <div key={t} className="rounded-xl border border-border p-4">
                        <b className="font-display text-sm">{doTime[0].team_label}</b>
                        {doTime.map((a, i) => (
                          <div key={`${t}-${i}`} className="border-t border-border pt-2.5 mt-2.5 first-of-type:mt-2">
                            <div className="text-[10px] uppercase tracking-wide text-primary">
                              contribui para: {a.objetivo}
                            </div>
                            <div className="mt-0.5 text-sm font-semibold leading-snug">{a.manchete}</div>
                            {a.detalhe && (
                              <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{a.detalhe}</div>
                            )}
                            <div className="mt-1 flex flex-wrap gap-3">
                              {a.links.map((l) => (
                                <a key={l.url} href={l.url} className="text-[11px] text-primary hover:underline">
                                  {l.label} →
                                </a>
                              ))}
                            </div>
                            {a.lag && (
                              <div className="mt-1 text-[10px] text-muted-foreground/70">defasagem: {a.lag}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    );
                  })}
              </div>
            </SectionCard>
          )}

          {d.objetivos.length > 0 && d.acoes.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Nenhum time com alavanca real sobre os objetivos atuais — revise os objetivos.
            </p>
          )}

          {d.revisao.length > 0 && (
            <SectionCard hint={<Hint area="semana" titulo="Fechamento da semana anterior" />}
              title={`Fechamento da semana anterior (${d.week_anterior_label})`}
              subtitle="o que era o objetivo × o que mexeu no número — leitura de aprendizado, não auditoria; defasagens respeitadas (churn não “falha” numa semana)">
              <div className="space-y-1">
                {d.revisao.map((r) => (
                  <div key={r.objetivo} className="border-t border-border py-2 text-sm first:border-t-0">
                    <b>{r.objetivo}</b> — {r.nota}
                    {r.maturacao && (
                      <Badge variant="outline" className="ml-2 text-muted-foreground">em maturação</Badge>
                    )}
                  </div>
                ))}
              </div>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}
