import type { Measured, MetricDelta, MetricsResponse } from "@/api/types";
import type { Better } from "@/lib/format";
import type { EventWindow } from "@/features/shell/ShellProvider";

/** Il nome di una metrica senza il prefisso del run: `m.run1.it2.road.arrival.veh_hours` →
 * `road.arrival.veh_hours`. Il run e l'iterazione sono i primi tre pezzi dell'id. */
export function tail(id: string): string {
  return id.split(".").slice(3).join(".");
}

export function indexMetrics(response: MetricsResponse | undefined): Map<string, Measured> {
  return new Map((response?.metrics ?? []).map((m) => [tail(m.id), m]));
}

export function indexDeltas(response: MetricsResponse | undefined): Map<string, MetricDelta> {
  return new Map((response?.deltas ?? []).map((d) => [tail(d.metric_id), d]));
}

/** Le classi di linea del TPL tra cui si cerca il carico massimo. */
export const TRANSIT_CLASSES = ["metro_line_1", "metro_line_6", "funicular"] as const;
export type TransitClass = (typeof TRANSIT_CLASSES)[number];

export interface CardSpec {
  /** Il nome della metrica principale (senza run e iterazione), per la finestra scelta. */
  main: string;
  /** Un secondo numero da mostrare accanto (gli archi critici: i km). */
  secondary?: string;
  better: Better;
  /** La classe di linea, se la card sceglie la più carica. */
  transitClass?: TransitClass;
}

/** La metrica «più alta» tra le classi di linea: la più carica. Sceglie, non calcola. */
export function busiestClass(
  metrics: Map<string, Measured>,
  window: EventWindow,
): TransitClass | undefined {
  let best: { kind: TransitClass; value: number } | undefined;
  for (const kind of TRANSIT_CLASSES) {
    const found = metrics.get(`transit.${window}.max_section_load.${kind}`);
    if (typeof found?.value === "number" && (!best || found.value > best.value)) {
      best = { kind, value: found.value };
    }
  }
  return best?.kind;
}

/** Le quattro card del motore (la quinta, l'affluenza, viene dall'Evento). Il verso: per ore-veicolo,
 * tempi, archi critici e carichi meno è meglio. */
export function cardSpecs(window: EventWindow, transit: TransitClass | undefined) {
  return {
    vehicleHours: { main: `road.${window}.veh_hours`, better: "lower" },
    odTime: { main: `road.${window}.od_time.mean`, better: "lower" },
    criticalEdges: {
      main: `road.${window}.critical_edges.count`,
      secondary: `road.${window}.critical_edges.km`,
      better: "lower",
    },
    transitLoad: {
      main: transit ? `transit.${window}.max_section_load.${transit}` : "",
      better: "lower",
      transitClass: transit,
    },
  } satisfies Record<string, CardSpec>;
}
