import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { ApiError } from "@/api/errors";
import { createMockClient } from "@/api/mock";
import { ApiProvider } from "@/api/provider";
import type { MetricsResponse, Run, RunView } from "@/api/types";
import { metricsKey, metricsQuery, useRunMetrics } from "@/features/metrics/queries";
import { useEvidence, useIterationMetrics } from "@/features/run/queries";
import { fixture } from "@/test/fixtures";

const baseRun = fixture<RunView>("run_view/step_13_done.json").run;
const run = (changes: Partial<Run>): Run => ({ ...baseRun, ...changes });

/** Un client le cui metriche esistono solo per le iterazioni in `available`. */
function clientWith(available: Set<number>, failure?: ApiError) {
  const runMetrics = vi.fn((_runId: string, iteration: number) => {
    if (failure) return Promise.reject(failure);
    if (!available.has(iteration)) {
      return Promise.reject(new ApiError(404, { code: "NOT_FOUND", message: "non ancora" }));
    }
    return Promise.resolve(
      fixture<MetricsResponse>(`run_metrics/iteration_${Math.min(iteration, 2)}.json`),
    );
  });
  return {
    client: { ...createMockClient({ authenticated: true }), runMetrics } as ApiClient,
    runMetrics,
  };
}

function setup(client: ApiClient, initial: Run | undefined) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ApiProvider client={client}>{children}</ApiProvider>
  );
  return renderHook(({ current }: { current: Run | undefined }) => useRunMetrics(current), {
    wrapper,
    initialProps: { current: initial },
  });
}

const notFound = () => new ApiError(404, { code: "NOT_FOUND", message: "x" });

describe("useRunMetrics", () => {
  it("senza un run non fa niente", () => {
    const { client, runMetrics } = clientWith(new Set([0]));
    const { result } = setup(client, undefined);
    expect(result.current).toEqual({ status: "idle", available: [] });
    expect(runMetrics).not.toHaveBeenCalled();
  });

  it("con la sola iterazione 0: pronta, e la 0 è anche il «prima»", async () => {
    const { client } = clientWith(new Set([0]));
    const { result } = setup(client, run({ state: "RECONCILE", iteration: 0 }));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.iteration).toBe(0);
    expect(result.current.current?.iteration).toBe(0);
    expect(result.current.baseline).toBe(result.current.current);
  });

  it("sceglie l'iterazione più recente e tiene la 0 come «prima»", async () => {
    const { client, runMetrics } = clientWith(new Set([0, 1, 2]));
    const { result } = setup(client, run({ state: "DONE", iteration: 2 }));
    await waitFor(() => expect(result.current.iteration).toBe(2));
    expect(result.current.current?.iteration).toBe(2);
    expect(result.current.baseline?.iteration).toBe(0);
    expect(runMetrics.mock.calls.map(([, iteration]) => iteration).sort()).toEqual([0, 1, 2]);
    expect(runMetrics.mock.calls.every(([runId]) => runId === baseRun.id)).toBe(true);
  });

  it("se l'ultima non c'è ancora mostra la più recente che c'è, non il caricamento", async () => {
    const { client } = clientWith(new Set([0, 1]));
    const { result } = setup(client, run({ state: "VERIFY", iteration: 2 }));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.iteration).toBe(1);
  });

  it("finché non c'è niente (404) il run in corso è in caricamento", async () => {
    const { client, runMetrics } = clientWith(new Set());
    const { result } = setup(client, run({ state: "RECONCILE", iteration: 0 }));
    await waitFor(() => expect(runMetrics).toHaveBeenCalledTimes(1));
    expect(result.current.status).toBe("loading");
    expect(result.current.current).toBeUndefined();
  });

  it("durante l'analisi non chiede la 0 (si salva alla fine: sarebbe un 404 nella console)", async () => {
    const available = new Set([0]);
    const { client, runMetrics } = clientWith(available);
    const { result, rerender } = setup(client, run({ state: "INTAKE", iteration: 0 }));
    expect(result.current.status).toBe("loading");
    rerender({ current: run({ state: "ANALYZE", iteration: 0 }) });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(runMetrics).not.toHaveBeenCalled();
    expect(result.current.status).toBe("loading");
    rerender({ current: run({ state: "RECONCILE", iteration: 0 }) });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(runMetrics).toHaveBeenCalledTimes(1);
  });

  it("un run in errore durante l'analisi chiede la 0 e, se non c'è, è «non disponibile»", async () => {
    const { client, runMetrics } = clientWith(new Set());
    const { result } = setup(client, run({ state: "ERROR", iteration: 0 }));
    await waitFor(() => expect(runMetrics).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(result.current.status).toBe("unavailable"));
  });

  it("quando il run avanza riprova le iterazioni che non c'erano e trova la 0", async () => {
    const available = new Set<number>();
    const { client, runMetrics } = clientWith(available);
    const { result, rerender } = setup(client, run({ state: "RECONCILE", iteration: 0 }));
    await waitFor(() => expect(runMetrics).toHaveBeenCalledTimes(1));
    expect(result.current.status).toBe("loading");
    available.add(0);
    rerender({ current: run({ state: "PLAN", iteration: 0 }) });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(runMetrics).toHaveBeenCalledTimes(2);
  });

  it("un cambio di iterazione aggiunge quella nuova senza rileggere quelle già lette", async () => {
    const available = new Set([0]);
    const { client, runMetrics } = clientWith(available);
    const { result, rerender } = setup(client, run({ state: "AWAIT", iteration: 0 }));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(runMetrics).toHaveBeenCalledTimes(1);
    available.add(1);
    rerender({ current: run({ state: "VERIFY", iteration: 1 }) });
    await waitFor(() => expect(result.current.iteration).toBe(1));
    // la 0 non si rilegge: non è in errore e non cambia più
    expect(runMetrics.mock.calls.filter(([, iteration]) => iteration === 0)).toHaveLength(1);
    expect(runMetrics.mock.calls.filter(([, iteration]) => iteration === 1)).toHaveLength(1);
  });

  it("le iterazioni già lette non si rileggono nemmeno se la fascia si rimonta", async () => {
    const { client, runMetrics } = clientWith(new Set([0]));
    const { result, rerender } = setup(client, run({ state: "RECONCILE", iteration: 0 }));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    rerender({ current: undefined });
    expect(result.current.status).toBe("idle");
    rerender({ current: run({ state: "RECONCILE", iteration: 0 }) });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(runMetrics).toHaveBeenCalledTimes(1);
  });

  it("a run finito e senza metriche: non disponibili", async () => {
    const { client, runMetrics } = clientWith(new Set());
    const { result } = setup(client, run({ state: "DONE", iteration: 0 }));
    await waitFor(() => expect(runMetrics).toHaveBeenCalled());
    await waitFor(() => expect(result.current.status).toBe("unavailable"));
  });

  it("anche un run in errore, senza metriche, è «non disponibile»", async () => {
    const { client, runMetrics } = clientWith(new Set());
    const { result } = setup(client, run({ state: "ERROR", iteration: 0 }));
    await waitFor(() => expect(runMetrics).toHaveBeenCalled());
    await waitFor(() => expect(result.current.status).toBe("unavailable"));
  });

  it("un guasto vero del server (500) è «non disponibile» anche a run in corso", async () => {
    const { client } = clientWith(
      new Set(),
      new ApiError(500, { code: "INTERNAL", message: "boom" }),
    );
    const { result } = setup(client, run({ state: "PLAN", iteration: 0 }));
    await waitFor(() => expect(result.current.status).toBe("unavailable"));
  });

  it("un 404 non è un guasto: il run in corso resta in caricamento", async () => {
    const { client, runMetrics } = clientWith(new Set(), notFound());
    const { result } = setup(client, run({ state: "PLAN", iteration: 0 }));
    await waitFor(() => expect(runMetrics).toHaveBeenCalled());
    expect(result.current.status).toBe("loading");
  });
});

