"use client";

import { createContext, useCallback, useContext, useMemo, useSyncExternalStore, type ReactNode } from "react";

type Theme = "light" | "dark" | "system";
type Resolved = "light" | "dark";
const KEY = "theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

/** Runs before first paint (inlined in the root layout) so the page never flashes the wrong theme. */
export const themeScript = `(function(){try{var t=localStorage.getItem("${KEY}")||"light";var d=t==="dark"||(t==="system"&&matchMedia("${DARK_QUERY}").matches);document.documentElement.dataset.theme=d?"dark":"light";document.documentElement.style.colorScheme=d?"dark":"light";}catch(e){document.documentElement.dataset.theme="light";}})();`;

interface Ctx { theme: Theme; resolvedTheme: Resolved; setTheme: (t: Theme) => void }
const ThemeContext = createContext<Ctx | null>(null);

/*
 * The stored choice and the OS preference live outside React, so they are read with useSyncExternalStore: the
 * server render and hydration use "light", the client then re-renders with the real values, and no effect has to
 * copy them into state. The <html> attributes are written by the pre-paint script and by the event handlers below.
 */
let current: Theme | null = null;            // in-memory copy, also the fallback when storage is unavailable
const listeners = new Set<() => void>();

function stored(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    return t === "dark" || t === "system" ? t : "light";
  } catch {
    return "light";
  }
}
const readTheme = (): Theme => (current ??= stored());
const systemDark = () => matchMedia(DARK_QUERY).matches;

function applyToDocument() {
  const t = readTheme();
  const r: Resolved = t === "dark" || (t === "system" && systemDark()) ? "dark" : "light";
  document.documentElement.dataset.theme = r;
  document.documentElement.style.colorScheme = r;
}

function subscribeTheme(cb: () => void) {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => {   // theme changed in another tab
    if (e.key !== KEY) return;
    current = stored();
    applyToDocument();
    cb();
  };
  window.addEventListener("storage", onStorage);
  return () => { listeners.delete(cb); window.removeEventListener("storage", onStorage); };
}

function subscribeSystem(cb: () => void) {
  const mq = matchMedia(DARK_QUERY);
  const onChange = () => { applyToDocument(); cb(); };
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useSyncExternalStore(subscribeTheme, readTheme, (): Theme => "light");
  const dark = useSyncExternalStore(subscribeSystem, systemDark, () => false);
  const resolvedTheme: Resolved = theme === "system" ? (dark ? "dark" : "light") : theme;

  const setTheme = useCallback((t: Theme) => {
    current = t;
    try { localStorage.setItem(KEY, t); } catch { /* storage unavailable: keep the choice for this page only */ }
    applyToDocument();
    listeners.forEach((l) => l());
  }, []);
  const value = useMemo(() => ({ theme, resolvedTheme, setTheme }), [theme, resolvedTheme, setTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const c = useContext(ThemeContext);
  if (!c) throw new Error("ThemeProvider missing");
  return c;
}
