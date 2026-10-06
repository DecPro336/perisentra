"use client";

import { ArrowDownRight, ArrowUpRight, CircleCheck, CircleDashed, CircleAlert, HandHeart, Tag, Minus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/lib/i18n";
import type { Tier } from "@/lib/api";

export function ActionBadge({ action, discount, window }: { action: string; discount?: number; window?: number }) {
  const { t } = useI18n();
  if (action === "MARKDOWN")
    return <Badge variant="brand" icon={<Tag className="h-3 w-3" />}>{`-${Math.round(discount ?? 0)}%`}{window ? <span className="font-normal opacity-80">· ≤{window}d</span> : null}</Badge>;
  return <Badge variant="neutral" icon={<Minus className="h-3 w-3" />}>{t("action.NO_ACTION")}</Badge>;
}

export function OrderBadge({ action, reference, recommended }: { action: string; reference?: number; recommended?: number }) {
  const { t } = useI18n();
  if (action === "REDUCE") return <Badge variant="serious" icon={<ArrowDownRight className="h-3 w-3" />}>{reference} → {recommended}</Badge>;
  if (action === "INCREASE") return <Badge variant="warning" icon={<ArrowUpRight className="h-3 w-3" />}>{reference} → {recommended}</Badge>;
  return <span className="text-[12.5px] text-ink-3" title={t("order.KEEP")}>{recommended ?? reference ?? "–"}</span>;
}

export function DonateBadge({ units }: { units: number }) {
  const { t } = useI18n();
  if (!units) return null;
  return <Badge variant="good" icon={<HandHeart className="h-3 w-3" />}>{t("action.DONATE")} · {units}</Badge>;
}

export function ConfidenceBadge({ tier, short }: { tier: Tier; short?: boolean }) {
  const { t } = useI18n();
  const map = { HIGH: { v: "good" as const, i: CircleCheck }, MEDIUM: { v: "warning" as const, i: CircleDashed }, LOW: { v: "critical" as const, i: CircleAlert } };
  const { v, i: Icon } = map[tier] ?? map.MEDIUM;
  return <Badge variant={v} icon={<Icon className="h-3 w-3" />}>{t(short ? `tier.short.${tier}` : `tier.${tier}`)}</Badge>;
}