describe("la lettura delle metriche è una sola per iterazione (F4-REF)", () => {
  it("la chiave è unica: quella di un'iterazione comincia con quella del run (chi invalida le trova)", () => {
    expect(metricsKey("run_x")).toEqual(["metrics", "run_x"]);
    expect(metricsKey("run_x", 2)).toEqual(["metrics", "run_x", 2]);
    expect(metricsKey("run_x", 2).slice(0, 2)).toEqual(metricsKey("run_x"));
    const { client } = clientWith(new Set([0]));
    expect(metricsQuery(client, "run_x", 1)).toMatchObject({
      queryKey: ["metrics", "run_x", 1],
      staleTime: Infinity,
      retry: false,
    });
  });

  it("la fascia, il confronto e le evidenze si dividono la stessa lettura", async () => {
    const { client, runMetrics } = clientWith(new Set([0, 1, 2]));
    const finished = run({ state: "DONE", iteration: 2 });
    const evidence = ["m.run_mock_match_2027.it1.road.departure.veh_hours"];
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ApiProvider client={client}>{children}</ApiProvider>
    );
    const { result } = renderHook(
      () => ({
        strip: useRunMetrics(finished),
        comparison: useIterationMetrics(finished),
        evidence: useEvidence(finished.id, evidence),
      }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.strip.status).toBe("ready"));
    await waitFor(() => expect(result.current.comparison.every(Boolean)).toBe(true));
    await waitFor(() => expect(result.current.evidence.size).toBeGreaterThan(0));
    // tre lettori, tre iterazioni (0, 1, 2): tre letture in tutto, non nove
    expect(runMetrics).toHaveBeenCalledTimes(3);
    expect(runMetrics.mock.calls.map((call) => call[1]).sort()).toEqual([0, 1, 2]);
  });
});
