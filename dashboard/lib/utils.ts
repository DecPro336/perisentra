import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** A link to a service on the dashboard's machine (e.g. MLflow at localhost:5000), rewritten to the host the
 * dashboard was opened with, so it also works when the dashboard is viewed from another machine. */
export function onThisHost(url: string): string {
  if (typeof window === "undefined") return url;
  try {
    const u = new URL(url);
    if (["localhost", "127.0.0.1"].includes(u.hostname)) u.hostname = window.location.hostname;
    return u.toString();
  } catch {
    return url;
  }
}
