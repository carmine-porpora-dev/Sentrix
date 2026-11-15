import { describe, expect, it } from "vitest";
import type { MetricsResponse } from "@/api/types";
import { measureEffects } from "@/features/run/effects";
import { fixture } from "@/test/fixtures";
import { measured } from "@/test/measured";

const response = (n: number) => fixture<MetricsResponse>(`run_metrics/iteration_${n}.json`);

describe("measureEffects", () => {
  it("raccoglie, per action_id, prima e dopo dalle metriche di tutte le iterazioni", () => {
    const effects = measureEffects([response(0), response(1), response(2)]);
    expect([...effects.keys()].sort()).toEqual(["act_001", "act_004"]);
    expect(effects.get("act_001")?.before.value).toBe(1.08);
    expect(effects.get("act_001")?.after.value).toBe(1.01);
    expect(effects.get("act_004")?.before.value).toBe(0.97);
    expect(effects.get("act_004")?.after.value).toBe(0.91);
    // sono i `Measured` del motore, non numeri ricalcolati
    expect(effects.get("act_001")?.after.unit).toBe("rapporto");
    expect(effects.get("act_001")?.after.kind).toBe("simulated");
  });

  it("una misura ha l'effetto solo se ci sono tutte e due le metà", () => {
    const only = (half: "before" | "after") => ({
      ...response(1),
      metrics: response(1).metrics.filter(
        (m) => !m.id.includes(".measure_effect.") || m.id.endsWith(`vc_${half}`),
      ),
    });
    expect(measureEffects([only("before")]).size).toBe(0);
    expect(measureEffects([only("after")]).size).toBe(0);
    expect(measureEffects([only("before"), only("before")]).size).toBe(0); // la stessa metà due volte
  });

  it("le iterazioni non ancora arrivate non fanno nulla, e le altre metriche si ignorano", () => {
    expect(measureEffects([]).size).toBe(0);
    expect(measureEffects([undefined, response(0)]).size).toBe(0);
    const other = measured({ id: "m.run1.it1.road.departure.veh_hours" });
    expect(measureEffects([{ ...response(1), metrics: [other] }]).size).toBe(0);
  });

  it("legge una finestra qualunque e un action_id del backend (lettere, cifre, _ e -)", () => {
    const ids = [
      "m.run_ab12.it2.road.arrival.measure_effect.act_ab12cd34_007.vc_before",
      "m.run_ab12.it2.road.arrival.measure_effect.act_ab12cd34_007.vc_after",
    ];
    const body = {
      ...response(2),
      metrics: ids.map((id) => measured({ id, unit: "rapporto", value: 2 })),
    };
    expect([...measureEffects([body]).keys()]).toEqual(["act_ab12cd34_007"]);
  });
});
