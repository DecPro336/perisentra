"use client";

import { AlertTriangle, CheckCircle2, Info, Zap, CircleDot } from "lucide-react";
import type { ReasonCode } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const ICON = { warning: AlertTriangle, success: CheckCircle2, info: Info, action: Zap, muted: CircleDot };
const TONE = { warning: "text-serious-ink", success: "text-good-ink", info: "text-ink-3", action: "text-brand", muted: "text-ink-3" };

export function ReasonList({ reasons, compact }: { reasons: ReasonCode[]; compact?: boolean }) {
  const { reason } = useI18n();
  const list = compact ? reasons.filter((r) => r.level !== "muted").slice(0, 2) : reasons;
  return (
    <ul className={cn("space-y-1.5", compact && "space-y-0.5")}>
      {list.map((r, i) => {
        const Icon = ICON[r.level] ?? Info;
        return (
          <li key={i} className={cn("flex items-start gap-2", compact ? "text-[12.5px] text-ink-2" : "text-[13.5px] text-ink")}>
            <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", TONE[r.level])} aria-hidden />
            <span className={cn(r.level === "muted" && "text-ink-3")}>{reason(r)}</span>
          </li>
        );
      })}
    </ul>
  );
}
