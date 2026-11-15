import { describe, expect, it } from "vitest";
import type { MetricsResponse } from "@/api/types";
import { comparisonRows } from "@/features/run/comparison";
import { metrics } from "@/test/runPanels";

const all = [metrics(0), metrics(1), metrics(2)];

describe("comparisonRows", () => {
  it("quattro righe del motore, per la finestra scelta, con il verso migliore", () => {
    const rows = comparisonRows("departure", all);
    expect(rows.map((r) => r.metric)).toEqual([
      "road.departure.veh_hours",
      "road.departure.od_time.mean",
      "road.departure.critical_edges.count",
      "transit.departure.max_section_load.metro_line_1",
    ]);
    expect(rows.map((r) => r.better)).toEqual(["lower", "lower", "lower", "lower"]);
    expect(rows[3]?.label).toContain("Linea 1");
  });

  it("una cella per iterazione, con la metrica di quell'iterazione", () => {
    const [hours] = comparisonRows("departure", all);
    expect(hours?.cells).toHaveLength(3);
    all.forEach((response, n) => {
      expect(hours?.cells[n]).toBe(
        response.metrics.find((m) => m.id.endsWith("road.departure.veh_hours")),
      );
    });
  });

  it("la variazione è quella del backend dell'ultima iterazione rispetto alla precedente", () => {
    const [hours] = comparisonRows("departure", all);
    const expected = metrics(2).deltas.find((d) =>
      d.metric_id.endsWith("road.departure.veh_hours"),
    )?.vs_previous;
    expect(hours?.delta).toEqual(expected); // il suo Measured, com'è
    expect(hours?.delta?.id).toContain("delta_previous");
  });

  it("l'altra finestra ha altre metriche", () => {
    const [hours] = comparisonRows("arrival", all);
    expect(hours?.metric).toBe("road.arrival.veh_hours");
    expect(hours?.cells[0]?.id).toContain("arrival");
  });

  it("una metrica che manca in un'iterazione è una cella vuota, non un errore", () => {
    const partial: MetricsResponse = {
      ...metrics(1),
      metrics: metrics(1).metrics.filter((m) => !m.id.endsWith("road.departure.od_time.mean")),
    };
    const rows = comparisonRows("departure", [metrics(0), partial, metrics(2)]);
    const odTime = rows.find((r) => r.metric === "road.departure.od_time.mean");
    expect(odTime?.cells.map((c) => c !== undefined)).toEqual([true, false, true]);
  });

  it("con una sola iterazione non c'è variazione; senza iterazioni non ci sono righe con numeri", () => {
    expect(comparisonRows("departure", [metrics(0)])[0]?.delta).toBeUndefined();
    expect(
      comparisonRows("departure", []).every((r) => r.cells.length === 0 && r.delta === undefined),
    ).toBe(true);
  });

  it("una sola colonna, anche se l'iterazione ha delle variazioni: non c'è con che confrontarla", () => {
    expect(metrics(2).deltas.length).toBeGreaterThan(0);
    expect(comparisonRows("departure", [metrics(2)]).every((r) => r.delta === undefined)).toBe(
      true,
    );
  });

  it("senza metriche del trasporto pubblico la riga del carico non c'è", () => {
    const noTransit = all.map((r) => ({
      ...r,
      metrics: r.metrics.filter((m) => !m.id.includes(".transit.")),
    }));
    const rows = comparisonRows("departure", noTransit);
    expect(rows).toHaveLength(3);
    expect(rows.some((r) => r.metric.startsWith("transit."))).toBe(false);
  });
});
