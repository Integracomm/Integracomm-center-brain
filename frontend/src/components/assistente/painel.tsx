import {
  Bot, Check, Copy, CornerDownLeft, Download, Loader2, MessageSquarePlus,
  Printer, Sparkles, ThumbsDown, X,
} from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import { Md } from "./md";

// Assistente de IA — consultor SOMENTE LEITURA (Fase 1, 27/07). O botão só
// aparece para quem o backend liberar (/api/assistente/status — piloto: admin).
// A conversa vive na sessão do navegador; nada é salvo como relatório oficial.

interface Msg {
  role: "user" | "assistant";
  content: string;
  consultas?: string[];   // rótulos das ferramentas usadas nesta resposta
}

interface Status {
  disponivel: boolean;
  motivo?: string;
  sugestoes?: string[];
  restantes_hoje?: number;
}

interface Conversa { id: string; titulo: string; msgs: Msg[] }

// Conversas ficam no navegador de QUEM perguntou (sessionStorage): nada vai
// para o servidor, então a conversa de um gestor não aparece para outro.
// sessionStorage e não localStorage: some ao fechar a aba — dado de negócio
// não fica esquecido num computador compartilhado.
const CHAVE = "assistente:conversas";

function carrega(): Conversa[] {
  try {
    const raw = sessionStorage.getItem(CHAVE);
    const v = raw ? JSON.parse(raw) : null;
    return Array.isArray(v) && v.length ? v : [{ id: "1", titulo: "Nova conversa", msgs: [] }];
  } catch {
    return [{ id: "1", titulo: "Nova conversa", msgs: [] }];
  }
}

