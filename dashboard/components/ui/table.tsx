import { cn } from "@/lib/utils";
import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("scroll-thin overflow-x-auto", className)}><table className="w-full border-collapse text-[13px]">{children}</table></div>;
}
export function THead({ children }: { children: ReactNode }) {
  return <thead className="sticky top-0 z-10 bg-surface">{children}</thead>;
}
export function TH({ className, align, ...p }: ThHTMLAttributes<HTMLTableCellElement> & { align?: "left" | "right" | "center" }) {
  return <th {...p} className={cn("whitespace-nowrap border-b border-border px-3 py-2 text-[12px] font-medium text-ink-3", align === "right" ? "text-right" : align === "center" ? "text-center" : "text-left", className)} />;
}
export function TR({ className, ...p }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr {...p} className={cn("border-b border-border last:border-0", className)} />;
}
export function TD({ className, align, ...p }: TdHTMLAttributes<HTMLTableCellElement> & { align?: "left" | "right" | "center" }) {
  return <td {...p} className={cn("px-3 py-2.5 align-middle text-ink", align === "right" ? "text-right tabular" : align === "center" ? "text-center" : "", className)} />;
}
