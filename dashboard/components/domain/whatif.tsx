"use client";

import { useState } from "react";
import * as Slider from "@radix-ui/react-slider";
import { Check, FlaskConical, Loader2, X } from "lucide-react";
import { useWhatIf } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { money, num, pct } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { WasteDistChart } from "./item-charts";
import { cn } from "@/lib/utils";

const RULE_LABEL: Record<string, string> = {
  promo_lock: "No active promotion lock",
  max_discount: "Within the family's maximum discount",
  unit_margin_floor: "Unit margin floor",
  window_margin_floor: "Margin floor over the markdown window",
  units_to_label: "Units available to label",
};

export function WhatIf({ storeId, skuId, initialDiscount, initialWindow }: { storeId: number; skuId: number; initialDiscount: number; initialWindow: number }) {
  const { t, lang } = useI18n();
  const [discount, setDiscount] = useState(Math.round(initialDiscount / 5) * 5 || 30);
  const [windowDays, setWindowDays] = useState(String(initialWindow || 2));
  const sim = useWhatIf();
  const r = sim.data;

  const rows: { key: string; label: string; fmt: (v: number) => string; better: "lower" | "higher" }[] = [
    { key: "waste_units", label: "Units wasted (expected)", fmt: (v) => num(v, lang, 1), better: "lower" },
    { key: "waste_value", label: "Waste value (at cost)", fmt: (v) => money(v, lang, 2), better: "lower" },
    { key: "p_waste", label: "Probability of any waste", fmt: (v) => pct(v, lang), better: "lower" },
    { key: "revenue", label: "Revenue (7 days)", fmt: (v) => money(v, lang, 2), better: "higher" },
    { key: "net_margin", label: "Margin after waste (7 days)", fmt: (v) => money(v, lang, 2), better: "higher" },
    { key: "discount_cost", label: "Discount given", fmt: (v) => money(v, lang, 2), better: "lower" },
    { key: "p_stockout", label: "Stock-out risk", fmt: (v) => pct(v, lang), better: "lower" },
  ];

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
      <div className="space-y-5 lg:col-span-2">
        <div>
          <div className="mb-2 flex items-baseline justify-between text-[13px]"><span className="text-ink-2">{t("item.discount")}</span><span className="text-[20px] font-semibold tabular text-ink">-{discount}%</span></div>
          <Slider.Root value={[discount]} onValueChange={(v) => setDiscount(v[0])} min={0} max={60} step={5} className="relative flex h-5 w-full touch-none select-none items-center" aria-label={t("item.discount")}>
            <Slider.Track className="relative h-1.5 grow rounded-full bg-surface-3"><Slider.Range className="absolute h-full rounded-full bg-brand" /></Slider.Track>
            <Slider.Thumb className="block h-4 w-4 rounded-full border-2 border-brand bg-surface shadow" />
          </Slider.Root>
          <div className="mt-1 flex justify-between text-[11px] text-ink-3 tabular"><span>0%</span><span>20%</span><span>40%</span><span>60%</span></div>
        </div>
        <div>
          <div className="mb-2 text-[13px] text-ink-2">{t("item.window")}</div>
          <Segmented value={windowDays} onChange={setWindowDays} options={["1", "2", "3"].map((d) => ({ value: d, label: d === "1" ? "1 day" : `${d} days` }))} />
        </div>
        <Button variant="primary" onClick={() => sim.mutate({ store_id: storeId, sku_id: skuId, discount_pct: discount, window_days: Number(windowDays) })} disabled={sim.isPending}>
          {sim.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}{t("item.simulate")}
        </Button>
        {r && (
          <div className="space-y-2 rounded-lg border border-border bg-surface-2/60 p-3">
            <div className="text-[12.5px] text-ink-3">Price: {money(r.regular_price, lang, 2)} → <b className="text-ink">{money(r.new_price, lang, 2)}</b> (-{num(r.discount_pct, lang)}%) · {num(r.units_labelled, lang)} units labelled · {num(r.n_paths, lang)} paths</div>
            <ul className="space-y-1">
              {r.checks.map((c: { rule: string; ok: boolean }) => (
                <li key={c.rule} className={cn("flex items-center gap-2 text-[13px]", c.ok ? "text-ink-2" : "text-critical-ink")}>
                  {c.ok ? <Check className="h-4 w-4 text-good" /> : <X className="h-4 w-4" />}{(RULE_LABEL[c.rule] ?? c.rule)}
                </li>
              ))}
            </ul>
            {!r.feasible && <div className="text-[12.5px] font-medium text-critical-ink">This scenario breaks a business rule: the engine would not recommend it.</div>}
          </div>
        )}
      </div>
      <div className="lg:col-span-3">
        {!r ? (
          <div className="flex h-full min-h-[220px] items-center justify-center rounded-lg border border-dashed border-border-strong text-center text-[13px] text-ink-3">
            Pick a discount and run the Monte Carlo simulation (2,000 demand paths).
          </div>
        ) : (
          <div className="space-y-4">
            <Table>
              <THead><TR><TH /><TH align="right">{t("item.baseline")}</TH><TH align="right">{t("item.scenario")}</TH><TH align="right">Δ</TH></TR></THead>
              <tbody>
                {rows.map((row) => {
                  const a = r.baseline[row.key], b = r.scenario[row.key], d = b - a;
                  const good = row.better === "lower" ? d < 0 : d > 0;
                  return (
                    <TR key={row.key}>
                      <TD className="text-ink-2">{row.label}</TD><TD align="right">{row.fmt(a)}</TD><TD align="right" className="font-medium">{row.fmt(b)}</TD>
                      <TD align="right" className={cn(Math.abs(d) < 1e-6 ? "text-ink-3" : good ? "text-good-ink" : "text-critical-ink")}>{d > 0 ? "+" : ""}{row.fmt(d)}</TD>
                    </TR>
                  );
                })}
              </tbody>
            </Table>
            <WasteDistChart baseline={r.baseline.waste_hist} chosen={r.scenario.waste_hist} labels={[t("item.baseline"), t("item.scenario")]} />
          </div>
        )}
      </div>
    </div>
  );
}
