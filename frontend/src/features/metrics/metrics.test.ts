import { describe, expect, it } from "vitest";
import type { Event, MetricsResponse } from "@/api/types";
import { attendanceMeasured } from "@/features/metrics/attendance";
import {
  busiestClass,
  cardSpecs,
  indexDeltas,
  indexMetrics,
  tail,
  type CardSpec,
} from "@/features/metrics/cards";
import { fixture } from "@/test/fixtures";
import { measured } from "@/test/measured";

describe("tail", () => {
  it("toglie il run e l'iterazione", () => {
    expect(tail("m.run1.it2.road.arrival.veh_hours")).toBe("road.arrival.veh_hours");
    expect(tail("m.run_mock_match_2027.it0.transit.departure.max_section_load.metro_line_6")).toBe(
      "transit.departure.max_section_load.metro_line_6",
    );
    expect(tail("m.r.it1.delta_baseline.road.departure.od_time.mean")).toBe(
      "delta_baseline.road.departure.od_time.mean",
    );
  });
});

describe("indexMetrics e indexDeltas", () => {
  const response = fixture<MetricsResponse>("run_metrics/iteration_2.json");

  it("indicizzano per nome, senza run e iterazione", () => {
    const metrics = indexMetrics(response);
    expect(metrics.get("road.departure.veh_hours")?.value).toBe(4690);
    expect(metrics.size).toBe(response.metrics.length);
    const deltas = indexDeltas(response);
    expect(deltas.get("road.departure.veh_hours")?.vs_baseline?.value).toBe(-130);
    expect(deltas.size).toBe(response.deltas.length);
  });

  it("senza risposta sono vuoti", () => {
    expect(indexMetrics(undefined).size).toBe(0);
    expect(indexDeltas(undefined).size).toBe(0);
  });
});

describe("busiestClass", () => {
  const index = (loads: Record<string, number | string>) =>
    new Map(
      Object.entries(loads).map(([name, value]) => [
        `transit.departure.max_section_load.${name}`,
        measured({
          id: `m.r.it0.transit.departure.max_section_load.${name}`,
          value,
          unit: "rapporto",
        }),
      ]),
    );

  it("sceglie la classe con il carico più alto", () => {
    expect(
      busiestClass(index({ metro_line_1: 0.8, metro_line_6: 1.4, funicular: 0.5 }), "departure"),
    ).toBe("metro_line_6");
    expect(
      busiestClass(index({ metro_line_1: 3, metro_line_6: 1.4, funicular: 0.5 }), "departure"),
    ).toBe("metro_line_1");
    expect(
      busiestClass(index({ metro_line_1: 0.8, metro_line_6: 1.4, funicular: 5 }), "departure"),
    ).toBe("funicular");
  });

  it("a parità vince la prima nell'ordine (L1, L6, funicolari)", () => {
    expect(
      busiestClass(index({ metro_line_1: 1, metro_line_6: 1, funicular: 1 }), "departure"),
    ).toBe("metro_line_1");
    expect(busiestClass(index({ metro_line_6: 1, funicular: 1 }), "departure")).toBe(
      "metro_line_6",
    );
  });

  it("anche con tutti i carichi a zero una classe c'è", () => {
    expect(
      busiestClass(index({ metro_line_1: 0, metro_line_6: 0, funicular: 0 }), "departure"),
    ).toBe("metro_line_1");
  });

  it("si guarda la finestra scelta", () => {
    const arrival = new Map([
      ["transit.arrival.max_section_load.funicular", measured({ value: 2, unit: "rapporto" })],
    ]);
    expect(busiestClass(arrival, "arrival")).toBe("funicular");
    expect(busiestClass(arrival, "departure")).toBeUndefined();
  });

  it("senza metriche TPL, o con testo, non c'è una classe", () => {
    expect(busiestClass(new Map(), "departure")).toBeUndefined();
    expect(busiestClass(index({ metro_line_1: "boh" }), "departure")).toBeUndefined();
  });

  it("sulle fixture è la Linea 1 (1,12) in entrambe le finestre", () => {
    const metrics = indexMetrics(fixture<MetricsResponse>("run_metrics/iteration_2.json"));
    expect(busiestClass(metrics, "departure")).toBe("metro_line_1");
    expect(busiestClass(metrics, "arrival")).toBe("metro_line_1");
  });
});

