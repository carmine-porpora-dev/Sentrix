import type { RunState } from "@/api/types";

/** «Iterazione n di 3» (07 2 e design): 3 nella barra, come nel design. Un run con più ripianificazioni
 * ha più passate (`iterationTotal`): fino a 4, la prima e tre ripianificazioni (MAX_REPLANS). */
export const ITERATIONS_TOTAL = 3;

/** Le tappe del run nell'ordine in cui il design le mostra (la barra di avanzamento). */
export const RUN_STEPS = [
  "INTAKE",
  "ANALYZE",
  "RECONCILE",
  "PLAN",
  "DISPATCH",
  "AWAIT",
  "REPLAN",
  "VERIFY",
  "DONE",
] as const satisfies readonly RunState[];

/** Cosa mostra il chip dello stato: gli stati del run e «decisione richiesta», che nello spec è lo
 * stato di una misura (non del run) e il design mostra come stato (D6). */
export type RunDisplay = RunState | "DECISION_REQUIRED";

export type RunKind = "run" | "warn" | "done" | "error";

export function runKind(display: RunDisplay): RunKind {
  switch (display) {
    case "AWAIT":
    case "DECISION_REQUIRED":
      return "warn";
    case "DONE":
      return "done";
    case "ERROR":
      return "error";
    default:
      return "run";
  }
}

/** La tappa evidenziata nella barra: la posizione dello stato; per ERROR e per la decisione
 * richiesta, dove il run si è fermato (`fallback`, la tappa dell'ultima volta). */
export function runStepIndex(display: RunDisplay, fallback = 0): number {
  const index = (RUN_STEPS as readonly string[]).indexOf(display);
  return index >= 0 ? index : fallback;
}

/** Il numero dell'iterazione mostrata: `run.iteration` parte da 0 (la prima passata), quindi è l'indice
 * più 1. Non ha un tetto: due passate diverse non possono avere lo stesso numero. */
export function iterationNumber(iteration: number): number {
  return Math.max(iteration, 0) + 1;
}

/** Il totale della barra: quello del design (3) finché il run sta dentro, altrimenti il numero della
 * passata in corso («Iterazione 4 di 4»): mai «4 di 3». */
export function iterationTotal(iteration: number): number {
  return Math.max(ITERATIONS_TOTAL, iterationNumber(iteration));
}
