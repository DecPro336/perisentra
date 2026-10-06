"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "@/lib/theme";
import * as Tooltip from "@radix-ui/react-tooltip";
import { Toaster } from "sonner";
import { useState, type ReactNode } from "react";
import { I18nProvider } from "@/lib/i18n";
import { isNotReady } from "@/lib/api";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        staleTime: 30_000,
        // "not ready yet" is not a failure: don't hammer the API, poll until the pipeline has produced the data
        retry: (count, error) => !isNotReady(error) && count < 1,
        refetchInterval: (query) => (isNotReady(query.state.error) ? 20_000 : false),
      },
    },
  }));
  return (
    <ThemeProvider>
      <QueryClientProvider client={client}>
        <I18nProvider>
          <Tooltip.Provider delayDuration={150}>
            {children}
            <Toaster position="bottom-right" richColors closeButton />
          </Tooltip.Provider>
        </I18nProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
