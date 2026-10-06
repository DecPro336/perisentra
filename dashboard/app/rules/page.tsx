"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { CircleAlert, CircleCheck, CircleDashed, LoaderCircle, Play, RotateCcw, Save, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { useMeta, useRecompute, useRules, useSaveRules, useValidateRules } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { dateLabel, money, num } from "@/lib/format";
import { PageHeader } from "@/components/ui/page";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { Empty, ErrorState, Loading } from "@/components/ui/states";
import { ChipList, Field, FieldError, NumberInput, Toggle, cleanMsg } from "@/components/domain/rules-fields";
import { cn } from "@/lib/utils";

/* eslint-disable @typescript-eslint/no-explicit-any */

type Path = (string | number)[];
type Validation = { valid: boolean; errors: { loc: string; msg: string }[] };

function setIn(obj: any, path: Path, value: unknown): any {
  if (!path.length) return value;
  const [k, ...rest] = path;
  const copy: any = Array.isArray(obj) ? [...obj] : { ...(obj ?? {}) };
  if (!rest.length && value === undefined) { delete copy[k as string]; return copy; }
  copy[k as string] = setIn(obj?.[k as string], rest, value);
  return copy;
}

/** Number of leaf values that differ (arrays compared whole). */
function diffCount(a: any, b: any): number {
  const isObj = (x: any) => x && typeof x === "object" && !Array.isArray(x);
  if (isObj(a) && isObj(b)) {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    let n = 0;
    keys.forEach((k) => { if (k !== "version") n += diffCount(a[k], b[k]); });
    return n;
  }
  return JSON.stringify(a) === JSON.stringify(b) ? 0 : 1;
}

function Section({ title, subtitle, children, className }: { title: string; subtitle?: string; children: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader title={title} subtitle={subtitle} />
      <CardBody>{children}</CardBody>
    </Card>
  );
}

/** Per-family overrides: default row + one row per family, empty input = inherits default. */
function FamilyOverrides({ families, columns, errorsFor }: {
  families: string[];
  columns: { key: string; label: string; dict: Record<string, number>; path: Path; suffix: string; step?: number; onChange: (p: Path, v: number | null | undefined) => void }[];
  errorsFor: (p: string) => string[];
}) {
  return (
    <Table>
      <THead>
        <TR>
          <TH>Family</TH>
          {columns.map((c) => <TH key={c.key}>{c.label}</TH>)}
        </TR>
      </THead>
      <tbody>
        <TR className="bg-surface-2/60">
          <TD className="font-semibold">Default</TD>
          {columns.map((c) => (
            <TD key={c.key}>
              <NumberInput value={c.dict?.default} onChange={(v) => c.onChange(["default"], v)} suffix={c.suffix} step={c.step} invalid={errorsFor(`${c.path.join(".")}.default`).length > 0} ariaLabel={`${c.label} default`} />
              <FieldError errors={errorsFor(`${c.path.join(".")}.default`)} />
            </TD>
          ))}
        </TR>
        {families.map((f) => (
          <TR key={f}>
            <TD className="text-ink-2">{f}</TD>
            {columns.map((c) => {
              const own = c.dict?.[f];
              const has = own !== undefined && own !== null;
              return (
                <TD key={c.key}>
                  <div className="flex items-center gap-2">
                    <NumberInput value={has ? own : null} onChange={(v) => c.onChange([f], v === null ? undefined : v)} suffix={c.suffix} step={c.step}
                      placeholder={`${c.dict?.default ?? "–"}`} invalid={errorsFor(`${c.path.join(".")}.${f}`).length > 0} ariaLabel={`${c.label} ${f}`} />
                    {has ? <Badge variant="brand">Override</Badge> : <span className="text-[12px] text-ink-3">inherits</span>}
                  </div>
                  <FieldError errors={errorsFor(`${c.path.join(".")}.${f}`)} />
                </TD>
              );
            })}
          </TR>
        ))}
      </tbody>
    </Table>
  );
}

