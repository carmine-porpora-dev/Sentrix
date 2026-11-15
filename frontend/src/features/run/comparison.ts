import type { Measured, MetricsResponse } from "@/api/types";
import {
  busiestClass,
  cardSpecs,
  indexDeltas,
  indexMetrics,
  type CardSpec,
} from "@/features/metrics/cards";
import type { EventWindow } from "@/features/shell/ShellProvider";
import type { Better } from "@/lib/format";
import { strings } from "@/i18n/it";

export interface ComparisonRow {
  /** Il nome della metrica (senza run e iterazione). */
  metric: string;
  label: string;
  better: Better;
  /** Una cella per iterazione (0…n); `undefined` se quella metrica non c'è per quell'iterazione. */
  cells: (Measured | undefined)[];
  /** La variazione dell'ultima iterazione rispetto alla precedente (dal backend, `Measured`). */
  delta: Measured | undefined;
}

/** Le righe del confronto tra iterazioni (design, schermata 08): le stesse quattro metriche del
 * motore delle card, per la finestra scelta, una colonna per iterazione e la variazione dell'ultima
 * rispetto alla precedente. Sceglie e affianca numeri che il backend ha già calcolato: non somma,
 * non confronta, non calcola variazioni. */
export function comparisonRows(
  window: EventWindow,
  responses: readonly (MetricsResponse | undefined)[],
): ComparisonRow[] {
  const latest = responses.at(-1);
  const indexes = responses.map(indexMetrics);
  const specs = cardSpecs(window, busiestClass(indexMetrics(latest), window));
  const copy = strings.metrics;
  const rows: [CardSpec, string][] = [
    [specs.vehicleHours, copy.cards.vehicleHours],
    [specs.odTime, copy.cards.odTime],
    [specs.criticalEdges, copy.cards.criticalEdges],
    [
      specs.transitLoad,
      specs.transitLoad.transitClass
        ? `${copy.cards.transitLoad} · ${copy.transitClasses[specs.transitLoad.transitClass]}`
        : copy.cards.transitLoad,
    ],
  ];
  const deltas = indexDeltas(latest);
  return rows
    .filter(([spec]) => spec.main !== "")
    .map(([spec, label]) => ({
      metric: spec.main,
      label,
      better: spec.better,
      cells: indexes.map((index) => index.get(spec.main)),
      delta: responses.length > 1 ? (deltas.get(spec.main)?.vs_previous ?? undefined) : undefined,
    }));
}
