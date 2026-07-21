import * as React from "react";

// Card de seção padrão: título, subtítulo opcional, slot à direita (filtros/badges)
// e conteúdo. Sem regra de negócio — só container visual.
export function SectionCard({
  title,
  subtitle,
  right,
  children,
  className,
}: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={
        "rounded-xl border border-border bg-card p-4 shadow-sm " + (className ?? "")
      }
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <h2 className="font-display text-sm font-semibold">{title}</h2>
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