function RecomputeCard({ rulesVersion, dirty }: { rulesVersion?: number; dirty: boolean }) {
  const { lang } = useI18n();
  const { data: meta } = useMeta();
  const recompute = useRecompute();
  const [store, setStore] = useState("");
  const [elapsed, setElapsed] = useState<number | null>(null);
  const storeId = store || String(meta?.stores?.[0]?.store_id ?? "");
  const storeName = meta?.stores.find((s) => String(s.store_id) === storeId)?.store_name ?? storeId;
  const r = recompute.data;
  const run = () => {
    if (!storeId) return;
    const t0 = Date.now();
    setElapsed(null);
    recompute.mutate(Number(storeId), {
      onSuccess: (res) => {
        setElapsed((Date.now() - t0) / 1000);
        toast.success(`Decisions re-run for ${storeName}`, { description: `${res.markdowns} markdowns · ${res.order_changes} order changes` });
      },
      onError: (e: any) => toast.error("Re-run failed", { description: String(e?.data?.detail ?? e?.message ?? e) }),
    });
  };
  return (
    <Card>
      <CardHeader title={"Apply without retraining"}
        subtitle={"Re-runs only the decision layer for one store with the saved rules."} />
      <CardBody className="space-y-3">
        <Select label={"Store"} value={storeId} onChange={(v) => v && setStore(v)} className="w-full"
          options={(meta?.stores ?? []).map((s) => ({ value: String(s.store_id), label: s.store_name }))} />
        <Button variant="primary" className="w-full" onClick={run} disabled={!storeId || recompute.isPending}>
          {recompute.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {recompute.isPending ? "Re-running… (5–15 s)" : "Re-run decisions"}
        </Button>
        {dirty && (
          <div className="flex items-start gap-1.5 text-[12px] leading-snug text-warning-ink">
            <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
            {`Unsaved edits: the re-run uses the saved version (v${rulesVersion ?? "–"}).`}
          </div>
        )}
        {recompute.isPending && (
          <div className="rounded-lg border border-dashed border-border-strong px-3 py-2.5 text-[12.5px] text-ink-3">
            Reusing this morning’s forecasts, elasticities and Monte Carlo paths; only the rules are re-applied.
          </div>
        )}
        {r && !recompute.isPending && (
          <div className="space-y-2.5">
            <div className="grid grid-cols-3 gap-2">
              {[
                { l: "Markdowns", v: num(r.markdowns, lang) },
                { l: "Order changes", v: num(r.order_changes, lang) },
                { l: "Waste avoided", v: money(r.waste_avoided, lang) },
              ].map((x) => (
                <div key={x.l} className="rounded-lg border border-border bg-surface-2/60 px-2.5 py-2">
                  <div className="text-[11.5px] leading-tight text-ink-3">{x.l}</div>
                  <div className="mt-0.5 text-[17px] font-semibold tracking-tight text-ink">{x.v}</div>
                </div>
              ))}
            </div>
            <p className="text-[12.5px] leading-snug text-ink-2">
              {`${num(r.items, lang)} products re-scored for ${meta?.stores.find((s) => s.store_id === r.store_id)?.store_name ?? r.store_id}${elapsed ? ` in ${num(elapsed, lang, 1)} s` : ""}. No model was retrained: only the decision layer re-ran.`}
            </p>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

export default function RulesPage() {
  const { t, lang } = useI18n();
  const { data, isLoading, error } = useRules();
  const { data: meta } = useMeta();
  const save = useSaveRules();
  const { mutate: validate } = useValidateRules();

  const [draft, setDraft] = useState<any>(null);
  const [comment, setComment] = useState("");
  const [validation, setValidation] = useState<Validation | null>(null);
  const [validating, setValidating] = useState(false);
  const loaded = useRef<number | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    if (data?.rules && loaded.current !== data.rules.version) {
      loaded.current = data.rules.version;
      setDraft(structuredClone(data.rules));
    }
  }, [data]);

  useEffect(() => {
    if (!draft) return;
    const id = setTimeout(() => {
      const n = ++seq.current;
      setValidating(true);
      validate({ rules: draft }, {
        onSuccess: (res: Validation) => { if (n === seq.current) { setValidation(res); setValidating(false); } },
        onError: (e: any) => { if (n === seq.current) { setValidation({ valid: false, errors: [{ loc: "", msg: String(e?.message ?? e) }] }); setValidating(false); } },
      });
    }, 400);
    return () => clearTimeout(id);
  }, [draft, validate]);

  const set = useCallback((path: Path, value: unknown) => setDraft((d: any) => setIn(d, path, value)), []);
  const errorsFor = useCallback((prefix: string) => (validation?.errors ?? [])
    .filter((e) => e.loc === prefix || e.loc.startsWith(`${prefix}.`)).map((e) => e.msg), [validation]);

  const original = data?.rules;
  const changes = useMemo(() => (draft && original ? diffCount(draft, original) : 0), [draft, original]);
  const families = useMemo(() => {
    const fromRules = draft ? [...Object.keys(draft.markdown?.max_discount_pct ?? {}), ...Object.keys(draft.margin?.unit_floor_pct ?? {}), ...Object.keys(draft.margin?.window_floor_pct ?? {})] : [];
    return [...new Set([...(meta?.families ?? []), ...fromRules])].filter((f) => f !== "default").sort((a, b) => a.localeCompare(b));
  }, [meta, draft]);

  if (isLoading || (data && !draft)) return <Loading rows={6} />;
  if (error) return <ErrorState error={error} />;
  if (!draft) return <Empty />;

  const valid = validation?.valid ?? true;
  const errCount = validation?.errors.length ?? 0;
  const confWarn = draft.confidence?.medium_min_score != null && draft.confidence?.high_min_score != null && draft.confidence.medium_min_score >= draft.confidence.high_min_score;
  const canSave = changes > 0 && valid && !validating && comment.trim().length > 0 && !save.isPending;
  const history: any[] = data?.history ?? [];
  const currentVersion = original?.version;

  const onSave = () => {
    save.mutate({ rules: draft, comment: comment.trim() }, {
      onSuccess: (res: any) => {
        toast.success(`Saved as version ${res.version}`, { description: comment.trim() });
        loaded.current = res.version;
        setDraft(structuredClone(res.rules));
        setComment("");
      },
      onError: (e: any) => {
        const detail = e?.data?.detail;
        const msg = Array.isArray(detail) ? detail.map((d: any) => `${d.loc}: ${cleanMsg(d.msg)}`).join(" · ") : String(detail ?? e?.message ?? e);
        toast.error("Could not save", { description: msg });
      },
    });
  };
  const onReset = () => { setDraft(structuredClone(original)); setComment(""); toast("Changes discarded"); };

  const pctSfx = "%";
  const conf = draft.confidence ?? {};
  const hi = Math.min(1, Math.max(0, conf.high_min_score ?? 0.7));
  const med = Math.min(hi, Math.max(0, conf.medium_min_score ?? 0.45));

  return (
    <div className="space-y-6">
      <PageHeader title={t("rules.title")}
        eyebrow={currentVersion != null ? `Active version v${currentVersion}` : undefined}
        subtitle={"The commercial constraints the engine respects. Change them here without retraining any model; every save creates a traceable version."} />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <Section title={"Objective"}
            subtitle={"Pick the action with the lowest expected waste; when actions are nearly tied, keep the best margin."}>
            <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
              <Field label={"Primary objective"} errors={errorsFor("objective.primary")}
                help={"Expected waste value (at cost), from the Monte Carlo simulation."}>
                <Badge variant="outline" className="h-9 px-3 text-[13px] font-normal">{draft.objective?.primary === "min_expected_waste_value" ? "Minimise expected waste value" : draft.objective?.primary}</Badge>
              </Field>
              <Field label={"Tie tolerance"} errors={errorsFor("objective.tie_tolerance_pct")}
                help={"Actions within this % of the best expected waste count as tied; the highest margin wins (0–50%)."}>
                <NumberInput value={draft.objective?.tie_tolerance_pct} onChange={(v) => set(["objective", "tie_tolerance_pct"], v)} suffix={pctSfx} step={0.5} invalid={errorsFor("objective.tie_tolerance_pct").length > 0} />
              </Field>
              <Field label={"Minimum waste saving"} errors={errorsFor("objective.min_waste_gain")}
                help={"Ignore markdowns that save less than this in expected waste."}>
                <NumberInput value={draft.objective?.min_waste_gain} onChange={(v) => set(["objective", "min_waste_gain"], v)} suffix="USD" step={0.1} invalid={errorsFor("objective.min_waste_gain").length > 0} />
              </Field>
              <Field label={"Minimum revenue gain"} errors={errorsFor("objective.min_revenue_gain")}
                help={"When markdowns must pay for themselves: the minimum expected revenue uplift."}>
                <NumberInput value={draft.objective?.min_revenue_gain} onChange={(v) => set(["objective", "min_revenue_gain"], v)} suffix="USD" step={0.1} invalid={errorsFor("objective.min_revenue_gain").length > 0} />
              </Field>
              <div className="md:col-span-2">
                <Toggle checked={!!draft.objective?.markdown_must_pay_for_itself} onChange={(v) => set(["objective", "markdown_must_pay_for_itself"], v)}
                  label={"A markdown must pay for itself"}
                  help={"The stock is already bought: a markdown is only proposed if it raises expected revenue."} />
              </div>
            </div>
          </Section>

          <Section title={"Markdowns"} subtitle={"Which discounts exist, when they can start, and how prices are rounded."}>
            <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
              <Field label={"Discount ladder"} errors={errorsFor("markdown.ladder_pct")} className="md:col-span-2"
                help={"The engine evaluates every step (whole percentages from 1 to 89)."}>
                <ChipList values={draft.markdown?.ladder_pct ?? []} onChange={(v) => set(["markdown", "ladder_pct"], v)} format={(v) => `-${v}%`} placeholder="%"
                  addLabel={"Add"} ariaLabel="Discount ladder" normalize={(v) => [...new Set(v)].sort((a, b) => a - b)} />
              </Field>
              <Field label={"Earliest start"} errors={errorsFor("markdown.max_days_before_expiry")}
                help={"A markdown can only start in the last N days before expiry (1–7)."}>
                <NumberInput value={draft.markdown?.max_days_before_expiry} onChange={(v) => set(["markdown", "max_days_before_expiry"], v)} suffix={"days"} min={1} max={7} invalid={errorsFor("markdown.max_days_before_expiry").length > 0} />
              </Field>
              <Field label={"Minimum price"} errors={errorsFor("markdown.min_price")}
                help={"No marked-down price goes below this."}>
                <NumberInput value={draft.markdown?.min_price} onChange={(v) => set(["markdown", "min_price"], v)} suffix="USD" step={0.01} invalid={errorsFor("markdown.min_price").length > 0} />
              </Field>
              <Field label={"Price endings"} errors={errorsFor("markdown.price_endings")} className="md:col-span-2"
                help={"Marked-down prices snap to the nearest of these endings (cents, e.g. 0.99)."}>
                <ChipList values={draft.markdown?.price_endings ?? []} onChange={(v) => set(["markdown", "price_endings"], v)} format={(v) => v.toFixed(2).replace(/^0/, "")}
                  step={0.01} placeholder="0.99" addLabel={"Add"} ariaLabel="Price endings" normalize={(v) => [...new Set(v)].sort((a, b) => b - a)} />
              </Field>
            </div>
          </Section>

          <Section title={"Maximum discount by family"}
            subtitle={"Leave a family empty to inherit the default."}>
            <FamilyOverrides families={families} errorsFor={errorsFor} columns={[
              { key: "md", label: "Max discount", dict: draft.markdown?.max_discount_pct ?? {}, path: ["markdown", "max_discount_pct"], suffix: "%",
                onChange: (p, v) => set(["markdown", "max_discount_pct", ...p], v) },
            ]} />
          </Section>

          <Section title={"Margin floors"}
            subtitle={"Unit floor: discounted price ≥ unit cost × (1 + floor). A negative floor allows clearance below cost (e.g. today's bread). Window floor: expected margin rate over the markdown window."}>
            <FamilyOverrides families={families} errorsFor={errorsFor} columns={[
              { key: "unit", label: "Unit floor", dict: draft.margin?.unit_floor_pct ?? {}, path: ["margin", "unit_floor_pct"], suffix: "%",
                onChange: (p, v) => set(["margin", "unit_floor_pct", ...p], v) },
              { key: "window", label: "Window floor", dict: draft.margin?.window_floor_pct ?? {}, path: ["margin", "window_floor_pct"], suffix: "%",
                onChange: (p, v) => set(["margin", "window_floor_pct", ...p], v) },
            ]} />
          </Section>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <Section title={"Promotions"} subtitle={"Don't stack markdowns on promotions."}>
              <Toggle checked={!!draft.promotions?.lock_markdowns_during_promo} onChange={(v) => set(["promotions", "lock_markdowns_during_promo"], v)}
                label={"Lock markdowns during a promotion"}
                help={"Marketing already set the promo price; the engine reports the PROMO_LOCK reason."} />
              <FieldError errors={errorsFor("promotions")} />
            </Section>
            <Section title={"Donation"} subtitle={"Donate rather than bin what is left at close."}>
              <div className="space-y-4">
                <Toggle checked={!!draft.donation?.enabled} onChange={(v) => set(["donation", "enabled"], v)} label={"Suggest donations"} />
                <div className="grid grid-cols-2 gap-4">
                  <Field label={"Minimum units"} errors={errorsFor("donation.min_units")}>
                    <NumberInput value={draft.donation?.min_units} onChange={(v) => set(["donation", "min_units"], v)} className="w-full" invalid={errorsFor("donation.min_units").length > 0} />
                  </Field>
                  <Field label="Tax benefit" errors={errorsFor("donation.tax_benefit_pct")}>
                    <NumberInput value={draft.donation?.tax_benefit_pct} onChange={(v) => set(["donation", "tax_benefit_pct"], v)} suffix="%" className="w-full" invalid={errorsFor("donation.tax_benefit_pct").length > 0} />
                  </Field>
                </div>
                <p className="text-[12px] leading-snug text-ink-3">
                  Donations to food banks are protected by the Bill Emerson Good Samaritan Act and qualify for the enhanced food-inventory deduction (IRC §170(e)(3)); this is the share of cost recovered.
                </p>
              </div>
            </Section>
          </div>

          <Section title={"Replenishment"} subtitle={"When to change the next order, and by how much at most."}>
            <div className="space-y-5">
              <Toggle checked={!!draft.replenishment?.enabled} onChange={(v) => set(["replenishment", "enabled"], v)}
                label={"Suggest order adjustments"}
                help={"Reduce when expected waste is high, increase when stock-out risk is."} />
              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
                <Field label={"Minimum change (units)"} errors={errorsFor("replenishment.min_change_units")}>
                  <NumberInput value={draft.replenishment?.min_change_units} onChange={(v) => set(["replenishment", "min_change_units"], v)} suffix={"units"} className="w-full" invalid={errorsFor("replenishment.min_change_units").length > 0} />
                </Field>
                <Field label={"Minimum change (%)"} errors={errorsFor("replenishment.min_change_pct")}>
                  <NumberInput value={draft.replenishment?.min_change_pct} onChange={(v) => set(["replenishment", "min_change_pct"], v)} suffix="%" className="w-full" invalid={errorsFor("replenishment.min_change_pct").length > 0} />
                </Field>
                <Field label={"Maximum change (%)"} errors={errorsFor("replenishment.max_change_pct")}>
                  <NumberInput value={draft.replenishment?.max_change_pct} onChange={(v) => set(["replenishment", "max_change_pct"], v)} suffix="%" className="w-full" invalid={errorsFor("replenishment.max_change_pct").length > 0} />
                </Field>
                <Field label={"Service level: lower bound"} errors={errorsFor("replenishment.service_level_bounds.0")}>
                  <NumberInput value={draft.replenishment?.service_level_bounds?.[0]} onChange={(v) => set(["replenishment", "service_level_bounds", 0], v)} scale={100} step={0.5} suffix="%" className="w-full" invalid={errorsFor("replenishment.service_level_bounds.0").length > 0} />
                </Field>
                <Field label={"Service level: upper bound"} errors={errorsFor("replenishment.service_level_bounds.1")}>
                  <NumberInput value={draft.replenishment?.service_level_bounds?.[1]} onChange={(v) => set(["replenishment", "service_level_bounds", 1], v)} scale={100} step={0.5} suffix="%" className="w-full" invalid={errorsFor("replenishment.service_level_bounds.1").length > 0} />
                </Field>
              </div>
              <FieldError errors={(validation?.errors ?? []).filter((e) => e.loc === "replenishment.service_level_bounds").map((e) => e.msg)} />
              <p className="text-[12px] leading-snug text-ink-3">
                A change is only proposed when it clears both minimums, and it is capped at the maximum. The target service level (probability of not running out) stays between the two bounds.
              </p>
            </div>
          </Section>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <Section title={"Exploration"} subtitle={"Keep learning price response."}>
              <Field label={"Exploration rate"} errors={errorsFor("exploration.rate")}
                help={"On this share of decisions the engine picks at random among near-equivalent actions and logs the probability of that choice (its propensity). Future elasticity refits then learn from unconfounded price variation (0–50%)."}>
                <NumberInput value={draft.exploration?.rate} onChange={(v) => set(["exploration", "rate"], v)} scale={100} step={0.5} suffix="%" invalid={errorsFor("exploration.rate").length > 0} />
              </Field>
            </Section>
            <Section title={"Confidence thresholds"} subtitle={"Score 0–1: forecast precision, history, expiry data, price evidence."}>
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <Field label={"Medium from"} errors={errorsFor("confidence.medium_min_score")}>
                    <NumberInput value={conf.medium_min_score} onChange={(v) => set(["confidence", "medium_min_score"], v)} step={0.05} className="w-full" invalid={errorsFor("confidence.medium_min_score").length > 0} />
                  </Field>
                  <Field label={"High from"} errors={errorsFor("confidence.high_min_score")}>
                    <NumberInput value={conf.high_min_score} onChange={(v) => set(["confidence", "high_min_score"], v)} step={0.05} className="w-full" invalid={errorsFor("confidence.high_min_score").length > 0} />
                  </Field>
                </div>
                <div>
                  <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-surface-2" role="img" aria-label="Confidence bands">
                    <div className="h-full border-r-2 border-surface bg-critical" style={{ width: `${med * 100}%` }} />
                    <div className="h-full border-r-2 border-surface bg-warning" style={{ width: `${(hi - med) * 100}%` }} />
                    <div className="h-full bg-good" style={{ width: `${(1 - hi) * 100}%` }} />
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <Badge variant="critical" icon={<CircleAlert className="h-3 w-3" />}>{t("tier.short.LOW")} &lt; {num(med, lang, 2)}</Badge>
                    <Badge variant="warning" icon={<CircleDashed className="h-3 w-3" />}>{t("tier.short.MEDIUM")} {num(med, lang, 2)}–{num(hi, lang, 2)}</Badge>
                    <Badge variant="good" icon={<CircleCheck className="h-3 w-3" />}>{t("tier.short.HIGH")} ≥ {num(hi, lang, 2)}</Badge>
                  </div>
                </div>
                {confWarn && (
                  <div className="flex items-start gap-1.5 text-[12px] text-warning-ink"><TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" />The medium threshold should stay below the high threshold.</div>
                )}
              </div>
            </Section>
          </div>

          <Section title={"Legacy reference rule"}
            subtitle={"The stores' current flat markdown rule (a fixed discount on the day before expiry), evaluated alongside every decision: the savings shown are measured against it."}>
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
              <Field label={"Discount applied"} errors={errorsFor("legacy.markdown_pct")}>
                <NumberInput value={draft.legacy?.markdown_pct} onChange={(v) => set(["legacy", "markdown_pct"], v)} suffix="%" invalid={errorsFor("legacy.markdown_pct").length > 0} />
              </Field>
              <Field label={"On products expiring within"} errors={errorsFor("legacy.days_before_expiry")}>
                <NumberInput value={draft.legacy?.days_before_expiry} onChange={(v) => set(["legacy", "days_before_expiry"], v)} suffix={"days"} invalid={errorsFor("legacy.days_before_expiry").length > 0} />
              </Field>
            </div>
            <p className="mt-3 text-[12px] text-ink-3">
              {`Today: -${num(draft.legacy?.markdown_pct, lang)}% on everything expiring within ${num(draft.legacy?.days_before_expiry, lang)} days. Change it only if the stores' rule changes.`}
            </p>
          </Section>
        </div>

        <div className="space-y-6 xl:sticky xl:top-20 xl:self-start">
          <RecomputeCard rulesVersion={currentVersion} dirty={changes > 0} />
          <Card>
            <CardHeader title={"Version history"} subtitle={"Every recommendation records the version that produced it."} />
            <CardBody className="pt-2">
              {history.length === 0 ? <Empty /> : (
                <ol className="max-h-[360px] space-y-0 overflow-y-auto scroll-thin">
                  {history.map((h) => (
                    <li key={h.version} className="flex gap-3 border-b border-border py-2.5 last:border-0">
                      <span className={cn("mt-0.5 inline-flex h-6 min-w-9 items-center justify-center rounded-md px-1.5 text-[12px] font-semibold tabular",
                        h.version === currentVersion ? "bg-brand-soft text-brand" : "bg-surface-2 text-ink-2")}>v{h.version}</span>
                      <div className="min-w-0">
                        <div className="text-[13px] leading-snug text-ink">{h.comment || <span className="text-ink-3">(no comment)</span>}</div>
                        <div className="mt-0.5 text-[12px] text-ink-3">{h.saved_by} · {dateLabel(h.saved_at, lang, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}{h.version === currentVersion ? ` · active` : ""}</div>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </CardBody>
          </Card>
        </div>
      </div>

      <div className="sticky bottom-4 z-20">
        <div className="flex flex-col gap-3 rounded-xl border border-border-strong bg-surface/95 px-4 py-3 shadow-[0_8px_30px_rgba(0,0,0,0.12)] backdrop-blur lg:flex-row lg:items-center">
          <div className="flex min-w-0 flex-wrap items-center gap-2 text-[13px]">
            {validating ? <Badge variant="neutral" icon={<LoaderCircle className="h-3 w-3 animate-spin" />}>Validating…</Badge>
              : valid ? <Badge variant="good" icon={<CircleCheck className="h-3 w-3" />}>Rules valid</Badge>
              : <Badge variant="critical" icon={<CircleAlert className="h-3 w-3" />}>{errCount} {(errCount > 1 ? "errors" : "error")}</Badge>}
            <span className="text-ink-2">
              {changes === 0 ? (`No changes since v${currentVersion}`)
                : (`${changes} unsaved change${changes > 1 ? "s" : ""}`)}
            </span>
            {!valid && (validation?.errors ?? []).some((e) => !e.loc) && (
              <span className="text-[12px] text-critical-ink">{(validation?.errors ?? []).filter((e) => !e.loc).map((e) => cleanMsg(e.msg)).join(" · ")}</span>
            )}
          </div>
          <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-center lg:justify-end">
            <input value={comment} onChange={(e) => setComment(e.target.value)} disabled={changes === 0}
              placeholder={"Describe the change (required)"} aria-label={"Comment"}
              className="h-9 w-full rounded-lg border border-border-strong bg-surface px-3 text-[13px] text-ink placeholder:text-ink-3 disabled:opacity-60 sm:max-w-[340px]" />
            <div className="flex gap-2">
              <Button variant="outline" onClick={onReset} disabled={changes === 0 || save.isPending}><RotateCcw className="h-4 w-4" />Reset</Button>
              <Button variant="primary" onClick={onSave} disabled={!canSave}
                title={!canSave && changes > 0 && !comment.trim() ? "Add a comment first" : undefined}>
                {save.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                Save as new version
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
