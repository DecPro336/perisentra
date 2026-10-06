import { cn } from "@/lib/utils";
import type { ReactNode } from "react";
import { InfoTip } from "./tooltip";

export function Stat({ label, value, hint, delta, deltaTone = "neutral", icon, className, accent }: {
  label: string; value: ReactNode; hint?: ReactNode; delta?: ReactNode; deltaTone?: "good" | "bad" | "neutral"; icon?: ReactNode; className?: string; accent?: boolean;
}) {
  return (
    <div className={cn("rounded-xl border border-border bg-surface px-4 py-3.5", accent && "border-transparent bg-brand text-brand-ink", className)}>
      <div className={cn("flex items-center gap-1.5 text-[12.5px] font-medium", accent ? "text-brand-ink/85" : "text-ink-3")}>
        {icon}
        <span>{label}</span>
        {hint && <InfoTip>{hint}</InfoTip>}
      </div>
      <div className={cn("mt-1.5 text-[26px] font-semibold leading-tight tracking-tight", accent ? "text-brand-ink" : "text-ink")}>{value}</div>
      {delta && (
        <div className={cn("mt-1 text-[12.5px]", accent ? "text-brand-ink/85" : deltaTone === "good" ? "text-good-ink" : deltaTone === "bad" ? "text-critical-ink" : "text-ink-3")}>{delta}</div>
      )}
    </div>
  );
}
