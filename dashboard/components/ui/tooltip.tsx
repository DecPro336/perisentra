"use client";

import * as T from "@radix-ui/react-tooltip";
import { Info } from "lucide-react";
import type { ReactNode } from "react";

export function Tip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content side={side} sideOffset={6} className="z-50 max-w-xs rounded-lg border border-border bg-surface px-3 py-2 text-[12.5px] leading-snug text-ink-2 shadow-lg">
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}

export function InfoTip({ children }: { children: ReactNode }) {
  return (
    <Tip content={children}>
      <button type="button" aria-label="More information" className="inline-flex text-ink-3 hover:text-ink">
        <Info className="h-3.5 w-3.5" />
      </button>
    </Tip>
  );
}
