import { Info, AlertTriangle } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export interface CaveatProps {
  text: string;
  tone?: "info" | "warning";
  className?: string;
}

// Ressalva visível: pequeno ícone com texto expandido no hover. Aparece SEMPRE
// junto ao valor a que se refere — nunca escondido.
export function Caveat({ text, tone = "info", className }: CaveatProps) {
  const Icon = tone === "warning" ? AlertTriangle : Info;
  return (
    <TooltipProvider delayDuration={100}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "inline-flex h-4 w-4 items-center justify-center rounded-full cursor-help",
              tone === "warning" ? "text-warning" : "text-muted-foreground",
              className,
            )}
            aria-label={text}
          >
            <Icon className="h-3.5 w-3.5" />
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs text-xs">{text}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// Rótulo inline pequeno de ressalva/contexto (visível, com texto).
export function CaveatChip({ text, tone = "info" }: CaveatProps) {
  const Icon = tone === "warning" ? AlertTriangle : Info;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium",
        tone === "warning"
          ? "bg-warning/15 text-warning"
          : "bg-muted text-muted-foreground",
      )}
    >
      <Icon className="h-3 w-3" />
      {text}
    </span>
  );
}
