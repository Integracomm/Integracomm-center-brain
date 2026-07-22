import { ArrowRight } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";

// HOME ÚNICA (decidida pelo Otávio 22/07) — a tela inicial de TODOS.
// Resolve dois problemas anteriores à migração: (a) o gestor com várias áreas
// caía na 1ª em ordem ALFABÉTICA; (b) não tinha como trocar de área pela
// interface. O que aparece aqui vem de /api/home, que deriva das áreas
// liberadas para a conta (mesma régua do RBAC) — nada é fixo por papel.

export interface HomePayload {
  usuario: string;
  role: string;
  areas: Array<{ slug: string; nome: string; href: string }>;
  visoes: Array<{ slug: string; nome: string; href: string; descricao: string }>;
  admin: Array<{ slug: string; nome: string; href: string; descricao: string }>;
  focos: Array<{ team: string; team_label: string;
    acoes: Array<{ manchete: string; detalhe: string; objetivo: string | null }> }>;
}

// descrição de cada área — a mesma frase dos cards do hub antigo
const DESC: Record<string, string> = {
  growth: "carteira monitorada, alertas de risco, cancelamentos e playbooks de retenção",
  marketing: "tráfego pago, leads, funil de prospecção, metas do semestre e planejador",
  prevendas: "qualificação, speed-to-lead, melhor horário e a ponte para Vendas",
  vendas: "funil de fechamento, win/loss, ciclo e desempenho por closer",
  operacoes: "iniciativas por área da empresa (Notion) — semáforo de prazo e KPIs",
  financeiro: "planejamento × realizado: recebimento, bookings vs meta e receita recorrente",
};

function Atalho({ nome, href, descricao }: { nome: string; href: string; descricao: string }) {
  return (
    <a href={href}
      className="group flex items-start justify-between gap-3 rounded-xl border border-border p-4 hover:border-primary/50 hover:bg-muted/40">
      <div className="min-w-0">
        <div className="font-display text-sm font-semibold group-hover:text-primary">{nome}</div>
        <div className="mt-1 text-xs leading-snug text-muted-foreground">{descricao}</div>
      </div>
      <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground group-hover:text-primary" />
    </a>
  );
}

export function HomePage() {
  const q = useApi<HomePayload>("/api/home");
  const d = q.data;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-2xl font-bold tracking-tight">Início</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          O que você acompanha e o foco desta semana do seu time. Cada atalho abre o painel completo
          da área.
        </p>
      </header>

      {q.loading && <LoadingSkeleton rows={4} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}
      {d && (
        <>
          {/* o combinado da semana antes dos atalhos: é o que orienta a leitura */}
          {d.focos.length > 0 && (
            <SectionCard title="Seu foco desta semana"
              subtitle="as ações derivadas dos objetivos confirmados da empresa — o detalhe e o fechamento ficam em Ações da Semana">
              <div className="grid gap-3 md:grid-cols-2">
                {d.focos.map((f) => (
                  <div key={f.team} className="rounded-xl border border-border p-4">
                    <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {f.team_label}
                    </div>
                    <div className="mt-1.5 space-y-2">
                      {f.acoes.map((a, i) => (
                        <div key={i}>
                          <div className="text-sm font-medium leading-snug">{a.manchete}</div>
                          {a.detalhe && (
                            <div className="text-xs leading-snug text-muted-foreground">{a.detalhe}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs">
                <a href="/semana" className="text-primary hover:underline">abrir Ações da Semana →</a>
              </p>
            </SectionCard>
          )}

          {d.areas.length > 0 && (
            <SectionCard title="Suas áreas"
              subtitle="as áreas liberadas para a sua conta — o administrador define quais no Painel Administrativo">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {d.areas.map((a) => (
                  <Atalho key={a.slug} nome={a.nome} href={a.href}
                    descricao={DESC[a.slug] ?? "abrir o painel da área"} />
                ))}
              </div>
            </SectionCard>
          )}

          <SectionCard title="Visões da empresa"
            subtitle="cortes transversais dos dados — valem para todas as áreas, não só para a sua">
            <div className="grid gap-3 md:grid-cols-2">
              {d.visoes.map((v) => (
                <Atalho key={v.slug} nome={v.nome} href={v.href} descricao={v.descricao} />
              ))}
            </div>
          </SectionCard>

          {d.admin.length > 0 && (
            <SectionCard title="Admin"
              subtitle="a inteligência cross-área e a administração do painel">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {d.admin.map((a) => (
                  <Atalho key={a.slug} nome={a.nome} href={a.href} descricao={a.descricao} />
                ))}
              </div>
            </SectionCard>
          )}
        </>
      )}
    </div>
  );
}
