import { describe, expect, it } from "vitest";
import type { Feature, FeatureCollection } from "@/api/types";
import { draftFromEvent, emptyDraft } from "@/features/events/draft";
import {
  areaBounds,
  bboxParam,
  circleFeature,
  closureLines,
  disruptedPoints,
  draftArea,
  snapBounds,
} from "@/features/events/geo";
import { CIRCLE_STEPS, METERS_PER_DEGREE } from "@/features/map/config";
import { boundsOf } from "@/features/map/layers";
import type { Event } from "@/api/types";
import { fixture } from "@/test/fixtures";

const match = fixture<Event>("event_match_2027.json");

const line = (key: string, extra: Record<string, unknown> = {}): Feature => ({
  type: "Feature",
  geometry: {
    type: "LineString",
    coordinates: [
      [14.2, 40.8],
      [14.21, 40.8],
    ],
  },
  properties: { edge_key: key, ...extra },
});
const collection = (...features: Feature[]): FeatureCollection => ({
  type: "FeatureCollection",
  features,
});

/** Distanza in metri tra due punti (equirettangolare: basta per qualche centinaio di metri). */
function meters(a: number[], b: [number, number]): number {
  const dx = ((a[0] as number) - b[1]) * METERS_PER_DEGREE * Math.cos((b[0] * Math.PI) / 180);
  const dy = ((a[1] as number) - b[0]) * METERS_PER_DEGREE;
  return Math.hypot(dx, dy);
}

describe("circleFeature", () => {
  const feature = circleFeature(40.832, 14.235, 400);
  const ring = (feature.geometry as { coordinates: number[][][] }).coordinates[0] as number[][];

  it("è un poligono chiuso con un punto ogni 360/64 gradi", () => {
    expect(feature.geometry?.type).toBe("Polygon");
    expect(ring).toHaveLength(CIRCLE_STEPS + 1);
    expect(ring[0]).toEqual(ring[CIRCLE_STEPS]);
  });

  it("ogni punto sta a 400 m dal centro (entro i 6 decimali delle coordinate)", () => {
    for (const point of ring) expect(meters(point, [40.832, 14.235])).toBeCloseTo(400, 0);
  });

  it("il raggio cambia la misura, il centro il punto: un cerchio più piccolo sta dentro", () => {
    const small = boundsOf({
      type: "FeatureCollection",
      features: [circleFeature(40.832, 14.235, 100)],
    });
    const big = boundsOf({ type: "FeatureCollection", features: [feature] });
    expect(small?.[0][0]).toBeGreaterThan(big?.[0][0] as number);
    expect(small?.[1][1]).toBeLessThan(big?.[1][1] as number);
  });
});

describe("draftArea", () => {
  it("dall'Evento: il cerchio sul suo centro", () => {
    const area = draftArea(draftFromEvent(match));
    expect(area?.features).toHaveLength(1);
    const bounds = boundsOf(area);
    expect(((bounds?.[0][0] as number) + (bounds?.[1][0] as number)) / 2).toBeCloseTo(14.235, 4);
    expect(((bounds?.[0][1] as number) + (bounds?.[1][1] as number)) / 2).toBeCloseTo(40.832, 4);
  });

  it("senza centro, o con testo che non si legge, o con raggio nullo non c'è un'area", () => {
    expect(draftArea(emptyDraft())).toBeUndefined();
    expect(draftArea({ ...draftFromEvent(match), centerLat: "nord" })).toBeUndefined();
    expect(draftArea({ ...draftFromEvent(match), radius: "0" })).toBeUndefined();
    expect(draftArea({ ...draftFromEvent(match), radius: "" })).toBeUndefined();
  });
});

