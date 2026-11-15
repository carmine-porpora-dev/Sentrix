import { describe, expect, it } from "vitest";
import type { RunState } from "@/api/types";
import { fixture } from "@/test/fixtures";
import {
  ITERATIONS_TOTAL,
  RUN_STEPS,
  iterationNumber,
  iterationTotal,
  runKind,
  runStepIndex,
  type RunDisplay,
} from "@/features/shell/run";

describe("runKind", () => {
  it.each([
    ["INTAKE", "run"],
    ["ANALYZE", "run"],
    ["RECONCILE", "run"],
    ["PLAN", "run"],
    ["DISPATCH", "run"],
    ["REPLAN", "run"],
    ["VERIFY", "run"],
    ["AWAIT", "warn"],
    ["DECISION_REQUIRED", "warn"],
    ["DONE", "done"],
    ["ERROR", "error"],
  ] as [RunDisplay, string][])("%s → %s", (state, kind) => {
    expect(runKind(state)).toBe(kind);
  });
});

describe("runStepIndex", () => {
  it("la posizione dello stato nella sequenza", () => {
    expect(RUN_STEPS.map((state) => runStepIndex(state))).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it("per ERROR e la decisione richiesta (fuori dalla sequenza) vale la tappa data", () => {
    expect(runStepIndex("ERROR", 5)).toBe(5);
    expect(runStepIndex("DECISION_REQUIRED", 7)).toBe(7);
    expect(runStepIndex("ERROR")).toBe(0);
  });

  it("le tappe sono gli stati del run nell'ordine del manifest, senza ERROR", () => {
    const states = fixture<{ run_sequence: { state: RunState }[] }>(
      "manifest.json",
    ).run_sequence.map((frame) => frame.state);
    const order = (state: RunState) => RUN_STEPS.indexOf(state as (typeof RUN_STEPS)[number]);
    // la sequenza del mock non torna mai indietro oltre REPLAN → DISPATCH (la ripianificazione)
    expect(states.every((state) => order(state) >= 0)).toBe(true);
    expect(new Set(states)).toEqual(new Set(RUN_STEPS));
  });
});

describe("iterationNumber", () => {
  it("la prima passata (iterazione 0) è «1»; ogni passata ha il suo numero, senza tetto", () => {
    expect(ITERATIONS_TOTAL).toBe(3);
    expect([0, 1, 2, 3, 4].map(iterationNumber)).toEqual([1, 2, 3, 4, 5]);
    expect(new Set([0, 1, 2, 3].map(iterationNumber)).size).toBe(4); // nessun numero ripetuto
  });

  it("un valore negativo parte da «1»", () => {
    expect(iterationNumber(-2)).toBe(1);
  });
});

describe("iterationTotal", () => {
  it("3 come nel design finché il run sta dentro; oltre, il numero della passata", () => {
    expect([0, 1, 2].map(iterationTotal)).toEqual([3, 3, 3]);
    expect([3, 4].map(iterationTotal)).toEqual([4, 5]);
  });

  it("la passata mostrata non supera mai il totale", () => {
    for (const iteration of [0, 1, 2, 3, 4, 5]) {
      expect(iterationNumber(iteration)).toBeLessThanOrEqual(iterationTotal(iteration));
    }
  });
});