export function AssistentePainel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [aberto, setAberto] = useState(false);
  const [conversas, setConversas] = useState<Conversa[]>(carrega);
  const [atualId, setAtualId] = useState<string>(() => carrega()[0].id);
  const msgs = conversas.find((c) => c.id === atualId)?.msgs ?? [];
  const setMsgs = (fn: Msg[] | ((m: Msg[]) => Msg[])) =>
    setConversas((cs) => cs.map((c) => c.id === atualId
      ? { ...c, msgs: typeof fn === "function" ? fn(c.msgs) : fn } : c));
  const [rascunho, setRascunho] = useState("");
  const [gerando, setGerando] = useState(false);
  const [atividade, setAtividade] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [copiado, setCopiado] = useState<number | null>(null);
  const fimRef = useRef<HTMLDivElement>(null);

  // relatórios vivem NA CONVERSA (nada é salvo como relatório oficial) — os
  // botões de copiar/baixar são o caminho de guardar o texto
  function copiar(i: number, texto: string) {
    navigator.clipboard.writeText(texto).then(() => {
      setCopiado(i);
      setTimeout(() => setCopiado(null), 1500);
    });
  }
  function baixar(texto: string) {
    const blob = new Blob([texto], { type: "text/markdown;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `assistente-integracomm-${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  useEffect(() => {
    fetch("/api/assistente/status", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    fimRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, atividade]);

  useEffect(() => {
    try { sessionStorage.setItem(CHAVE, JSON.stringify(conversas)); } catch { /* cota cheia */ }
  }, [conversas]);

  function novaConversa() {
    const id = String(Date.now());
    setConversas((cs) => [...cs, { id, titulo: "Nova conversa", msgs: [] }]);
    setAtualId(id);
    setErro(null);
  }

  function fecharConversa(id: string) {
    setConversas((cs) => {
      const restantes = cs.filter((c) => c.id !== id);
      const finais = restantes.length ? restantes : [{ id: "1", titulo: "Nova conversa", msgs: [] }];
      if (id === atualId) setAtualId(finais[0].id);
      return finais;
    });
  }

  // PDF sem dependência nova: janela de impressão do navegador ("Salvar como
  // PDF"). O mesmo caminho que a apresentação do All Hands já usa.
  function imprimir(texto: string) {
    const w = window.open("", "_blank", "width=820,height=900");
    if (!w) return;
    const esc = (s: string) => s.replace(/[&<>]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c] as string));
    w.document.write(`<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<title>Assistente Integracomm — ${new Date().toLocaleDateString("pt-BR")}</title>
<style>body{font:13px/1.6 system-ui,sans-serif;color:#111;max-width:760px;margin:28px auto;padding:0 20px}
pre{white-space:pre-wrap;font:inherit}h1{font-size:17px}
@media print{@page{margin:16mm}}</style></head><body>
<h1>Assistente Integracomm</h1>
<p style="color:#666;font-size:11px">Gerado por IA a partir dos dados do painel em
${new Date().toLocaleString("pt-BR")} — confira números críticos na tela de origem.</p>
<hr><pre>${esc(texto)}</pre></body></html>`);
    w.document.close();
    w.focus();
    setTimeout(() => w.print(), 300);
  }

  async function enviarFeedback(m: Msg, pergunta: string) {
    const comentario = window.prompt(
      "O que faltou nesta resposta? (vai para o administrador virar melhoria — "
      + "descreva o dado ou a análise que você precisava)");
    if (comentario === null) return;
    await fetch("/api/assistente/feedback", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ util: false, categoria: "faltou_dado",
        comentario, pergunta, ferramentas: m.consultas ?? [] }),
    }).catch(() => null);
    setErro(null);
    alert("Registrado. Obrigado — isso vira melhoria no painel.");
  }

  if (!status?.disponivel) return null;

  async function enviar(pergunta: string) {
    const p = pergunta.trim();
    if (!p || gerando) return;
    setErro(null);
    setRascunho("");
    setGerando(true);
    const historico = [...msgs, { role: "user" as const, content: p }];
    setMsgs([...historico, { role: "assistant", content: "", consultas: [] }]);
    // a 1ª pergunta nomeia a conversa (para achar entre várias)
    setConversas((cs) => cs.map((c) => c.id === atualId && c.msgs.length === 0
      ? { ...c, titulo: p.slice(0, 38) + (p.length > 38 ? "…" : "") } : c));
    try {
      const resp = await fetch("/api/assistente/chat", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mensagens: historico.map(({ role, content }) => ({ role, content })),
          tela: window.location.pathname + window.location.search,
        }),
      });
      if (!resp.ok || !resp.body) {
        const e = await resp.json().catch(() => null);
        throw new Error(e?.error || `HTTP ${resp.status}`);
      }
      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        // SSE: eventos separados por linha em branco; chunk pode cortar no meio
        const partes = buf.split("\n\n");
        buf = partes.pop() ?? "";
        for (const parte of partes) {
          const linha = parte.split("\n").find((l) => l.startsWith("data: "));
          if (!linha) continue;
          const ev = JSON.parse(linha.slice(6));
          if (ev.tipo === "texto") {
            setAtividade(null);
            setMsgs((cur) => {
              const novo = [...cur];
              const ult = { ...novo[novo.length - 1] };
              ult.content += ev.delta;
              novo[novo.length - 1] = ult;
              return novo;
            });
          } else if (ev.tipo === "ferramenta") {
            setAtividade(ev.rotulo);
            setMsgs((cur) => {
              const novo = [...cur];
              const ult = { ...novo[novo.length - 1] };
              ult.consultas = [...(ult.consultas ?? []), ev.rotulo.replace("consultando ", "").replace("…", "")];
              novo[novo.length - 1] = ult;
              return novo;
            });
          } else if (ev.tipo === "fim") {
            setStatus((s) => (s ? { ...s, restantes_hoje: ev.restantes_hoje } : s));
          } else if (ev.tipo === "erro") {
            throw new Error(ev.mensagem);
          }
        }
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : "falha na consulta");
      // resposta vazia não fica pendurada na conversa
      setMsgs((cur) => (cur[cur.length - 1]?.content === "" ? cur.slice(0, -1) : cur));
    } finally {
      setAtividade(null);
      setGerando(false);
    }
  }

  return (
    <>
      {/* botão fixo — não compete com o cockpit */}
      <button
        onClick={() => setAberto(true)}
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full border border-border bg-card px-4 py-2.5 text-sm font-medium shadow-lg transition-colors hover:border-primary/60"
        aria-label="Abrir assistente de IA">
        <Sparkles className="h-4 w-4 text-primary" /> Assistente
      </button>

      <Sheet open={aberto} onOpenChange={setAberto}>
        <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-xl">
          <SheetHeader className="border-b border-border px-4 py-3">
            <SheetTitle className="flex items-center gap-2 text-base">
              <Bot className="h-4 w-4 text-primary" /> Assistente da Integracomm
            </SheetTitle>
            <SheetDescription className="text-xs">
              Conteúdo gerado por IA a partir dos dados do painel — só consulta, nunca altera.
              Confira números críticos na tela de origem.
              {typeof status.restantes_hoje === "number" && (
                <> · {status.restantes_hoje} pergunta(s) restante(s) hoje</>
              )}
            </SheetDescription>
          </SheetHeader>

          {/* conversas paralelas: assuntos distintos não se misturam no
              histórico (cada uma tem o próprio contexto) */}
          <div className="flex items-center gap-1 overflow-x-auto border-b border-border px-3 py-1.5">
            {conversas.map((c) => (
              <div key={c.id}
                className={`group flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs ${
                  c.id === atualId ? "bg-muted font-medium" : "text-muted-foreground hover:bg-muted/50"}`}>
                <button onClick={() => setAtualId(c.id)} className="max-w-[150px] truncate">
                  {c.titulo}
                </button>
                {conversas.length > 1 && (
                  <button onClick={() => fecharConversa(c.id)} aria-label="Fechar conversa"
                    className="opacity-0 transition-opacity group-hover:opacity-100">
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
            ))}
            <button onClick={novaConversa} title="Nova conversa"
              className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs text-primary hover:bg-primary/10">
              <MessageSquarePlus className="h-3.5 w-3.5" /> nova
            </button>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
            {msgs.length === 0 && (
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">
                  Pergunte sobre qualquer área — eu consulto os mesmos dados das telas e
                  respondo com fonte. Exemplos:
                </p>
                {(status.sugestoes ?? []).map((s) => (
                  <button key={s} onClick={() => enviar(s)}
                    className="block w-full rounded-lg border border-border bg-card px-3 py-2 text-left text-sm transition-colors hover:border-primary/50">
                    {s}
                  </button>
                ))}
              </div>
            )}

            {msgs.map((m, i) => (
              <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
                {m.role === "user" ? (
                  <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary/10 px-3.5 py-2 text-sm">
                    {m.content}
                  </div>
                ) : (
                  <div className="max-w-full">
                    {m.consultas && m.consultas.length > 0 && (
                      <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                        fontes: {[...new Set(m.consultas)].join(" · ")}
                      </p>
                    )}
                    <Md texto={m.content} />
                    {m.content && !(gerando && i === msgs.length - 1) && (
                      <div className="mt-1.5 flex gap-1">
                        <button onClick={() => copiar(i, m.content)} title="Copiar (markdown)"
                          className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground">
                          {copiado === i ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
                          {copiado === i ? "copiado" : "copiar"}
                        </button>
                        <button onClick={() => baixar(m.content)} title="Baixar como .md"
                          className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground">
                          <Download className="h-3 w-3" /> .md
                        </button>
                        <button onClick={() => imprimir(m.content)} title="Imprimir ou salvar como PDF"
                          className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground">
                          <Printer className="h-3 w-3" /> PDF
                        </button>
                        <button
                          onClick={() => enviarFeedback(m, msgs[i - 1]?.content ?? "")}
                          title="Faltou algo nesta resposta? conte ao administrador"
                          className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:text-warning">
                          <ThumbsDown className="h-3 w-3" /> faltou algo
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}

            {atividade && (
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> {atividade}
              </p>
            )}
            {erro && (
              <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {erro}
              </p>
            )}
            <div ref={fimRef} />
          </div>

          <form
            className="flex items-end gap-2 border-t border-border px-4 py-3"
            onSubmit={(e) => { e.preventDefault(); enviar(rascunho); }}>
            <textarea
              value={rascunho}
              onChange={(e) => setRascunho(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar(rascunho); }
              }}
              rows={Math.min(4, Math.max(1, rascunho.split("\n").length))}
              placeholder={gerando ? "gerando resposta…" : "pergunte sobre os dados da empresa…"}
              disabled={gerando}
              className="min-h-[40px] flex-1 resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/60 disabled:opacity-60"
            />
            <button type="submit" disabled={gerando || !rascunho.trim()}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground disabled:opacity-40"
              aria-label="Enviar pergunta">
              {gerando ? <Loader2 className="h-4 w-4 animate-spin" /> : <CornerDownLeft className="h-4 w-4" />}
            </button>
            {msgs.length > 0 && !gerando && (
              <button type="button" onClick={() => { setMsgs([]); setErro(null); }}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-border text-muted-foreground hover:text-foreground"
                aria-label="Limpar conversa" title="Limpar conversa">
                <X className="h-4 w-4" />
              </button>
            )}
          </form>
        </SheetContent>
      </Sheet>
    </>
  );
}
