"use client";

import * as S from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export function Select({ value, onChange, options, placeholder, className, label }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; placeholder?: string; className?: string; label?: string;
}) {
  return (
    <S.Root value={value || "__all"} onValueChange={(v) => onChange(v === "__all" ? "" : v)}>
      <S.Trigger aria-label={label} className={cn("inline-flex h-9 min-w-[150px] items-center justify-between gap-2 rounded-lg border border-border-strong bg-surface px-3 text-[13px] text-ink hover:bg-surface-2", className)}>
        <span className="flex min-w-0 items-center gap-1.5 truncate">
          {label && <span className="text-ink-3">{label}:</span>}
          <S.Value placeholder={placeholder} />
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-ink-3" />
      </S.Trigger>
      <S.Portal>
        <S.Content position="popper" sideOffset={4} className="z-50 max-h-[360px] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg border border-border bg-surface shadow-lg">
          <S.Viewport className="p-1">
            {options.map((o) => (
              <S.Item key={o.value || "__all"} value={o.value || "__all"} className="relative flex cursor-pointer select-none items-center rounded-md py-1.5 pl-7 pr-3 text-[13px] text-ink outline-none data-[highlighted]:bg-surface-2">
                <S.ItemIndicator className="absolute left-2"><Check className="h-4 w-4 stroke-[3]" /></S.ItemIndicator>
                <S.ItemText>{o.label}</S.ItemText>
              </S.Item>
            ))}
          </S.Viewport>
        </S.Content>
      </S.Portal>
    </S.Root>
  );
}
