import type { Measured, MetricsResponse } from "@/api/types";

/** L'effetto locale di una misura stradale (02 7): il massimo v/c sugli archi che tocca, prima e dopo
 * l'iterazione in cui entra in vigore. Sono due `Measured` del motore; l'interfaccia li affianca. */
export interface MeasureEffect {
  before: Measured;
  after: Measured;
}

const EFFECT_ID =
  /^m\.[^.]+\.it\d+\.road\.(?:arrival|departure)\.measure_effect\.([^.]+)\.vc_(before|after)$/;

/** Gli effetti nelle metriche di tutte le iterazioni, per action_id. Una misura ha l'effetto nelle
 * metriche dell'iterazione in cui è entrata in vigore; se manca una delle due metà (o le metriche non
 * sono ancora arrivate) la misura non ha un effetto da mostrare. */
export function measureEffects(
  responses: readonly (MetricsResponse | undefined)[],
): ReadonlyMap<string, MeasureEffect> {
  const halves = new Map<string, { before?: Measured; after?: Measured }>();
  for (const response of responses) {
    for (const metric of response?.metrics ?? []) {
      const match = EFFECT_ID.exec(metric.id);
      if (!match) continue;
      const [, actionId, half] = match as unknown as [string, string, "before" | "after"];
      halves.set(actionId, { ...halves.get(actionId), [half]: metric });
    }
  }
  const effects = new Map<string, MeasureEffect>();
  for (const [actionId, { before, after }] of halves) {
    if (before && after) effects.set(actionId, { before, after });
  }
  return effects;
}
