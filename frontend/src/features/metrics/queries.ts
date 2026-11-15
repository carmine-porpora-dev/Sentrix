import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { ApiError } from "@/api/errors";
import type { ApiClient } from "@/api/client";
import { useApi } from "@/api/provider";
import type { Event, MetricsResponse, Run, RunState } from "@/api/types";
import { isRunFinished } from "@/api/queries";
import { DEFAULT_VIEW, chooseIteration, type IterationView } from "@/features/metrics/iterations";

export function useEvent(eventId: string | undefined) {
  const api = useApi();
  return useQuery<Event>({
    queryKey: ["event", eventId ?? ""],
    queryFn: () => api.getEvent(eventId as string),
    enabled: eventId !== undefined,
    staleTime: Infinity,
  });
}

/** La chiave delle metriche di un run, o di una sua iterazione: una sola, perché chi le legge (la fascia,
 * il confronto, le evidenze) condivide la stessa lettura e chi la invalida le trova tutte. */
export const metricsKey = (runId: string | undefined, iteration?: number) =>
  iteration === undefined
    ? (["metrics", runId] as const)
    : (["metrics", runId, iteration] as const);

/** La lettura delle metriche di un'iterazione. Un'iterazione già letta non cambia più; finché non c'è
 * l'API risponde 404 (si riprova quando il run avanza, `useRunMetrics`), quindi nessun nuovo tentativo. */
export const metricsQuery = (
  api: ApiClient,
  runId: string | undefined,
  iteration: number,
  enabled = true,
) => ({
  queryKey: metricsKey(runId, iteration),
  queryFn: () => api.runMetrics(runId as string, iteration),
  enabled,
  staleTime: Infinity,
  retry: false,
});

const ANALYZING: readonly RunState[] = ["INTAKE", "ANALYZE"];

/** Se l'iterazione può già avere le metriche. La 0 si salva alla fine dell'analisi: prima l'API
 * risponde 404 (giusto, ma ogni 404 è un errore nella console del browser), quindi non la si chiede.
 * Le altre arrivano con la verifica, e `run.iteration` le conta solo da allora. */
export const iterationMayBeReady = (run: Run, iteration: number): boolean =>
  iteration > 0 || !ANALYZING.includes(run.state);

export type MetricsStatus = "idle" | "loading" | "ready" | "unavailable";

export interface RunMetrics {
  status: MetricsStatus;
  /** Le iterazioni di cui ci sono le metriche, in ordine. */
  available: number[];
  /** L'iterazione mostrata (`view`): «Prima», quella scelta o la più recente. */
  iteration?: number;
  /** Le sue metriche e i suoi delta. */
  current?: MetricsResponse;
  /** Quelle dell'iterazione 0, senza misure (per «prima → dopo»). */
  baseline?: MetricsResponse;
}

/** Le metriche del run: l'iterazione da mostrare (di default la più recente disponibile) e la 0. Un'iterazione si produce quando il
 * run arriva alla verifica: finché non c'è l'API risponde 404 e si riprova quando il run avanza
 * (stato o iterazione). Quelle già lette non cambiano più. */
export function useRunMetrics(
  run: Run | undefined,
  view: IterationView = DEFAULT_VIEW,
): RunMetrics {
  const api = useApi();
  const queryClient = useQueryClient();
  const runId = run?.id;
  const iterations = run ? Array.from({ length: run.iteration + 1 }, (_, n) => n) : [];

  const results = useQueries({
    queries: iterations.map((iteration) =>
      metricsQuery(api, runId, iteration, run !== undefined && iterationMayBeReady(run, iteration)),
    ),
  });

  const state = run?.state;
  const iteration = run?.iteration;
  useEffect(() => {
    if (runId === undefined) return;
    void queryClient.invalidateQueries({
      queryKey: metricsKey(runId),
      predicate: (query) => query.state.status === "error",
    });
  }, [runId, state, iteration, queryClient]);

  if (!run) return { status: "idle", available: [] };
  const available = results.flatMap((result, n) => (result.data ? [n] : []));
  const shown = chooseIteration(available, view);
  const baseline = results[0]?.data;
  if (shown !== undefined) {
    return {
      status: "ready",
      available,
      iteration: shown,
      current: results[shown]?.data,
      baseline,
    };
  }
  // niente ancora: «non ancora prodotte» (404) o un guasto vero
  const failed = results.some(
    (result) => result.error && !(result.error instanceof ApiError && result.error.status === 404),
  );
  return { status: failed || isRunFinished(run.state) ? "unavailable" : "loading", available };
}
