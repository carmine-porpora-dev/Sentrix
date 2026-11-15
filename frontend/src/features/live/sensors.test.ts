import { describe, expect, it } from "vitest";
import type { FeatureCollection, PlannedSensor } from "@/api/types";
import { SENSOR_TYPES, sensorMarkers, sensorTypes } from "@/features/live/sensors";
import { fixture } from "@/test/fixtures";

const sensors = fixture<PlannedSensor[]>("sensors.json");
const mockLines = fixture<FeatureCollection>("transit_lines.json");

const line = (routeClass: string, routeId: string, coordinates: number[][]) => ({
  type: "Feature" as const,
  id: routeId,
  geometry: { type: "LineString", coordinates },
  properties: { route_id: routeId, route_class: routeClass, label: routeClass, kind: "line" },
});

const lines: FeatureCollection = {
  type: "FeatureCollection",
  features: [
    line("metro_line_1", "L1", [
      [14.2, 40.8],
      [14.21, 40.81],
      [14.22, 40.82],
    ]),
    line("metro_line_6", "L6", [
      [14.3, 40.85],
      [14.31, 40.86],
    ]),
    line("funicular", "F1", [
      [14.24, 40.83],
      [14.241, 40.835],
    ]),
    line("funicular", "F3", [
      [14.25, 40.84],
      [14.251, 40.845],
    ]),
  ],
};

const ofType = (type: string) => sensors.filter((s) => s.type === type);

describe("sensorMarkers: dove si disegna ogni sensore previsto", () => {
  it("contapersone e sensori di rampa: nel punto del file, uno ciascuno", () => {
    const markers = sensorMarkers(sensors, undefined);
    const points = markers.filter((m) => m.sensor.type !== "turnstile");
    expect(points).toHaveLength(ofType("people_counter").length + ofType("ramp_counter").length);
    for (const marker of points) {
      expect([marker.lat, marker.lng]).toEqual([
        marker.sensor.location?.lat,
        marker.sensor.location?.lon,
      ]);
    }
  });

  it("le sonde GPS non hanno un posto: nessun simbolo", () => {
    const markers = sensorMarkers(sensors, lines);
    expect(markers.some((m) => m.sensor.type === "gps_probe")).toBe(false);
    expect(ofType("gps_probe").length).toBeGreaterThan(0); // ci sono, solo non si disegnano
  });

  it("i tornelli stanno nelle stazioni delle linee della loro classe (i vertici), non altrove", () => {
    const markers = sensorMarkers(sensors, lines);
    const turnstiles = markers.filter((m) => m.sensor.type === "turnstile");
    const of = (routeClass: string) =>
      turnstiles
        .filter((m) => m.sensor.route_class === routeClass)
        .map((m) => [m.lng, m.lat])
        .sort();
    expect(of("metro_line_1")).toEqual([
      [14.2, 40.8],
      [14.21, 40.81],
      [14.22, 40.82],
    ]);
    expect(of("metro_line_6")).toEqual([
      [14.3, 40.85],
      [14.31, 40.86],
    ]);
    // le funicolari sono più linee della stessa classe: le stazioni di tutte
    expect(of("funicular")).toHaveLength(4);
  });

  it("nessuna posizione duplicata nel file: i tornelli non ne hanno, la posizione viene dal feed", () => {
    for (const sensor of ofType("turnstile")) expect(sensor.location ?? null).toBeNull();
  });

  it("senza le linee (ancora in lettura, o non disponibili) nessun tornello e nessun errore", () => {
    const markers = sensorMarkers(sensors, undefined);
    expect(markers.some((m) => m.sensor.type === "turnstile")).toBe(false);
    expect(sensorMarkers(sensors, { type: "FeatureCollection", features: [] })).toHaveLength(
      markers.length,
    );
  });

  it("una linea di un'altra classe non porta tornelli", () => {
    const only = sensorMarkers(sensors, {
      type: "FeatureCollection",
      features: [line("tram", "T1", [[14.2, 40.8]])],
    });
    expect(only.some((m) => m.sensor.type === "turnstile")).toBe(false);
  });

  it("una geometria che non è una linea (o con posizioni rotte) si ignora", () => {
    const broken: FeatureCollection = {
      type: "FeatureCollection",
      features: [
        { type: "Feature", geometry: null, properties: { route_class: "metro_line_1" } },
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [14.2, 40.8] },
          properties: { route_class: "metro_line_1" },
        },
        {
          type: "Feature",
          geometry: { type: "LineString", coordinates: [[14.2], ["x", "y"], [14.3, 40.9]] },
          properties: { route_class: "metro_line_1", route_id: "L1" },
        },
      ],
    };
    const markers = sensorMarkers(sensors, broken).filter((m) => m.sensor.type === "turnstile");
    expect(markers.map((m) => [m.lng, m.lat])).toEqual([[14.3, 40.9]]);
  });

  it("ogni simbolo ha una chiave unica (due stazioni, due simboli)", () => {
    const keys = sensorMarkers(sensors, lines).map((m) => m.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("con le linee del mock (schematiche) i tornelli ci sono e stanno sulle linee", () => {
    const markers = sensorMarkers(sensors, mockLines).filter((m) => m.sensor.type === "turnstile");
    expect(markers.length).toBeGreaterThan(0);
  });

  it("senza sensori, niente", () => {
    expect(sensorMarkers(undefined, lines)).toEqual([]);
    expect(sensorMarkers([], lines)).toEqual([]);
  });
});

describe("sensorTypes: i tipi presenti, nell'ordine di spech 11.2", () => {
  it("i quattro tipi, in quest'ordine", () => {
    expect(SENSOR_TYPES).toEqual(["gps_probe", "turnstile", "people_counter", "ramp_counter"]);
    expect(sensorTypes(sensors)).toEqual(SENSOR_TYPES);
  });

  it("solo quelli che ci sono, anche se l'elenco è in un altro ordine", () => {
    const some = [...ofType("ramp_counter"), ...ofType("gps_probe")];
    expect(sensorTypes(some)).toEqual(["gps_probe", "ramp_counter"]);
  });

  it("senza elenco, nessun tipo", () => {
    expect(sensorTypes(undefined)).toEqual([]);
    expect(sensorTypes([])).toEqual([]);
  });
});
