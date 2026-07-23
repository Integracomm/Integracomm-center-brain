import { useEffect, useState } from "react";

// Lista que SOBREVIVE AO RECARREGAR mas morre ao sair da tela (Otávio 23/07).
//
// Os dois casos são distinguíveis porque a navegação entre telas do painel é
// por CARGA COMPLETA (os links do sidebar são <a href>, não roteamento no
// cliente). Então o tipo da navegação diz o que aconteceu:
//
//   "reload"        → F5 / Ctrl+R      → restaura
//   "navigate"      → veio de outra tela ou abriu do zero → limpa
//   "back_forward"  → voltar/avançar   → limpa (a pessoa saiu da tela)
//
// Guardar em sessionStorage sozinho não serviria: ele sobrevive à navegação
// dentro da aba, e a lista voltaria ao reabrir a tela — que é justamente o que
// não se quer.

function foiRecarregamento(): boolean {
  try {
    const nav = performance.getEntriesByType("navigation")[0] as
      PerformanceNavigationTiming | undefined;
    return nav?.type === "reload";
  } catch {
    return false; // sem a API, o comportamento seguro é começar vazio
  }
}

export function useListaDaSessao<T>(chave: string, inicial: T[]): [T[], (v: T[]) => void] {
  const [itens, setItens] = useState<T[]>(() => {
    try {
      const bruto = sessionStorage.getItem(chave);
      if (!bruto) return inicial;
      if (!foiRecarregamento()) {
        // chegou aqui vindo de outra tela: a lista da visita anterior morre
        sessionStorage.removeItem(chave);
        return inicial;
      }
      return JSON.parse(bruto) as T[];
    } catch {
      return inicial;
    }
  });

  useEffect(() => {
    try {
      if (itens.length) sessionStorage.setItem(chave, JSON.stringify(itens));
      else sessionStorage.removeItem(chave);
    } catch {
      /* cota cheia ou storage bloqueado: a lista segue só em memória */
    }
  }, [chave, itens]);

  return [itens, setItens];
}
