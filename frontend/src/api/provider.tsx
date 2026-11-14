import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useState, type ReactNode } from "react";
import { createApiClient, type ApiClient } from "@/api/client";
import { ApiError } from "@/api/errors";
import type { AuthState } from "@/api/types";

export const queryKeys = {
  me: ["me"] as const,
  departments: ["departments"] as const,
  run: (runId: string) => ["run", runId] as const,
};

const ANONYMOUS: AuthState = { authenticated: false };

/** Un 401 da qualunque chiamata vuol dire sessione scaduta o assente (07 3): lo stato di
 * autenticazione torna anonimo (il resto dell'interfaccia mostra il login) e i dati dell'utente
 * in cache si buttano. Vale anche per il 401 del login («password errata»): lo stato era già
 * anonimo e non c'è niente in cache, quindi non cambia nulla. */
function backToLogin(queryClient: QueryClient, error: unknown): void {
  if (!(error instanceof ApiError) || !error.isUnauthorized) return;
  queryClient.setQueryData(queryKeys.me, ANONYMOUS);
  queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== queryKeys.me[0] });
}

function createQueryClient(): QueryClient {
  const queryClient: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError: (error) => backToLogin(queryClient, error) }),
    mutationCache: new MutationCache({ onError: (error) => backToLogin(queryClient, error) }),
    defaultOptions: {
      queries: {
        // i dati del server si rileggono con il polling, non perché la finestra torna in primo piano
        // (il mock avanzerebbe di un fotogramma a ogni cambio di scheda)
        refetchOnWindowFocus: false,
        // un errore dell'API (4xx) non migliora riprovando; la rete assente sì, una volta
        retry: (failures, error) =>
          !(error instanceof ApiError && error.status >= 400) && failures < 1,
      },
    },
  });
  return queryClient;
}

const ApiContext = createContext<ApiClient | null>(null);

export function useApi(): ApiClient {
  const client = useContext(ApiContext);
  if (!client) throw new Error("useApi fuori da <ApiProvider>");
  return client;
}

interface ApiProviderProps {
  /** Il client da usare; se manca lo sceglie `VITE_API_MODE` (`createApiClient`). */
  client?: ApiClient;
  children: ReactNode;
}

export function ApiProvider({ client, children }: ApiProviderProps) {
  const [state] = useState(() => ({
    queryClient: createQueryClient(),
    client: client ?? createApiClient(),
  }));
  return (
    <QueryClientProvider client={state.queryClient}>
      <ApiContext.Provider value={state.client}>{children}</ApiContext.Provider>
    </QueryClientProvider>
  );
}
