import { Bot, CornerDownLeft, Loader2, Sparkles, X } from "lucide-react";
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

export function AssistentePainel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [aberto, setAberto] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [rascunho, setRascunho] = useState("");
  const [gerando, setGerando] = useState(false);
  const [atividade, setAtividade] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const fimRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch("/api/assistente/status", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    fimRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, atividade]);

  if (!status?.disponivel) return null;

  async function enviar(pergunta: string) {
    const p = pergunta.trim();
    if (!p || gerando) return;
    setErro(null);
    setRascunho("");
    setGerando(true);
    const historico = [...msgs, { role: "user" as const, content: p }];
    setMsgs([...historico, { role: "assistant", content: "", consultas: [] }]);
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
