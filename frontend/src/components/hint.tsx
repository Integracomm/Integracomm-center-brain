import { useEffect, useRef, useState } from "react";
import { Info, X } from "lucide-react";
import { apiGet } from "@/api/client";

// ⓘ "como ler este campo" — regra do produto: todo campo nasce com help
// (padrão 16/07: O que mostra / Como ler / Fique de olho, para gestor não
// técnico). Os TEXTOS vêm de /api/help — a MESMA fonte (help_texts.py) das
// telas HTML; nada duplicado no frontend.
type HelpDb = Record<string, Array<{ titulo: string; texto: string }>>;

let _cache: HelpDb | null = null;
let _pending: Promise<HelpDb> | null = null;

function carregaHelp(): Promise<HelpDb> {
  if (_cache) return Promise.resolve(_cache);
  _pending ??= apiGet<HelpDb>("/api/help").then((db) => {
    _cache = db;
    return db;
  });
  return _pending;
}

export function Hint({ area, titulo }: { area: string; titulo: string }) {
  const [texto, setTexto] = useState<string | null>(null);
  const [aberto, setAberto] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let vivo = true;
    carregaHelp().then((db) => {
      if (!vivo) return;
      const entrada = db[area]?.find((e) => e.titulo === titulo);
      setTexto(entrada?.texto ?? null);
    }).catch(() => {});
    return () => { vivo = false; };
  }, [area, titulo]);

  useEffect(() => {
    if (!aberto) return;
    const fecha = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setAberto(false);
    };
    document.addEventListener("mousedown", fecha);
    return () => document.removeEventListener("mousedown", fecha);
  }, [aberto]);

  if (!texto) return null; // sem entrada correspondente, o ícone não aparece
  return (
    <div ref={ref} className="relative inline-flex">
      <button type="button" onClick={() => setAberto((v) => !v)}
        className="inline-flex items-center gap-1 rounded px-1 text-muted-foreground hover:text-foreground"
        title="como ler este campo" aria-label="como ler este campo">
        <Info className="h-3.5 w-3.5" />
      </button>
      {aberto && (
        <div className="absolute left-0 top-6 z-50 w-[340px] max-w-[80vw] rounded-xl border border-border bg-popover p-4 text-popover-foreground shadow-lg">
          <div className="mb-1 flex items-start justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              como ler — {titulo === "_intro" ? "esta tela" : titulo}
            </span>
            <button type="button" onClick={() => setAberto(false)} aria-label="fechar">
              <X className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
            </button>
          </div>
          <p className="whitespace-pre-line text-[13px] leading-relaxed">{texto}</p>
        </div>
      )}
    </div>
  );
}