describe("cardSpecs", () => {
  it("le metriche delle card per la finestra scelta, con il verso", () => {
    expect(cardSpecs("departure", "metro_line_6")).toEqual({
      vehicleHours: { main: "road.departure.veh_hours", better: "lower" },
      odTime: { main: "road.departure.od_time.mean", better: "lower" },
      criticalEdges: {
        main: "road.departure.critical_edges.count",
        secondary: "road.departure.critical_edges.km",
        better: "lower",
      },
      transitLoad: {
        main: "transit.departure.max_section_load.metro_line_6",
        better: "lower",
        transitClass: "metro_line_6",
      },
    });
  });

  it("in arrivo tutte le metriche sono quelle dell'arrivo", () => {
    const specs = cardSpecs("arrival", "funicular");
    expect(specs.vehicleHours.main).toBe("road.arrival.veh_hours");
    expect(specs.transitLoad.main).toBe("transit.arrival.max_section_load.funicular");
  });

  it("senza una classe di linea la card del TPL non ha metrica", () => {
    expect(cardSpecs("departure", undefined).transitLoad.main).toBe("");
  });

  it("ogni nome di metrica esiste nelle fixture (il contratto con il backend)", () => {
    const names = new Set(
      indexMetrics(fixture<MetricsResponse>("run_metrics/iteration_1.json")).keys(),
    );
    for (const window of ["arrival", "departure"] as const) {
      for (const kind of ["metro_line_1", "metro_line_6", "funicular"] as const) {
        const specs = cardSpecs(window, kind);
        const all: CardSpec[] = [
          specs.vehicleHours,
          specs.odTime,
          specs.criticalEdges,
          specs.transitLoad,
        ];
        for (const spec of all) {
          expect(names.has(spec.main), spec.main).toBe(true);
          if (spec.secondary) expect(names.has(spec.secondary), spec.secondary).toBe(true);
        }
      }
    }
  });
});

describe("attendanceMeasured", () => {
  const event = fixture<Event>("event_match_2027.json");

  it("è il numero dell'Evento per il livello del run, SIMULATO, in persone", () => {
    for (const [level, persons] of [
      ["low", 50000],
      ["mid", 150000],
      ["high", 300000],
    ] as const) {
      const m = attendanceMeasured(event, level, "run1");
      expect(m.value).toBe(persons);
      expect(m.unit).toBe("pax");
      expect(m.kind).toBe("simulated");
    }
  });

  it("dichiara da dove viene: l'Evento, la revisione, il livello e la fonte indicata", () => {
    const m = attendanceMeasured(event, "mid", "run1");
    expect(m.source).toBe("Evento match_2027 (revisione 1)");
    expect(m.method).toBe("affluenza del livello mid indicata nell'Evento, ipotesi di scenario");
    expect(m.inputs).toEqual(["event match_2027 rev 1", "livello di affluenza mid"]);
    expect(m.assumptions).toEqual([
      "fonte indicata nell'Evento: Ipotesi di scenario (documento di progetto 5.2)",
    ]);
    expect(m.as_of).toBe(event.updated_at);
  });

  it("è la stessa che scrive il backend tra le metriche dell'iterazione 0 (contratto)", () => {
    // le fixture sono scritte dal backend con `attendance_measured`: se il testo o l'id di uno dei due
    // cambia e l'altro no, questo test lo dice (altrimenti la card e il tooltip divergerebbero in silenzio)
    const fromApi = fixture<MetricsResponse>("run_metrics/iteration_0.json").metrics.find((m) =>
      m.id.endsWith(".event.attendance"),
    );
    expect(fromApi).toBeDefined();
    expect(attendanceMeasured(event, "mid", "run_mock_match_2027")).toEqual(fromApi);
  });

  it("l'id è valido per l'API (m.<run>.it0.event.attendance)", () => {
    const m = attendanceMeasured(event, "mid", "run_mock_match_2027");
    expect(m.id).toBe("m.run_mock_match_2027.it0.event.attendance");
    expect(m.id).toMatch(/^m(\.[A-Za-z0-9_-]+)+$/);
  });

  it("senza fonte indicata non ci sono assunzioni", () => {
    const noSource = { ...event, attendance: { ...event.attendance, source_ref: null } };
    expect(attendanceMeasured(noSource, "mid", "r").assumptions).toEqual([]);
    const blank = { ...event, attendance: { ...event.attendance, source_ref: "   " } };
    expect(attendanceMeasured(blank, "mid", "r").assumptions).toEqual([]);
  });
});
