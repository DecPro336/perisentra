"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import * as Switch from "@radix-ui/react-switch";
import { CircleAlert, Plus, X } from "lucide-react";
import { cn } from "@/lib/utils";

/** Pydantic messages come prefixed with "Value error, "; keep the human part. */
export const cleanMsg = (m: string) => m.replace(/^Value error,\s*/i, "");

export function FieldError({ errors }: { errors?: string[] }) {
  if (!errors?.length) return null;
  return (
    <div className="mt-1 space-y-0.5" role="alert">
      {errors.map((e, i) => (
        <div key={i} className="flex items-start gap-1 text-[12px] leading-snug text-critical-ink"><CircleAlert className="mt-px h-3.5 w-3.5 shrink-0" />{cleanMsg(e)}</div>
      ))}
    </div>
  );
}

export function Field({ label, help, errors, children, className }: { label: ReactNode; help?: ReactNode; errors?: string[]; children: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="mb-1.5 text-[13px] font-medium text-ink">{label}</div>
      {children}
      {help && <div className="mt-1.5 text-[12px] leading-snug text-ink-3">{help}</div>}
      <FieldError errors={errors} />
    </div>
  );
}

const fmt = (v: number | null | undefined, scale: number) => (v == null || Number.isNaN(v) ? "" : String(+(v * scale).toFixed(6)));

/** Numeric input that keeps its own text (so "-" or "0." can be typed) and reports a number, or null when empty. */
export function NumberInput({ value, onChange, scale = 1, step = 1, min, max, prefix, suffix, placeholder, invalid, className, ariaLabel }: {
  value: number | null | undefined; onChange: (v: number | null) => void; scale?: number; step?: number; min?: number; max?: number;
  prefix?: string; suffix?: string; placeholder?: string; invalid?: boolean; className?: string; ariaLabel?: string;
}) {
  const [text, setText] = useState(fmt(value, scale));
  const last = useRef<number | null | undefined>(value);
  useEffect(() => {
    if (value !== last.current) { last.current = value; setText(fmt(value, scale)); }
  }, [value, scale]);
  return (
    <div className={cn("relative inline-flex w-32 items-center", className)}>
      {prefix && <span className="pointer-events-none absolute left-2.5 text-[12.5px] text-ink-3">{prefix}</span>}
      <input
        type="number" inputMode="decimal" value={text} step={step} min={min} max={max} placeholder={placeholder} aria-label={ariaLabel} aria-invalid={invalid || undefined}
        onChange={(e) => {
          const s = e.target.value;
          setText(s);
          const n = s.trim() === "" ? null : Number(s) / scale;
          const v = n == null || Number.isNaN(n) ? null : +n.toFixed(8);
          last.current = v;
          onChange(v);
        }}
        className={cn("h-9 w-full rounded-lg border bg-surface text-[13px] tabular text-ink placeholder:text-ink-3 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none",
          prefix ? "pl-6" : "pl-3", suffix ? "pr-10" : "pr-3", invalid ? "border-critical" : "border-border-strong")}
      />
      {suffix && <span className="pointer-events-none absolute right-2.5 text-[12.5px] text-ink-3">{suffix}</span>}
    </div>
  );
}

export function Toggle({ checked, onChange, label, help }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; help?: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <Switch.Root checked={checked} onCheckedChange={onChange} className="relative mt-0.5 h-5 w-9 shrink-0 rounded-full bg-surface-3 data-[state=checked]:bg-brand">
        <Switch.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
      </Switch.Root>
      <span>
        <span className="block text-[13px] font-medium text-ink">{label}</span>
        {help && <span className="mt-0.5 block text-[12px] leading-snug text-ink-3">{help}</span>}
      </span>
    </label>
  );
}

/** Removable chips plus an "add" input; values are numbers. */
export function ChipList({ values, onChange, format, step = 1, scale = 1, placeholder, addLabel, normalize, ariaLabel }: {
  values: number[]; onChange: (v: number[]) => void; format: (v: number) => string; step?: number; scale?: number;
  placeholder?: string; addLabel: string; normalize?: (v: number[]) => number[]; ariaLabel: string;
}) {
  const [draft, setDraft] = useState<number | null>(null);
  const add = () => {
    if (draft == null) return;
    const next = [...values, draft];
    onChange(normalize ? normalize(next) : next);
    setDraft(null);
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label={ariaLabel}>
      {values.map((v, i) => (
        <span key={`${v}-${i}`} className="inline-flex h-8 items-center gap-1 rounded-lg border border-border-strong bg-surface-2 pl-2.5 pr-1 text-[13px] font-medium tabular text-ink">
          {format(v)}
          <button type="button" onClick={() => onChange(values.filter((_, j) => j !== i))} aria-label={`Remove ${format(v)}`}
            className="inline-flex h-6 w-6 items-center justify-center rounded-md text-ink-3 hover:bg-surface-3 hover:text-ink"><X className="h-3.5 w-3.5" /></button>
        </span>
      ))}
      <div className="inline-flex items-center gap-1" onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}>
        <NumberInput value={draft} onChange={setDraft} step={step} scale={scale} placeholder={placeholder} className="w-24" ariaLabel={addLabel} />
        <button type="button" onClick={add} disabled={draft == null}
          className="inline-flex h-9 items-center gap-1 rounded-lg border border-border-strong bg-surface px-2.5 text-[13px] font-medium text-ink hover:bg-surface-2 disabled:opacity-50">
          <Plus className="h-3.5 w-3.5" />{addLabel}
        </button>
      </div>
    </div>
  );
}
