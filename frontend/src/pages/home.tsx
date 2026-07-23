import logoClaro from "@/assets/integracomm-logo-black.png";
import logoEscuro from "@/assets/integracomm-logo-white.png";

// HOME ÚNICA (Otávio 22/07) — a tela inicial de TODOS: SÓ a marca.
//
// A 1ª versão trazia foco da semana, atalhos e visões. O Otávio cortou: dado na
// home é dado fora do contexto da área, e vira risco de mostrar a alguém o que
// ela não deveria ver (as ações do foco, por exemplo, trazem nome de cliente e
// de negócio). Cada um vê os seus números NA PÁGINA DA ÁREA; a home é só a
// porta de entrada, e quem decide o que ela abre é o sidebar — montado a partir
// de /api/home, que devolve apenas o que ESTA conta acessa.
//
// Nada de fetch aqui: a página não tem dado para vazar.

export interface HomePayload {
  usuario: string;
  role: string;
  areas: Array<{ slug: string; nome: string; href: string }>;
  visoes: Array<{ slug: string; nome: string; href: string }>;
  // `pendencias` = o que espera o admin (pedido de senha, cadastro a aprovar).
  // O selo aparece no SIDEBAR: a home é só a marca, e o pedido de senha não vai
  // para o grupo do Slack (23/07), então precisa saltar aos olhos na navegação.
  admin: Array<{ slug: string; nome: string; href: string;
    pendencias?: number; pendencias_detalhe?: string }>;
}

export function HomePage() {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center gap-6">
      {/* a marca segue o tema: preta no claro, branca no escuro */}
      <img src={logoClaro} alt="Integracomm" className="w-72 max-w-[70%] dark:hidden" />
      <img src={logoEscuro} alt="Integracomm" className="hidden w-72 max-w-[70%] dark:block" />
      <p className="text-sm text-muted-foreground">
        Escolha uma área no menu à esquerda.
      </p>
    </div>
  );
}
