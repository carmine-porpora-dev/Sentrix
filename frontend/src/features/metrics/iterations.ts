export interface IterationView {
  after: boolean;
  /** L'iterazione scelta con il selettore (da 1); `undefined` = segue la più recente. */
  pinned: number | undefined;
}

export const DEFAULT_VIEW: IterationView = { after: true, pinned: undefined };

/** L'iterazione da mostrare tra quelle di cui ci sono i dati. Con la sola 0 c'è solo quella;
 * «Prima» è sempre la 0; «Dopo» è la scelta se esiste, altrimenti l'ultima. */
export function chooseIteration(
  available: readonly number[],
  view: IterationView,
): number | undefined {
  if (available.length === 0) return undefined;
  const latest = Math.max(...available);
  if (latest === 0 || !view.after) return 0;
  if (view.pinned !== undefined && view.pinned >= 1 && available.includes(view.pinned)) {
    return view.pinned;
  }
  return latest;
}

/** Le iterazioni che «Dopo» può mostrare (da 1), in ordine. */
export function afterIterations(available: readonly number[]): number[] {
  return available.filter((n) => n >= 1).sort((a, b) => a - b);
}
