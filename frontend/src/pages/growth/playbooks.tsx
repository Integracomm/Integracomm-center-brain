import { BookOpen, CheckCircle2 } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

// Growth · Playbooks (Lote 6) — /api/growth/playbooks embrulha `_top_practices`
// e `_recent_interventions`, que já eram funções puras (nada foi extraído).
//
// A tela é o ciclo de aprendizado: ação registrada com um cliente + desfecho
// RETIDO vira prática de referência, e passa a ser citada na diretriz de casos
// futuros com a mesma dor.

interface Payload {
  praticas: Array<{ driver: string; driver_label: string; acao: string; reteve: number }>;
  acoes: Array<{ conta: string; acao: string; desfecho: string | null;
    driver: string | null; quando: string }>;
}

const th = "text-xs font-semibold uppercase tracking-wide text-muted-foreground";
// cor SEMPRE com rótulo — o desfecho é escrito por extenso
const DESFECHO: Record<string, { label: string; cls: string }> = {
  retido: { label: "Retido", cls: "bg-success/15 text-success" },
  cancelou: { label: "Cancelou", cls: "bg-destructive/15 text-destructive" },
  sem_efeito: { label: "Sem efeito", cls: "bg-muted text-muted-foreground" },
};

export function GrowthPlaybooksPage() {
  const q = useApi<Payload>("/api/growth/playbooks");
  const d = q.data;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display inline-flex items-center gap-2 text-2xl font-bold tracking-tight">
          Playbooks
          <Hint area="growth/playbooks" titulo="_intro" />
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Boas práticas aprendidas com clientes reais. Toda ação registrada vira aprendizado: quando
          o desfecho é <b>retido</b>, a prática entra aqui e passa a ser citada na diretriz de casos
          futuros com a mesma dor.
        </p>
      </header>

      {q.loading && <LoadingSkeleton rows={3} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && (
        <>
          <SectionCard hint={<Hint area="growth/playbooks" titulo="Práticas de referência" />}
            title="Práticas de referência"
            subtitle="a ação que mais reteve, por dor">
            {d.praticas.length === 0 ? (
              // vazio com CAMINHO: diz o que fazer para a seção acender
              <div className="rounded-xl border border-dashed border-border p-8 text-center">
                <BookOpen className="mx-auto h-6 w-6 text-muted-foreground" />
                <div className="mt-2 font-semibold">Nenhuma prática validada ainda</div>
                <p className="mx-auto mt-1 max-w-lg text-sm leading-relaxed text-muted-foreground">
                  Registre as ações tomadas com cada cliente e feche o desfecho (retido / cancelou /
                  sem efeito). As que retiveram aparecem aqui e passam a orientar os próximos casos
                  parecidos.
                </p>
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {d.praticas.map((p) => (
                  <div key={p.driver} className="rounded-xl border border-border p-4">
                    <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      {p.driver_label}
                    </div>
                    <div className="mt-2 font-display text-sm font-semibold leading-snug">
                      “{p.acao}”
                    </div>
                    <Badge className="mt-3 border-0 bg-success/15 text-success">
                      <CheckCircle2 className="mr-1 h-3 w-3" />
                      reteve {p.reteve}×
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>

          {d.acoes.length > 0 && (
            <SectionCard hint={<Hint area="growth/playbooks" titulo="Ações recentes" />}
              title="Ações recentes" subtitle="últimos registros">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <TableHead className={th}>Conta</TableHead>
                    <TableHead className={th}>Ação</TableHead>
                    <TableHead className={th}>Desfecho</TableHead>
                    <TableHead className={th}>Quando</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.acoes.map((a, i) => {
                    const st = a.desfecho ? DESFECHO[a.desfecho] : null;
                    return (
                      <TableRow key={`${a.conta}-${i}`}>
                        <TableCell className="max-w-[260px] truncate font-medium" title={a.conta}>
                          {a.conta}
                        </TableCell>
                        <TableCell className="max-w-[380px] truncate text-sm text-muted-foreground"
                          title={a.acao}>
                          {a.acao}
                        </TableCell>
                        <TableCell>
                          <Badge className={cn("border-0", st?.cls ?? "bg-warning/15 text-warning")}>
                            {st?.label ?? "Pendente"}
                          </Badge>
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-sm tabular-nums">{a.quando}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}
