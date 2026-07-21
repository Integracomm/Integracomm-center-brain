import * as React from "react";

// Card de seção padrão: título, subtítulo opcional, slot à direita (filtros/badges)
// e conteúdo. Sem regra de negócio — só container visual.
export function SectionCard({
  title,
  subtitle,
  right,
  hint,
  children,
  className,
  headerClassName,
}: {
  title: string;
  subtitle?: string;
  hint?: React.ReactNode;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  // p/ cards lado a lado: fixa a altura do header e os gráficos ALINHAM
  // (feedback Otávio 21/07 — subtítulos de tamanhos diferentes desalinhavam)
  headerClassName?: string;
}) {
  return (
    <section
      className={
        "rounded-xl border border-border bg-card p-4 shadow-sm " + (className ?? "")
      }
    >
      <div className={"flex items-start justify-between gap-3 mb-3 " + (headerClassName ?? "")}>
        <div className="min-w-0">
          <h2 className="font-display inline-flex items-center gap-1.5 text-sm font-semibold">{title}{hint}</h2>
          {subtitle && (
            <p className="text-xs text-muted-foreground mt-0.5">{subtitle}</p>
          )}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}
