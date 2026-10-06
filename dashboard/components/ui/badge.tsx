import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

const variants = {
  neutral: "bg-surface-2 text-ink-2 border-border",
  brand: "bg-brand-soft text-brand border-transparent",
  good: "bg-good-soft text-good-ink border-transparent",
  warning: "bg-warning-soft text-warning-ink border-transparent",
  serious: "bg-serious-soft text-serious-ink border-transparent",
  critical: "bg-critical-soft text-critical-ink border-transparent",
  outline: "bg-transparent text-ink-2 border-border-strong",
};

export function Badge({ variant = "neutral", className, children, icon }: { variant?: keyof typeof variants; className?: string; children: ReactNode; icon?: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[12px] font-medium leading-none", variants[variant], className)}>
      {icon}
      {children}
    </span>
  );
}
