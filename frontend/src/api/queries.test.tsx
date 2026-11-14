import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { isDeepStrictEqual } from "node:util";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { createMockClient } from "@/api/mock";
import { ApiProvider } from "@/api/provider";
import { RUN_POLL_MS, isRunFinished, useDepartmentName, useRun } from "@/api/queries";
import type { RunState, RunView } from "@/api/types";
import { fixture } from "@/test/fixtures";

const RUN = "run_mock_match_2027";
const SEQUENCE = fixture<{ run_sequence: { state: RunState; run_view: string }[] }>(
  "manifest.json",
).run_sequence;
const STATES = SEQUENCE.map((frame) => frame.state);
const FRAMES = SEQUENCE.map((frame) => fixture<RunView>(frame.run_view));

afterEach(() => {
  vi.useRealTimers();
});

describe("isRunFinished", () => {
  it.each([
    ["DONE", true],
    ["ERROR", true],
    ["INTAKE", false],
    ["ANALYZE", false],
    ["RECONCILE", false],
    ["PLAN", false],
    ["DISPATCH", false],
    ["AWAIT", false],
    ["REPLAN", false],
    ["VERIFY", false],
  ] as [RunState, boolean][])("%s → %s", (state, finished) => {
    expect(isRunFinished(state)).toBe(finished);
  });

  it("senza dati il run non è finito", () => {
    expect(isRunFinished(undefined)).toBe(false);
  });
});

function setup(client: ApiClient, runId?: string) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ApiProvider client={client}>{children}</ApiProvider>
  );
  return renderHook(() => useRun(runId), { wrapper });
}

/** Un client le cui letture del run danno i fotogrammi del manifest, uno per volta, come il mock
 * (qui senza `import()` dinamici: con i timer finti l'I/O vero non avanza). */
function sequence() {
  const frames = FRAMES;
  const times: number[] = [];
  const getRun = vi.fn(() => {
    times.push(Date.now());
    return Promise.resolve(frames[Math.min(times.length - 1, frames.length - 1)] as RunView);
  });
  return {
    client: { ...createMockClient({ authenticated: true }), getRun } as ApiClient,
    getRun,
    times,
  };
}

/** Un client che risponde subito con una vista fissa (niente `import()`: i timer finti bastano). */
function fixed(view: RunView) {
  const getRun = vi.fn(() => Promise.resolve(view));
  return { client: { ...createMockClient({ authenticated: true }), getRun } as ApiClient, getRun };
}

describe("useRun: polling di 07 3", () => {
  it("rilegge il run ogni secondo, nell'ordine, e si ferma su DONE", async () => {
    vi.useFakeTimers();
    const { client, getRun, times } = sequence();
    const { result } = setup(client, RUN);

    // lo stato mostrato non torna mai indietro (quale lettura sia già a schermo dipende dal
    // momento del rendering, non si controlla lettura per lettura)
    const shown: number[] = [];
    const record = () => {
      const data = result.current.data;
      if (data) shown.push(FRAMES.findIndex((frame) => isDeepStrictEqual(frame, data)));
    };
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    record();
    for (let second = 0; second < 40; second++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(RUN_POLL_MS);
      });
      record();
    }
    expect(result.current.data?.run.state).toBe("DONE");
    // una lettura al secondo, una per fotogramma, poi niente più richieste
    expect(getRun).toHaveBeenCalledTimes(STATES.length);
    expect(times.map((t) => t - (times[0] ?? 0))).toEqual(STATES.map((_, n) => n * RUN_POLL_MS));
    expect(shown).toEqual([...shown].sort((a, b) => a - b));
    expect(shown[0]).toBe(0);
    expect(shown).not.toContain(-1); // sempre uno dei fotogrammi del manifest
  });

  it("l'intervallo è di un secondo (07 3)", () => {
    expect(RUN_POLL_MS).toBe(1000);
  });

  it("a 999 ms non rilegge, a 1000 sì", async () => {
    vi.useFakeTimers();
    const { client, getRun } = fixed(fixture<RunView>("run_view/step_00_intake.json"));
    setup(client, RUN);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(getRun).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RUN_POLL_MS - 1);
    });
    expect(getRun).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(getRun).toHaveBeenCalledTimes(2);
  });

  it("su ERROR si ferma subito", async () => {
    vi.useFakeTimers();
    const { client, getRun } = fixed(fixture<RunView>("run_view_variant_error.json"));
    const { result } = setup(client, RUN);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data?.run.state).toBe("ERROR");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RUN_POLL_MS * 5);
    });
    expect(getRun).toHaveBeenCalledTimes(1);
  });

  it("senza run non chiama il server", async () => {
    const { client, getRun } = sequence();
    const { result } = setup(client);
    expect(result.current.fetchStatus).toBe("idle");
    expect(getRun).not.toHaveBeenCalled();
  });
});

describe("useDepartmentName", () => {
  function names() {
    const vdeptRegistry = vi.fn<ApiClient["vdeptRegistry"]>(() =>
      Promise.resolve(fixture("vdept_registry.json")),
    );
    const client = { ...createMockClient({ authenticated: true }), vdeptRegistry } as ApiClient;
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ApiProvider client={client}>{children}</ApiProvider>
    );
    return { vdeptRegistry, ...renderHook(() => useDepartmentName(), { wrapper }) };
  }

  it("il nome è quello del registro dell'API; finché non arriva, e per un id ignoto, l'id", async () => {
    const { result } = names();
    expect(result.current("municipal_police")).toBe("municipal_police");
    await waitFor(() =>
      expect(result.current("municipal_police")).toBe("Polizia Municipale (virtuale)"),
    );
    expect(result.current("traffic_control")).toBe("Controllo Traffico (virtuale)");
    expect(result.current("sconosciuto")).toBe("sconosciuto");
  });

  it("legge il registro una volta sola, per tutti i componenti, senza run", async () => {
    const { result, vdeptRegistry } = names();
    await waitFor(() => expect(result.current("public_comms")).not.toBe("public_comms"));
    expect(vdeptRegistry).toHaveBeenCalledTimes(1);
    expect(vdeptRegistry).toHaveBeenCalledWith();
  });
});
