import { useEffect, useMemo, useState } from "react";
import { Check, Copy, KeyRound, Pencil } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { Hint } from "@/components/hint";
import { LoadingSkeleton, ErrorState } from "@/components/states";
import { SectionCard } from "@/components/blocks/section-card";
import { apiPost } from "@/api/client";

// Painel Administrativo — /api/admin/painel embrulha as MESMAS fontes da tela
// HTML (list_users + audit_log, llm_budget.month_summary, _teams_dados,
// _integracoes_status, pedidos_reset_abertos). Todas as mutações reusam os
// endpoints que já existiam: /api/users/{id}/{status,admin,areas,reset} e
// /api/admin/times. Só admin entra (o backend devolve 403).

interface Usuario {
  id: string; name: string; email: string; status: string; is_admin: boolean;
  areas: string[]; views: number; last_seen: string | null; eu: boolean;
}
interface Membro { nome: string; papel: string; papel_label: string; pipedrive: string }
interface Payload {
  eu: string;
  areas: Record<string, string>;
  papeis: Record<string, string>;
  usuarios: Usuario[];
  pedidos: Array<{ email: string; em: string }>;
  llm: { spent_usd: number; cap_usd: number; pct: number;
    por_funcao: Array<{ feature: string; label: string; chamadas: number; cost_usd: number }> } | null;
  times: Array<{ area: string; titulo: string; nota: string; membros: Membro[] }>;
  integracoes: { cobertura: string;
    fontes: Array<{ fonte: string; status: string; quando: string; ha: string; detalhe: string }> };
}

const FAROL: Record<string, string> = {
  verde: "bg-success", amarelo: "bg-warning", vermelho: "bg-destructive",
};
const ST_USER: Record<string, string> = {
  pendente: "border-warning/40 text-warning",
  aprovado: "border-success/40 text-success",
  bloqueado: "border-destructive/40 text-destructive",
};
const PD_DOT: Record<string, [string, string]> = {
  "ativo": ["bg-success", "ativo no Pipedrive"],
  "desativado": ["bg-destructive", "desativado no Pipedrive"],
  "sem dados": ["bg-muted-foreground/50", "sem deals no nome ainda"],
};

const btn = "cursor-pointer rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:border-primary hover:text-primary disabled:opacity-50";
const inputCls = "rounded-md border border-border bg-background px-2 py-1.5 text-sm";

// interruptor no estilo do painel (o HTML usava .tgl com --brand)
function Toggle({ on, disabled, title, onChange }: {
  on: boolean; disabled?: boolean; title?: string; onChange: (v: boolean) => void;
}) {
  return (
    <label title={title} className={`relative inline-block h-[21px] w-[38px] ${disabled ? "cursor-not-allowed opacity-45" : "cursor-pointer"}`}>
      <input type="checkbox" checked={on} disabled={disabled} className="h-0 w-0 opacity-0"
        onChange={(e) => onChange(e.target.checked)} />
      <span className={`absolute inset-0 rounded-full border transition-colors ${
        on ? "border-primary bg-primary" : "border-border bg-muted"}`}>
        <span className={`absolute top-[2px] h-[15px] w-[15px] rounded-full transition-all ${
          on ? "left-[18px] bg-primary-foreground" : "left-[3px] bg-muted-foreground"}`} />
      </span>
    </label>
  );
}

// Uso do assistente de IA por usuário (Fase 2/3, 27/07): sem esta visão, o
// gasto por pessoa só aparece na fatura — e a avaliação da Fase 3 ("o que o
// uso real mostrou faltar") depende de ver quem pergunta o quê.
interface UsoAssistente {
  mes: string; custo_mes_usd: number; chamadas_ao_modelo: number;
  limite_por_usuario_dia: number;
  por_usuario: Array<{ usuario: string; perguntas: number; custo_usd: number;
    ferramentas_mais_usadas: Array<[string, number]> }>;
}

