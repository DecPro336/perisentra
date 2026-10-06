"use client";

import { AlertTriangle, Inbox, LoaderCircle } from "lucide-react";
import { ApiError, isNotReady } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export function Loading({ className, rows = 3 }: { className?: string; rows?: number }) {
  return (
    <div className={cn("space-y-3", className)} aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => <div key={i} className="h-16 animate-pulse rounded-xl bg-surface-2" />)}
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const { t } = useI18n();
  if (isNotReady(error)) return <PreparingState detail={(error as ApiError).detail} />;
  return (
    <div className="flex items-start gap-3 rounded-xl border border-critical/30 bg-critical-soft px-4 py-3 text-critical-ink">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div><div className="font-medium">{t("common.error")}</div><div className="text-[12.5px] opacity-80">{error instanceof ApiError ? error.detail : String((error as Error)?.message ?? error)}</div></div>
    </div>
  );
}

export function Empty({ children }: { children?: React.ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-ink-3">
      <Inbox className="h-6 w-6" />
      <div className="text-[13px]">{children ?? t("common.none")}</div>
    </div>
  );
}

/** Shown while the pipeline has not produced this morning's data yet (API 503). Refreshes on its own. */
function PreparingState({ detail }: { detail?: string }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-border bg-surface px-5 py-4">
      <LoaderCircle className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-brand" />
      <div>
        <div className="font-medium text-ink">Preparing this morning&apos;s data</div>
        <div className="mt-0.5 text-[13px] text-ink-3">{detail ?? "The pipeline is still running."} This page refreshes automatically.</div>
      </div>
    </div>
  );
}
