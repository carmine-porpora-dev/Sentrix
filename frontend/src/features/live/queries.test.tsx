import { useQueryClient } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMockClient } from "@/api/mock";
import { ApiProvider } from "@/api/provider";
import { ApiError } from "@/api/errors";
import { LIVE_POLL_MS, liveFlowKey, useLiveFlow, useSensors } from "@/features/live/queries";

function setup() {
  const client = createMockClient({ authenticated: true });
  const liveFlow = vi.spyOn(client, "liveFlow");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ApiProvider client={client}>{children}</ApiProvider>
  );
  return { liveFlow, wrapper };
}

describe("useLiveFlow", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  it("fuori da LIVE non chiede nulla (SCENARIO non dipende da TomTom)", async () => {
    const { liveFlow, wrapper } = setup();
    renderHook(() => useLiveFlow(false, { poll: true }), { wrapper });
    await vi.advanceTimersByTimeAsync(3 * LIVE_POLL_MS);
    expect(liveFlow).not.toHaveBeenCalled();
  });

  it("in LIVE legge una volta e, se glielo si chiede, ogni minuto", async () => {
    const { liveFlow, wrapper } = setup();
    const { result } = renderHook(() => useLiveFlow(true, { poll: true }), { wrapper });
    await waitFor(() => expect(result.current.data?.mode).toBe("fresh"));
    expect(liveFlow).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    await waitFor(() => expect(liveFlow).toHaveBeenCalledTimes(2));
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    await waitFor(() => expect(liveFlow).toHaveBeenCalledTimes(3));
  });

  it("non rilegge a scheda in secondo piano (nessuna interrogazione se nessuno guarda)", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(
      () => {
        const query = useLiveFlow(true, { poll: true });
        return { query, queries: useQueryClient() };
      },
      { wrapper },
    );
    await waitFor(() => expect(result.current.query.data).toBeDefined());
    const cached = result.current.queries.getQueryCache().find({ queryKey: liveFlowKey });
    const options = cached?.observers[0]?.options;
    expect(options?.refetchInterval).toBe(LIVE_POLL_MS);
    expect(options?.refetchIntervalInBackground).toBe(false);
  });

  it("senza `poll` legge la cache e non rilegge da solo", async () => {
    const { liveFlow, wrapper } = setup();
    const { result } = renderHook(() => useLiveFlow(true), { wrapper });
    await waitFor(() => expect(result.current.data?.mode).toBe("fresh"));
    await vi.advanceTimersByTimeAsync(5 * LIVE_POLL_MS);
    expect(liveFlow).toHaveBeenCalledTimes(1);
  });

  it("più lettori della stessa cache fanno una sola chiamata", async () => {
    const { liveFlow, wrapper } = setup();
    renderHook(
      () => {
        useLiveFlow(true, { poll: true });
        useLiveFlow(true);
        return useLiveFlow(true);
      },
      { wrapper },
    );
    await vi.advanceTimersByTimeAsync(10);
    expect(liveFlow).toHaveBeenCalledTimes(1);
  });
});

describe("useSensors: i sensori previsti (spech 11.5)", () => {
  function sensorsSetup() {
    const client = createMockClient({ authenticated: true });
    const listSensors = vi.spyOn(client, "listSensors");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ApiProvider client={client}>{children}</ApiProvider>
    );
    return { client, listSensors, wrapper };
  }

  it("fuori da LIVE non chiede nulla", async () => {
    const { listSensors, wrapper } = sensorsSetup();
    renderHook(() => useSensors(false), { wrapper });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(listSensors).not.toHaveBeenCalled();
  });

  it("in LIVE legge l'elenco una volta, anche con più lettori, e non lo rilegge", async () => {
    const { listSensors, wrapper } = sensorsSetup();
    const { result } = renderHook(
      () => {
        useSensors(true);
        return useSensors(true);
      },
      { wrapper },
    );
    await waitFor(() => expect(result.current.data?.length).toBeGreaterThan(0));
    expect(listSensors).toHaveBeenCalledTimes(1);
    expect(result.current.data?.every((s) => s.status === "planned")).toBe(true);
  });

  it("un errore non si riprova e non rompe nulla: l'elenco manca e basta", async () => {
    const { client, listSensors, wrapper } = sensorsSetup();
    listSensors.mockRejectedValue(
      new ApiError(503, { code: "DATA_UNAVAILABLE", message: "non disponibile" }),
    );
    const { result } = renderHook(() => useSensors(true), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
    expect(listSensors).toHaveBeenCalledTimes(1); // senza nuovi tentativi
    expect(client.mode).toBe("mock");
  });
});
