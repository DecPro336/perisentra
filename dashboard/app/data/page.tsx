"use client";

// The page body lives in components/domain/data-page.tsx: the repository's root .gitignore ignores every `data/`
// directory, and Tailwind v4 skips gitignored paths when scanning for classes, so classes written here would not be generated.
import { DataPage } from "@/components/domain/data-page";

export default function Page() {
  return <DataPage />;
}
