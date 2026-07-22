import { Users, AlertOctagon, ShieldAlert, Sparkles, PackageCheck, DollarSign,
         type LucideIcon } from "lucide-react";
import { KpiCard, type KpiTone } from "@/components/kpi-card";
import { valorComMeta } from "./formato";
import type { Metrica } from "./tipos";

// NÚMEROS-CHAVE DO MÊS — quais KPIs entram e em que ordem é decisão do backend
// (_hub_kpis); aqui escolhemos só ícone e tom a partir do rótulo.

const ICONE: Array<[RegExp, LucideIcon, KpiTone]> = [
  [/monitorad/i, Users, "primary"],
  [/alerta/i, AlertOctagon, "destructive"],
  [/MRR/i, ShieldAlert, "warning"],
  [/lead/i, Sparkles, "accent"],
  [/booking/i, PackageCheck, "success"],
  [/receita/i, DollarSign, "success"],
];
const TOM: Record<string, KpiTone> = {
  ok: "success", medio: "warning", alto: "warning", critico: "destructive",
};

export function KpisMes({ kpis }: { kpis: Metrica[] }) {
  return (
    // 6 colunas só a partir de 2xl: a 1280 a célula ficava com 149px e o
    // KpiCard precisa de 168 (ícone 44 + texto), o que empurrava scroll na
    // página inteira — medido no navegador, não no olho
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
      {kpis.map((k) => {
        const hit = ICONE.find(([re]) => re.test(k.rotulo));
        const icone = hit ? hit[1] : Users;
        const tom = k.tom ? TOM[k.tom] : hit ? hit[2] : "muted";
        return <KpiCard key={k.rotulo} title={k.rotulo} value={valorComMeta(k)} icon={icone} tone={tom} />;
      })}
    </div>
  );
}