function UsoDoAssistente() {
  const q = useApi<UsoAssistente>("/api/assistente/uso");
  const d = q.data;
  if (!d) return null;
  return (
    <SectionCard title="Assistente de IA — uso no mês"
      subtitle={`custo por usuário e ferramentas mais consultadas · teto de ${d.limite_por_usuario_dia} perguntas/usuário/dia (ASSISTENTE_PERGUNTAS_DIA)`}
      className="max-w-[560px]">
      <div className="flex items-baseline justify-between">
        <span className="font-display text-2xl font-bold tabular-nums">US$ {d.custo_mes_usd.toFixed(2)}</span>
        <span className="text-xs text-muted-foreground">{d.chamadas_ao_modelo} chamada(s) ao modelo</span>
      </div>
      <div className="mt-3">
        {d.por_usuario.length === 0 ? (
          <p className="py-1 text-xs text-muted-foreground">nenhuma pergunta neste mês ainda</p>
        ) : d.por_usuario.map((u) => (
          <div key={u.usuario} className="border-t border-border py-1.5 text-xs">
            <div className="flex justify-between gap-3">
              <span className="font-medium">{u.usuario} · {u.perguntas} pergunta(s)</span>
              <span className="tabular-nums">US$ {u.custo_usd.toFixed(2)}</span>
            </div>
            {u.ferramentas_mais_usadas.length > 0 && (
              <p className="mt-0.5 text-muted-foreground">
                {u.ferramentas_mais_usadas.map(([f, n]) => `${f} (${n})`).join(" · ")}
              </p>
            )}
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

function MedidorIA({ llm }: { llm: NonNullable<Payload["llm"]> }) {
  const cor = llm.pct < 0.7 ? "bg-success" : llm.pct < 0.9 ? "bg-warning" : "bg-destructive";
  return (
    <SectionCard title="Consumo de IA (Claude) no mês"
      subtitle="custo real por chamada, todas as áreas · ao atingir o teto as chamadas são bloqueadas automaticamente e os recursos caem no modo determinístico"
      className="max-w-[560px]">
      <div className="flex items-baseline justify-between">
        <span className="font-display text-2xl font-bold tabular-nums">US$ {llm.spent_usd.toFixed(2)}</span>
        <span className="text-xs text-muted-foreground">de US$ {llm.cap_usd.toFixed(2)}</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded bg-muted">
        <div className={`h-full ${cor}`} style={{ width: `${Math.min(100, llm.pct * 100)}%` }} />
      </div>
      <div className="mt-3">
        {llm.por_funcao.length === 0 ? (
          <p className="py-1 text-xs text-muted-foreground">nenhuma chamada à IA neste mês ainda</p>
        ) : llm.por_funcao.map((f) => (
          <div key={f.feature} className="flex justify-between gap-3 border-t border-border py-1.5 text-xs">
            <span>{f.label} · {f.chamadas} chamada(s)</span>
            <span className="tabular-nums">US$ {f.cost_usd.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

function Times({ d, recarrega }: { d: Payload; recarrega: () => void }) {
  const [editando, setEditando] = useState(false);
  const [novo, setNovo] = useState<Record<string, { nome: string; papel: string }>>({});
  const papeis = Object.entries(d.papeis);

  // mesma razão dos interruptores de Contas: trocar a função é um <select>
  // controlado, e esperar o refetch de ~3,3s fazia a escolha "voltar" sozinha
  const [times, setTimes] = useState(d.times);
  useEffect(() => setTimes(d.times), [d.times]);
  const patchArea = (area: string, fn: (ms: Membro[]) => Membro[]) =>
    setTimes((ts) => ts.map((t) => (t.area === area ? { ...t, membros: fn(t.membros) } : t)));

  const post = async (body: unknown, onErro?: () => void) => {
    try {
      await apiPost("/api/admin/times", body);
    } catch (e) {
      onErro?.();
      alert(e instanceof Error ? e.message : "falha de rede");
    }
  };
  const trocarPapel = (area: string, m: Membro, papel: string) => {
    patchArea(area, (ms) => ms.map((x) => (x.nome === m.nome
      ? { ...x, papel, papel_label: d.papeis[papel] ?? papel } : x)));
    post({ area, action: "papel", nome: m.nome, papel },
      () => patchArea(area, (ms) => ms.map((x) => (x.nome === m.nome ? m : x))));
  };
  const desligar = (area: string, m: Membro) => {
    const areaLbl = area === "vendas" ? "Vendas" : "Pré-vendas";
    let msg = `Desligar ${m.nome} de ${areaLbl}?\n\nA pessoa some de todas as telas do painel; os números dela permanecem nas réguas históricas do funil.`;
    if (m.pipedrive === "ativo") msg += "\n\n⚠ ATENÇÃO: este colaborador ainda está ATIVO no Pipedrive — confirme se o desligamento é mesmo agora.";
    if (!confirm(msg)) return;
    patchArea(area, (ms) => ms.filter((x) => x.nome !== m.nome));
    post({ area, action: "desligar", nome: m.nome },
      () => patchArea(area, (ms) => [...ms, m]));
  };

  return (
    <SectionCard title="Times por área"
      hint={<Hint area="admin" titulo="Times por área" />}
      subtitle="quem compõe cada time e a função de cada um · o ponto indica a situação do usuário no Pipedrive · editar libera: trocar função (promoção), desligar (com confirmação; some das telas, números preservados nas réguas) e adicionar colaborador"
      right={
        <button className={btn} onClick={() => setEditando((v) => !v)}>
          {editando ? "concluir edição" : <><Pencil className="mr-1 inline h-3 w-3" />editar</>}
        </button>
      }>
      <div className="flex flex-wrap gap-6">
        {times.map((t) => (
          <div key={t.area} className="min-w-[300px] flex-1">
            <b className="text-sm">{t.titulo}</b>
            <p className="mb-2 mt-1 text-xs text-muted-foreground">{t.nota}</p>
            <table className="w-full text-sm">
              <tbody>
                {t.membros.map((m) => (
                  <tr key={m.nome} className="border-b border-border">
                    <td className="py-2">
                      <span title={PD_DOT[m.pipedrive]?.[1]}
                        className={`mr-2 inline-block h-2 w-2 rounded-full ${PD_DOT[m.pipedrive]?.[0] ?? "bg-muted-foreground/50"}`} />
                      <b>{m.nome}</b>
                      {m.papel !== "membro" && (
                        <span className="ml-1.5 rounded-full border border-primary/40 px-1.5 py-0.5 text-[10px] text-primary">
                          {m.papel_label.toLowerCase()}
                        </span>
                      )}
                    </td>
                    <td className="py-2 text-muted-foreground">
                      {editando ? (
                        <select className={inputCls} value={m.papel}
                          onChange={(e) => trocarPapel(t.area, m, e.target.value)}>
                          {papeis.map(([v, lbl]) => <option key={v} value={v}>{lbl}</option>)}
                        </select>
                      ) : m.papel_label}
                    </td>
                    {editando && (
                      <td className="py-2 text-right">
                        <button className="cursor-pointer rounded-md border border-destructive/50 px-2 py-0.5 text-[11px] text-destructive hover:bg-destructive/10"
                          onClick={() => desligar(t.area, m)}>desligar</button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {editando && (
              <div className="mt-3 flex flex-wrap gap-2">
                <input className={`${inputCls} min-w-[170px] flex-1`} placeholder="nome como está no Pipedrive"
                  value={novo[t.area]?.nome ?? ""}
                  onChange={(e) => setNovo((s) => ({ ...s, [t.area]: { nome: e.target.value, papel: s[t.area]?.papel ?? "membro" } }))} />
                <select className={inputCls} value={novo[t.area]?.papel ?? "membro"}
                  onChange={(e) => setNovo((s) => ({ ...s, [t.area]: { nome: s[t.area]?.nome ?? "", papel: e.target.value } }))}>
                  {papeis.map(([v, lbl]) => <option key={v} value={v}>{lbl}</option>)}
                </select>
                <button className={btn} onClick={async () => {
                  const n = (novo[t.area]?.nome ?? "").trim();
                  if (!n) { alert("informe o nome como está no Pipedrive"); return; }
                  const papel = novo[t.area]?.papel ?? "membro";
                  // aparece na hora; o refetch depois traz o ponto REAL do
                  // Pipedrive (que só o servidor sabe)
                  patchArea(t.area, (ms) => [...ms, { nome: n, papel,
                    papel_label: d.papeis[papel] ?? papel, pipedrive: "sem dados" }]);
                  setNovo((s) => ({ ...s, [t.area]: { nome: "", papel: "membro" } }));
                  await post({ area: t.area, action: "add", nome: n, papel },
                    () => patchArea(t.area, (ms) => ms.filter((x) => x.nome !== n)));
                  recarrega();
                }}>+ adicionar</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

function Integracoes({ d }: { d: Payload }) {
  return (
    <SectionCard title="Saúde das integrações"
      hint={<Hint area="admin" titulo="Saúde das integrações" />}
      subtitle="última sincronização por fonte · verde = dentro do esperado, amarelo = atrasada, vermelho = parada/falhou — fonte quebrada em silêncio = gestor decidindo com dado velho">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
              <th className="py-2 text-left">Fonte</th>
              <th className="py-2 text-right">Última sync</th>
              <th className="py-2 text-left">Detalhe</th>
            </tr>
          </thead>
          <tbody>
            {d.integracoes.fontes.map((f) => (
              <tr key={f.fonte} className="border-b border-border">
                <td className="py-2">
                  <span className={`mr-2 inline-block h-2 w-2 rounded-full ${FAROL[f.status] ?? "bg-muted-foreground/50"}`} />
                  <b>{f.fonte}</b>
                </td>
                <td className="whitespace-nowrap py-2 text-right">
                  {f.quando}{f.ha && <span className="text-muted-foreground/70"> ({f.ha})</span>}
                </td>
                <td className="py-2 text-muted-foreground">{f.detalhe}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d.integracoes.cobertura && (
        <p className="mt-3 text-xs text-muted-foreground">Cobertura: {d.integracoes.cobertura}.</p>
      )}
    </SectionCard>
  );
}

function Contas({ d }: { d: Payload }) {
  const [busca, setBusca] = useState("");
  const [link, setLink] = useState<{ email: string; link: string; min: number } | null>(null);
  const [copiado, setCopiado] = useState(false);
  const slugs = Object.keys(d.areas);

  // Os interruptores são OTIMISTAS: o estado muda na hora e o POST vai atrás
  // (revertendo se falhar). Sem isto eles pareciam quebrados — o checkbox era
  // controlado pelo payload e cada clique disparava um refetch de ~3,3s do
  // /api/admin/painel, então o React re-renderizava com o dado ANTIGO e o
  // interruptor "voltava" sozinho. O HTML não tinha o problema porque o
  // checkbox era não-controlado e a página dava reload inteiro.
  const [usuarios, setUsuarios] = useState<Usuario[]>(d.usuarios);
  useEffect(() => setUsuarios(d.usuarios), [d.usuarios]);
  const patch = (id: string, fn: (u: Usuario) => Usuario) =>
    setUsuarios((us) => us.map((u) => (u.id === id ? fn(u) : u)));

  const filtrados = useMemo(() => {
    const q = busca.toLowerCase();
    return usuarios.filter((u) => `${u.name} ${u.email}`.toLowerCase().includes(q));
  }, [usuarios, busca]);

  const erro = (e: unknown) => alert(e instanceof Error ? e.message : "falha de rede");
  const setStatus = async (u: Usuario, status: string) => {
    if (status === "bloqueado" && !confirm("Bloquear esta conta?")) return;
    const antes = u.status;
    patch(u.id, (x) => ({ ...x, status }));
    try {
      await apiPost(`/api/users/${u.id}/status`, { status });
    } catch (e) {
      patch(u.id, (x) => ({ ...x, status: antes }));
      erro(e);
    }
  };
  const setAdmin = async (u: Usuario, v: boolean) => {
    if (v && !confirm("Tornar esta conta ADMINISTRADORA? Ela passa a ver a Central, o Painel Administrativo, as Ações da Semana e todas as áreas.")) return;
    patch(u.id, (x) => ({ ...x, is_admin: v }));
    try {
      await apiPost(`/api/users/${u.id}/admin`, { admin: v });
    } catch (e) {
      patch(u.id, (x) => ({ ...x, is_admin: !v }));
      erro(e);
    }
  };
  const setAreas = async (u: Usuario, slug: string, on: boolean) => {
    const areas = on ? [...u.areas, slug] : u.areas.filter((a) => a !== slug);
    const antes = u.areas;
    patch(u.id, (x) => ({ ...x, areas }));
    try {
      await apiPost(`/api/users/${u.id}/areas`, { areas });
    } catch (e) {
      patch(u.id, (x) => ({ ...x, areas: antes }));
      erro(e);
    }
  };
  const gerarLink = async (u: Usuario) => {
    if (!confirm("Gerar um link de redefinição de senha para esta conta? O link vale 30 minutos, só pode ser usado uma vez e invalida qualquer link anterior.")) return;
    try {
      const j = await apiPost<{ email: string; link: string; validade_min: number }>(`/api/users/${u.id}/reset`);
      setLink({ email: j.email, link: j.link, min: j.validade_min });
      setCopiado(false);
    } catch (e) { erro(e); }
  };

  return (
    <SectionCard title="Contas e permissões"
      hint={<Hint area="admin" titulo="Contas e permissões" />}
      subtitle="pendentes primeiro · os interruptores aplicam NA HORA (vale em até 60s) · busca por nome/e-mail">

      {d.pedidos.length > 0 && (
        <div className="mb-3 rounded-lg border-l-2 border-primary bg-muted/30 p-3">
          <div className="font-display font-semibold">🔑 {d.pedidos.length} pedido(s) de redefinição de senha</div>
          {d.pedidos.map((p) => (
            <div key={p.email} className="py-1 text-sm">
              <b>{p.email}</b> <span className="text-muted-foreground">· pediu em {p.em}</span>
            </div>
          ))}
          <p className="mt-1.5 text-xs text-muted-foreground">
            Use o botão <b>senha</b> na linha da conta para gerar um link de uso único (vale 30 min) e envie
            você mesmo à pessoa — por WhatsApp, Slack ou outro canal que você já use com ela.
          </p>
        </div>
      )}

      {/* o HTML mostrava o link num window.prompt; aqui ele fica copiável */}
      {link && (
        <div className="mb-3 rounded-lg border border-primary/40 bg-primary/5 p-3">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <KeyRound className="h-4 w-4 text-primary" />
            Link de redefinição para {link.email}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Vale {link.min} minutos e só funciona UMA vez — copie e envie à pessoa.
          </p>
          <div className="mt-2 flex gap-2">
            <input readOnly value={link.link} onFocus={(e) => e.currentTarget.select()}
              className={`${inputCls} flex-1 font-mono text-xs`} />
            <button className={btn} onClick={() => {
              navigator.clipboard?.writeText(link.link).then(() => setCopiado(true)).catch(() => {});
            }}>
              {copiado ? <><Check className="mr-1 inline h-3 w-3" />copiado</> : <><Copy className="mr-1 inline h-3 w-3" />copiar</>}
            </button>
            <button className={btn} onClick={() => setLink(null)}>fechar</button>
          </div>
        </div>
      )}

      {usuarios.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          nenhuma conta criada ainda — os gestores usam “Criar sua conta” na tela de login
        </p>
      ) : (
        <>
          <input className={`${inputCls} w-full max-w-[420px]`} value={busca}
            placeholder="pesquisar por nome ou e-mail…" onChange={(e) => setBusca(e.target.value)} />
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="whitespace-nowrap px-3 py-2 text-left">Usuário</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left">Status</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left">Acessos</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left">Último login</th>
                  <th className="whitespace-nowrap px-3 py-2 text-center text-primary">Admin</th>
                  {slugs.map((s) => (
                    <th key={s} className="whitespace-nowrap px-3 py-2 text-center">{d.areas[s].split(" /")[0]}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtrados.map((u) => (
                  <tr key={u.id} className="border-b border-border">
                    <td className="px-3 py-2.5">
                      <b>{u.name.slice(0, 34)}</b>
                      <br />
                      <span className="text-xs text-muted-foreground">{u.email.slice(0, 44)}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`rounded-full border px-2 py-0.5 text-[11px] ${ST_USER[u.status] ?? "border-border text-muted-foreground"}`}>
                        {u.status}
                      </span>
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {u.status !== "aprovado" && <button className={btn} onClick={() => setStatus(u, "aprovado")}>aprovar</button>}
                        {u.status !== "bloqueado" && <button className={btn} onClick={() => setStatus(u, "bloqueado")}>bloquear</button>}
                        <button className={btn} onClick={() => gerarLink(u)}>senha</button>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 tabular-nums">{u.views}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 tabular-nums">{u.last_seen ?? "—"}</td>
                    <td className="px-3 py-2.5 text-center">
                      <Toggle on={u.is_admin} disabled={u.eu}
                        title={u.eu ? "seu próprio acesso" : "acesso de administrador"}
                        onChange={(v) => setAdmin(u, v)} />
                    </td>
                    {/* conta admin enxerga tudo: os interruptores de área ficam
                        travados p/ não prometerem um recorte que o papel ignora */}
                    {slugs.map((s) => (
                      <td key={s} className="px-3 py-2.5 text-center">
                        <Toggle on={u.is_admin || u.areas.includes(s)} disabled={u.is_admin}
                          onChange={(v) => setAreas(u, s, v)} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </SectionCard>
  );
}

export function AdminPage() {
  const q = useApi<Payload>("/api/admin/painel");
  const d = q.data;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-2xl font-bold tracking-tight">Painel Administrativo</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          controle de acessos por conta — aprovar/bloquear cadastros e definir quais áreas cada usuário enxerga
        </p>
      </header>

      {/* skeleton SÓ na 1ª carga: em refetch o `d` anterior segue na tela
          (senão a página piscava um esqueleto por cima do conteúdo) */}
      {q.loading && !d && <LoadingSkeleton rows={5} />}
      {q.error && <ErrorState message={q.error} onRetry={q.refetch} />}

      {d && (
        <>
          {d.llm && <MedidorIA llm={d.llm} />}
          <UsoDoAssistente />
          <Times d={d} recarrega={q.refetch} />
          <Integracoes d={d} />
          <Contas d={d} />
        </>
      )}
    </div>
  );
}
