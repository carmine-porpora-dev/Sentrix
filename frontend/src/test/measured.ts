import type { Measured } from "@/api/types";

/** Un `Measured` di prova: i campi obbligatori con valori neutri, `changes` li cambia. */
export function measured(changes: Partial<Measured> = {}): Measured {
  return {
    id: "m.run1.it0.road.departure.veh_hours",
    value: 1240,
    unit: "veic·h",
    kind: "simulated",
    source: "engine.metrics v1",
    method: "Σ archi v × t / 60",
    inputs: ["event e1 rev 3", "osm 2026-11-07"],
    assumptions: ["modello statico non calibrato"],
    as_of: "2026-11-09T10:00:50+01:00",
    ...changes,
  };
}
