import { type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Caveat } from "./caveat";

export type KpiTone = "primary" | "accent" | "success" | "warning" | "destructive" | "muted";

const toneClasses: Record<KpiTone, { wash: string; icon: string; iconBg: string }> = {
  primary:    { wash: "bg-primary/[0.07]",     icon: "text-primary",     iconBg: "bg-primary/15" },
  accent:     { wash: "bg-accent/[0.07]",      icon: "text-accent",      iconBg: "bg-accent/15" },
  success:    { wash: "bg-success/[0.07]",     icon: "text-success",     iconBg: "bg-success/15" },
  warning:    { wash: "bg-warning/[0.07]",     icon: "text-warning",     iconBg: "bg-warning/15" },
  destructive:{ wash: "bg-destructive/[0.07]", icon: "text-destructive", iconBg: "bg-destructive/15" },
  muted:      { wash: "bg-muted/40",           icon: "text-muted-foreground", iconBg: "bg-muted" },
};

export interface KpiCardProps {
  title: string;
  value: string;
  subtitle?: string;
  icon: LucideIcon;
  tone?: KpiTone;
  caveat?: string;
  className?: string;
}

export function KpiCard({ title, value, subtitle, icon: Icon, tone = "primary", caveat, className }: KpiCardProps) {
  const t = toneClasses[tone];
  return (
    // Ícone + rótulo em cima; o VALOR embaixo, ocupando a largura inteira do
    // card (Otávio 23/07). Antes o número dividia a coluna estreita com o
    // ícone e quebrava em duas linhas: "R$ 186.671" tinha 91px para caber.
    // Assim o espaço útil quase dobra e o número fica numa linha só.
    <div className={cn("relative rounded-xl p-5 shadow-sm border border-transparent", t.wash, className)}>
      <div className="flex items-start gap-3">
        <div className={cn("flex h-11 w-11 shrink-0 items-center justify-center rounded-xl", t.iconBg)}>
          <Icon className={cn("h-5 w-5", t.icon)} strokeWidth={2.2} />
        </div>
        <div className="flex min-w-0 flex-1 items-center gap-2 pt-0.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <span className="min-w-0 whitespace-normal leading-tight">{title}</span>
          {caveat && <Caveat text={caveat} />}
        </div>
      </div>
      <div className={cn(
        "mt-3 font-display font-bold tabular-nums leading-none text-foreground",
        // mesmo com a largura toda, "1.252 / 1.506" não cabe em text-3xl numa
        // coluna de 6 — o tamanho cede conforme o texto
        value.length <= 8 ? "text-3xl" : value.length <= 12 ? "text-2xl" : "text-xl",
      )}>
        {value}
      </div>
      {subtitle && <div className="mt-1.5 text-sm text-muted-foreground">{subtitle}</div>}
    </div>
  );
}
