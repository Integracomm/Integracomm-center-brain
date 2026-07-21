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
    <div className={cn("relative flex items-start gap-4 rounded-xl p-5 shadow-sm border border-transparent", t.wash, className)}>
      <div className={cn("flex h-11 w-11 shrink-0 items-center justify-center rounded-xl", t.iconBg)}>
        <Icon className={cn("h-5 w-5", t.icon)} strokeWidth={2.2} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
          <span className="truncate">{title}</span>
          {caveat && <Caveat text={caveat} />}
        </div>
        <div className="mt-1 font-display text-3xl font-bold tabular-nums leading-tight text-foreground">
          {value}
        </div>
        {subtitle && <div className="mt-1 text-sm text-muted-foreground">{subtitle}</div>}
      </div>
    </div>
  );
}