describe("closureLines", () => {
  const closed = new Set(["a", "b"]);

  it("tiene solo gli archi chiusi, da tutte le fonti, senza doppioni", () => {
    const preview = collection(line("a", { kind: "closure" }), line("x", { kind: "closure" }));
    const picked = collection(line("a"), line("b"));
    const result = closureLines(closed, preview, picked, undefined);
    expect(result.features.map((f) => f.properties?.edge_key)).toEqual(["a", "b"]);
    // vince la prima fonte: l'anteprima del risolutore
    expect(result.features[0]).toBe(preview.features[0]);
  });

  it("dell'anteprima salta ciò che non è una chiusura (centro, destinazioni)", () => {
    const preview = collection(line("a", { kind: "area_center" }), line("b", { kind: "closure" }));
    expect(closureLines(closed, preview).features.map((f) => f.properties?.edge_key)).toEqual([
      "b",
    ]);
  });

  it("una strada è chiusa anche se lo è solo il suo altro senso (reverse_key)", () => {
    const streets = collection(
      line("x", { reverse_key: "b" }),
      line("y", { reverse_key: null }),
      line("z", { reverse_key: 5 }),
    );
    const result = closureLines(new Set(["b", "y"]), streets);
    expect(result.features.map((f) => f.properties?.edge_key)).toEqual(["x", "y"]);
  });

  it("un arco riaperto sparisce anche se l'anteprima lo conosce ancora", () => {
    const preview = collection(line("a", { kind: "closure" }), line("b", { kind: "closure" }));
    expect(closureLines(new Set(["b"]), preview).features).toHaveLength(1);
    expect(closureLines(new Set(), preview).features).toHaveLength(0);
  });

  it("feature senza chiave o fonti assenti non rompono", () => {
    expect(
      closureLines(
        closed,
        undefined,
        collection({ type: "Feature", geometry: null, properties: {} }),
      ).features,
    ).toEqual([]);
  });
});

describe("disruptedPoints", () => {
  const stop = (id: string): Feature => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [14.2, 40.8] },
    properties: { stop_id: id, name: id },
  });

  it("le fermate interrotte tra quelle note", () => {
    const stops = collection(stop("1"), stop("2"), stop("3"));
    expect(
      disruptedPoints(new Set(["2", "3", "9"]), stops).features.map((f) => f.properties?.stop_id),
    ).toEqual(["2", "3"]);
    expect(disruptedPoints(new Set(), stops).features).toEqual([]);
    expect(disruptedPoints(new Set(["1"]), undefined).features).toEqual([]);
  });
});

describe("rettangolo per strade e fermate", () => {
  it("bboxParam: ovest,sud,est,nord", () => {
    expect(
      bboxParam([
        [14.1, 40.78],
        [14.35, 40.92],
      ]),
    ).toBe("14.1,40.78,14.35,40.92");
  });

  it("snapBounds allarga alla griglia, e due viste vicine danno lo stesso rettangolo", () => {
    expect(
      snapBounds([
        [14.2345, 40.8311],
        [14.2411, 40.8399],
      ]),
    ).toEqual([
      [14.23, 40.83],
      [14.25, 40.84],
    ]);
    const a = snapBounds([
      [14.2345, 40.8311],
      [14.2411, 40.8399],
    ]);
    const b = snapBounds([
      [14.2361, 40.8322],
      [14.2434, 40.8388],
    ]);
    expect(a).toEqual(b);
  });

  it("snapBounds contiene sempre il rettangolo di partenza ed è idempotente", () => {
    const original: [[number, number], [number, number]] = [
      [14.2001, 40.8001],
      [14.2599, 40.8599],
    ];
    const snapped = snapBounds(original);
    expect(snapped[0][0]).toBeLessThanOrEqual(original[0][0]);
    expect(snapped[0][1]).toBeLessThanOrEqual(original[0][1]);
    expect(snapped[1][0]).toBeGreaterThanOrEqual(original[1][0]);
    expect(snapped[1][1]).toBeGreaterThanOrEqual(original[1][1]);
    expect(snapBounds(snapped)).toEqual(snapped);
  });

  it("un valore già sulla griglia non si allarga: da 14,00 a 14,40 e da 40,50 a 41,00, un passo alla volta", () => {
    // in virgola mobile 40,84 / 0,01 non è 4084 esatto: senza tolleranza il bordo cresce di un passo
    for (let step = 1400; step <= 4100; step++) {
      const value = Number((step * 0.01).toFixed(4));
      const snapped = snapBounds([
        [value, value],
        [value, value],
      ]);
      expect(snapped, String(value)).toEqual([
        [value, value],
        [value, value],
      ]);
    }
  });

  it("areaBounds: attorno al centro, più largo del cerchio; senza centro non c'è", () => {
    const bounds = areaBounds(draftFromEvent(match));
    expect(bounds).toBeDefined();
    expect(bounds?.[0][1]).toBeLessThan(40.832);
    expect(bounds?.[1][1]).toBeGreaterThan(40.832);
    expect(bounds?.[0][0]).toBeLessThan(14.235);
    expect(areaBounds(emptyDraft())).toBeUndefined();
  });
});
