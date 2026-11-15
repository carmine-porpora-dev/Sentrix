import { Color, createPropertyExpression, v8 } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";
import type { FeatureCollection } from "@/api/types";
import { buildBaseStyle, BASEMAP_SOURCE, tokenFlavor } from "@/features/map/basemap";
import {
  API_LAYER,
  EDIT_EDGES_LAYER,
  EDIT_EDGES_SOURCE,
  EDIT_STOPS_LAYER,
  EDIT_STOPS_SOURCE,
  editLayerSpecs,
  LOAD_MID,
  MAP_LAYER_IDS,
  PROMOTE_ID,
  CLOSURE_DASH,
  CLOSURE_LINE_WIDTH,
  CLOSURE_SYMBOL_SIZE,
  DETOUR_DASH,
  DETOUR_LINE_WIDTH,
  STOP_MIN_ZOOM,
  STOP_RADIUS,
  STOP_RADIUS_MID,
  STOP_RADIUS_OVER,
  boundsOf,
  closureSymbols,
  lineCenter,
  inWindow,
  interactiveIds,
  layerSpecs,
  loadClass,
  sourceId,
} from "@/features/map/layers";
import { MapTokenError, readMapTokens } from "@/features/map/tokens";
import { strings } from "@/i18n/it";
import { afterIterations, chooseIteration, DEFAULT_VIEW } from "@/features/metrics/iterations";
import { DEPARTMENTS, markerState, requestMarkerLabel, requestStateLabel } from "@/lib/departments";
import { fixture } from "@/test/fixtures";
import { GENERATED, generatedReader, mapTokens } from "@/test/mapTokens";

type PropertySpec = Parameters<typeof createPropertyExpression>[1];
const PAINT_SPECS = { ...v8.paint_line, ...v8.paint_circle } as unknown as Record<
  string,
  PropertySpec
>;

/** Il valore di un'espressione di stile **come lo calcola MapLibre** per una feature con queste
 * proprietà. Se l'espressione fallisce (un confronto con `null`, per esempio) MapLibre dà il valore
 * predefinito della proprietà (nero per i colori): è proprio ciò che un controllo sulla forma
 * dell'espressione non vede. */
function evaluate(property: string, expression: unknown, properties: Record<string, unknown>) {
  const parsed = createPropertyExpression(expression, PAINT_SPECS[property] as PropertySpec);
  if (parsed.result !== "success") throw new Error(`espressione non valida: ${property}`);
  return parsed.value.evaluate({ zoom: 0 } as never, { type: "Point", properties } as never);
}

describe("readMapTokens", () => {
  it("legge i colori e le misure dai token del design", () => {
    const t = mapTokens();
    expect(t.colors.bg).toBe("#121110");
    expect(t.colors.congestion).toEqual(["#12BFA0", "#D4A93A", "#EE5663", "#C84BE0"]);
    expect(t.colors.detour).toBe("#3495D2");
    expect(t.colors.closure).toBe("#E8ECF5");
    expect(t.colors.eventArea).toBe("#6B7CF5");
    expect([t.colors.stopLow, t.colors.stopMid, t.colors.stopOver]).toEqual([
      "#12BFA0",
      "#D4A93A",
      "#EE5663",
    ]);
    expect(t.sizes).toEqual({
      roadLine: 6,
      node: 28,
      marker: 44,
      markerBadge: 20,
      iconMarker: 24,
      outline: 2,
    });
    expect(t.opacity).toEqual({ congestionRest: 0.4, congestionHover: 1, eventAreaFill: 0.12 });
  });

  it("se manca un token dice quale (e non inventa un valore)", () => {
    for (const name of ["--color-map-detour", "--size-road-line", "--opacity-event-area-fill"]) {
      const without = (n: string) => (n === name ? "" : generatedReader(n));
      expect(() => readMapTokens(without)).toThrowError(MapTokenError);
      expect(() => readMapTokens(without)).toThrowError(name);
    }
  });

  it("una misura che non è un numero è un errore, non NaN", () => {
    const broken = (n: string) => (n === "--size-node" ? "grande" : generatedReader(n));
    expect(() => readMapTokens(broken)).toThrowError("--size-node");
  });
});

describe("la base map", () => {
  const tokens = mapTokens();
  const style = buildBaseStyle("/tiles/napoli.pmtiles", tokens);

  it("legge il file PMTiles locale, senza host esterni", () => {
    expect(style.sources[BASEMAP_SOURCE]).toEqual({
      type: "vector",
      url: "pmtiles:///tiles/napoli.pmtiles",
    });
    expect(JSON.stringify(style)).not.toMatch(/https?:\/\//);
  });

  it("non ha etichette né glyphs (nessun font da caricare: funziona offline)", () => {
    expect(style.layers.length).toBeGreaterThan(20);
    expect(style.layers.some((layer) => layer.type === "symbol")).toBe(false);
    expect(style.glyphs).toBeUndefined();
    expect(style.sprite).toBeUndefined();
  });

  it("ogni colore dei livelli è un colore dei token del design", () => {
    const allowed = new Set(
      [...GENERATED.entries()]
        .filter(([name]) => name.startsWith("--color-"))
        .map(([, value]) => value.toLowerCase()),
    );
    const colors: string[] = [];
    for (const layer of style.layers) {
      const paint = ("paint" in layer ? layer.paint : undefined) as
        Record<string, unknown> | undefined;
      for (const [key, value] of Object.entries(paint ?? {})) {
        if (key.endsWith("-color") && typeof value === "string") colors.push(value);
      }
    }
    expect(colors.length).toBeGreaterThan(10);
    for (const value of colors) expect(allowed.has(value.toLowerCase()), value).toBe(true);
  });

  it("lo sfondo è il fondo del design, l'acqua e gli edifici salgono di poco", () => {
    const flavor = tokenFlavor(tokens);
    expect(flavor.background).toBe(tokens.colors.bg);
    expect(flavor.earth).toBe(tokens.colors.bg);
    expect(flavor.water).toBe(tokens.colors.surface2);
    expect(flavor.buildings).toBe(tokens.colors.surface1);
  });

  it("le strade grandi si distinguono dalle minori", () => {
    const flavor = tokenFlavor(tokens);
    expect(flavor.major).toBe(tokens.colors.borderStrong);
    expect(flavor.highway).toBe(tokens.colors.borderStrong);
    expect(flavor.minor_service).toBe(tokens.colors.border);
    expect(flavor.other).toBe(tokens.colors.border);
    expect(flavor.major_casing_early).toBe(tokens.colors.bg);
  });
});

describe("loadClass", () => {
  it.each([
    [0, "low"],
    [0.59, "low"],
    [LOAD_MID, "mid"],
    [1, "mid"],
    [1.0001, "over"],
    [1.4, "over"],
    [null, "low"],
    [undefined, "low"],
  ] as const)("%s → %s", (ratio, expected) => {
    expect(loadClass(ratio)).toBe(expected);
  });

  it("la soglia è la prima delle classi di congestione di engine.yaml", () => {
    expect(LOAD_MID).toBe(0.6);
  });

  it("fermate e tratte con lo stesso carico hanno la stessa classe sulle fixture", () => {
    const stops = fixture<FeatureCollection>("run_layers/stops_it2.json");
    const classes = stops.features.map((f) => loadClass(f.properties?.load_ratio as number));
    expect(classes).toContain("over");
  });
});

describe("layerSpecs", () => {
  const tokens = mapTokens();
  /** Gli stili che interessano ai test (l'unione di MapLibre ha tipi diversi per ogni `type`). */
  interface Spec {
    id: string;
    type: string;
    source?: string;
    filter?: unknown;
    paint?: Record<string, unknown>;
  }
  const specs = (
    id: (typeof MAP_LAYER_IDS)[number],
    window: "arrival" | "departure" = "departure",
  ): Spec[] => layerSpecs(id, tokens, window) as unknown as Spec[];

  it("ogni livello della mappa ha il suo livello dell'API", () => {
    expect(Object.keys(API_LAYER).sort()).toEqual([...MAP_LAYER_IDS].sort());
    expect(new Set(Object.values(API_LAYER))).toEqual(
      new Set([
        "edges_vc",
        "closures",
        "critical_intersections",
        "stops",
        "sections",
        "event_area",
        "requests",
      ]),
    );
  });

  it("congestione e deviazioni sono lo stesso livello dell'API, filtrato (nessun endpoint dedicato)", () => {
    expect(specs("congestion")[0]?.source).toBe(sourceId("edges_vc"));
    expect(specs("detours")[0]?.source).toBe(sourceId("edges_vc"));
    expect(JSON.stringify(specs("detours")[0]?.filter)).toContain('["==",["get","detour"],true]');
    // la congestione non ridisegna deviazioni e chiusure
    const filter = JSON.stringify(specs("congestion")[0]?.filter);
    expect(filter).toContain('["!=",["get","closed"],true]');
    expect(filter).toContain('["!=",["get","detour"],true]');
  });

  it("le quattro classi di congestione hanno i quattro colori del design", () => {
    const paint = specs("congestion")[0]?.paint as Record<string, unknown>;
    const color = JSON.stringify(paint["line-color"]);
    tokens.colors.congestion.forEach((c, i) => expect(color).toContain(`${i},"${c}"`));
    expect(paint["line-width"]).toEqual(
      expect.arrayContaining(["interpolate", ["linear"], ["zoom"]]),
    );
    expect(JSON.stringify(paint["line-width"])).toContain(String(tokens.sizes.roadLine));
  });

  it("il colore delle deviazioni e quello dell'area evento sono dei token", () => {
    expect((specs("detours")[0]?.paint as Record<string, unknown>)["line-color"]).toBe(
      tokens.colors.detour,
    );
    const area = specs("event_area");
    expect(area.map((s) => s.type)).toEqual(["fill", "line"]);
    expect((area[0]?.paint as Record<string, unknown>)["fill-opacity"]).toBe(
      tokens.opacity.eventAreaFill,
    );
  });

  it("le deviazioni sono da 4 px, tratteggiate 6 px di tratto e 6 di vuoto, a taglio netto (map-style 2.3, palette v0.5)", () => {
    const spec = specs("detours")[0];
    const paint = spec?.paint as Record<string, unknown>;
    expect(DETOUR_LINE_WIDTH).toBe(4);
    expect(JSON.stringify(paint["line-width"])).toContain("4");
    expect(JSON.stringify(paint["line-width"])).not.toContain(String(tokens.sizes.roadLine));
    // MapLibre misura il tratteggio in multipli dello spessore: 4 px × 1,5 = 6 di tratto e 6 di vuoto
    expect(DETOUR_DASH).toEqual([1.5, 1.5]);
    expect(paint["line-dasharray"]).toEqual([1.5, 1.5]);
    // a taglio netto, come le chiusure: con gli estremi arrotondati il vuoto si chiuderebbe
    expect((spec as unknown as { layout: Record<string, unknown> }).layout["line-cap"]).toBe(
      "butt",
    );
  });

  it("chiusure e deviazioni sono entrambe tratteggiate: si distinguono per colore e ritmo (map-style 2.3)", () => {
    const closure = specs("closures")[0]?.paint as Record<string, unknown>;
    const detour = specs("detours")[0]?.paint as Record<string, unknown>;
    expect(closure["line-color"]).not.toBe(detour["line-color"]);
    expect(closure["line-dasharray"]).not.toEqual(detour["line-dasharray"]);
  });

  it("le chiusure sono da 4 px, tratteggiate 10 px di tratto e 8 di vuoto, a taglio netto (map-style 2.2)", () => {
    const spec = specs("closures")[0];
    const paint = spec?.paint as Record<string, unknown>;
    expect(CLOSURE_LINE_WIDTH).toBe(4);
    // MapLibre misura il tratteggio in multipli dello spessore: 4 px × 2,5 = 10, 4 px × 2 = 8
    expect(CLOSURE_DASH).toEqual([2.5, 2]);
    expect(paint["line-dasharray"]).toEqual([2.5, 2]);
    expect(paint["line-color"]).toBe(tokens.colors.closure);
    expect(JSON.stringify(paint["line-width"])).toContain("4");
    expect((spec as unknown as { layout: Record<string, unknown> }).layout["line-cap"]).toBe(
      "butt",
    );
    expect(CLOSURE_SYMBOL_SIZE).toBe(24);
  });

  it("fermate e tratte: tre colori per classe di carico; la fermata sovraccarica è più grande", () => {
    const stop = specs("stops")[0];
    const paint = stop?.paint as Record<string, unknown>;
    const color = JSON.stringify(paint["circle-color"]);
    expect(color).toContain(tokens.colors.stopOver);
    expect(color).toContain(tokens.colors.stopMid);
    expect(color).toContain(tokens.colors.stopLow);
    // raggi in pixel: 6 basso, 9 medio, 13 oltre la capacità (map-style 2.5, scelta 5A)
    expect([STOP_RADIUS, STOP_RADIUS_MID, STOP_RADIUS_OVER]).toEqual([6, 9, 13]);
    // i tre raggi, valutati come li valuta MapLibre
    const radius = (value: unknown) =>
      evaluate("circle-radius", paint["circle-radius"], { load_ratio: value });
    expect([radius(0.1), radius(LOAD_MID), radius(1), radius(1.01)]).toEqual([6, 9, 9, 13]);
    expect(paint["circle-stroke-width"]).toBe(tokens.sizes.outline); // il bordo `bg` da 2 px
    // a scala di città le fermate non coprono i tratti: si vedono da `STOP_MIN_ZOOM`
    expect(STOP_MIN_ZOOM).toBe(13);
    expect((stop as { minzoom?: number }).minzoom).toBe(STOP_MIN_ZOOM);
    expect(JSON.stringify(stop?.filter)).toContain('["!=",["get","closed"],true]');
    expect(JSON.stringify(specs("sections")[0]?.paint)).toContain(tokens.colors.stopOver);
    expect(JSON.stringify(specs("sections")[0]?.paint)).toContain(String(LOAD_MID));
  });

  it("un carico nullo (capacità 0) non diventa nero: colore neutro, raggio più piccolo, in fermate e tratte", () => {
    const colors = tokens.colors;
    for (const id of ["stops", "sections"] as const) {
      const paint = specs(id)[0]?.paint as Record<string, unknown>;
      const key = id === "stops" ? "circle-color" : "line-color";
      const color = (value: unknown) =>
        evaluate(key, paint[key], value === undefined ? {} : { load_ratio: value });
      // senza rapporto: il neutro del design (e non il nero che MapLibre usa quando l'espressione fallisce)
      expect(color(null)).toEqual(Color.parse(colors.borderStrong));
      expect(color(undefined)).toEqual(Color.parse(colors.borderStrong));
      // con il rapporto: le tre classi, come prima
      expect(color(0)).toEqual(Color.parse(colors.stopLow));
      expect(color(LOAD_MID)).toEqual(Color.parse(colors.stopMid));
      expect(color(1)).toEqual(Color.parse(colors.stopMid));
      expect(color(1.5)).toEqual(Color.parse(colors.stopOver));
    }
    const stop = specs("stops")[0]?.paint as Record<string, unknown>;
    expect(evaluate("circle-radius", stop["circle-radius"], { load_ratio: null })).toBe(
      STOP_RADIUS,
    );
  });

  it("lineCenter: il punto a metà del percorso, non degli estremi", () => {
    // una linea dritta: a metà
    expect(
      lineCenter([
        [14.2, 40.8],
        [14.2, 40.82],
      ]),
    ).toEqual([14.2, 40.81]);
    // un angolo (nord poi est): il centro è sul tratto più lungo, non sulla corda
    const corner = lineCenter([
      [14.2, 40.8],
      [14.2, 40.81],
      [14.2002, 40.81],
    ]) as [number, number];
    expect(corner[0]).toBe(14.2);
    expect(corner[1]).toBeCloseTo(40.805076, 5); // metà di 0,01° a nord più 0,0002° a est (× coseno)
    // la media degli estremi cadrebbe fuori dalla linea
    expect(corner[0]).not.toBeCloseTo(14.2001, 5);
    // i metri della longitudine pesano il coseno della latitudine
    const east = lineCenter([
      [14.2, 40.8],
      [14.21, 40.8],
      [14.21, 40.8001],
    ]) as [number, number];
    expect(east[1]).toBe(40.8);
    expect(east[0]).toBeCloseTo(14.205066, 5);
  });

  it("lineCenter: se il centro cade oltre il primo tratto lo si cerca nei successivi", () => {
    // un tratto corto (0,001°) e uno lungo (0,019°): a metà dei 0,02° totali c'è 40,81 nel secondo
    const center = lineCenter([
      [14.2, 40.8],
      [14.2, 40.801],
      [14.2, 40.82],
    ]) as [number, number];
    expect(center[0]).toBe(14.2);
    expect(center[1]).toBeCloseTo(40.81, 9);
  });

  it("lineCenter: meno di due punti non hanno un centro; una linea di lunghezza zero è il suo punto", () => {
    expect(lineCenter([])).toBeUndefined();
    expect(lineCenter([[14.2, 40.8]])).toBeUndefined();
    expect(
      lineCenter([
        [14.2, 40.8],
        [14.2, 40.8],
      ]),
    ).toEqual([14.2, 40.8]);
  });

  it("closureSymbols: uno per posto, solo della finestra scelta, i due sensi insieme", () => {
    const line = (id: string, coords: number[][], window?: string) => ({
      type: "Feature" as const,
      id,
      geometry: { type: "LineString" as const, coordinates: coords },
      properties: { label: `chiusura ${id}`, ...(window ? { window } : {}) },
    });
    const forward = [
      [14.2, 40.8],
      [14.2, 40.82],
    ];
    const backward = [...forward].reverse();
    const collection = {
      type: "FeatureCollection",
      features: [
        line("departure:a", forward, "departure"),
        line("departure:b", backward, "departure"), // l'altro senso: stessa linea
        line("arrival:a", forward, "arrival"),
        line(
          "departure:c",
          [
            [14.3, 40.9],
            [14.3, 40.92],
          ],
          "departure",
        ),
        // vicina a `a` (0,01° di distanza) ma un'altra chiusura: non si fonde con lei
        line(
          "departure:d",
          [
            [14.2, 40.8],
            [14.2, 40.8004],
          ],
          "departure",
        ),
        line("senza-finestra", [
          [14.4, 40.9],
          [14.4, 40.92],
        ]),
        {
          type: "Feature",
          id: "punto",
          geometry: { type: "Point", coordinates: [14.2, 40.8] },
          properties: {},
        },
      ],
    } as unknown as FeatureCollection;
    const departure = closureSymbols(collection, "departure");
    expect(departure.map((s) => s.id)).toEqual([
      "departure:a",
      "departure:c",
      "departure:d",
      "senza-finestra",
    ]);
    expect(departure[0]?.center).toEqual([14.2, 40.81]);
    expect(departure[0]?.properties.label).toBe("chiusura departure:a");
    expect(closureSymbols(collection, "arrival").map((s) => s.id)).toEqual([
      "arrival:a",
      "senza-finestra",
    ]);
    expect(closureSymbols(undefined, "departure")).toEqual([]);
  });

  it("gli incroci critici sono cerchi grandi quanto il nodo del design", () => {
    const paint = specs("intersections")[0]?.paint as Record<string, unknown>;
    expect(paint["circle-radius"]).toBe(tokens.sizes.node / 2);
  });

  it("le richieste sono marker HTML: nessun livello di stile", () => {
    expect(specs("requests")).toEqual([]);
  });

  it("gli id dei livelli sono unici e il pannello dei livelli li copre tutti", () => {
    const ids = MAP_LAYER_IDS.flatMap((id) => specs(id).map((s) => s.id));
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.length).toBe(8);
  });

  it("interactiveIds: tutti i livelli di disegno tranne i riempimenti", () => {
    expect(interactiveIds("event_area", tokens)).toEqual(["event_area-line"]);
    expect(interactiveIds("congestion", tokens)).toEqual(["congestion-line"]);
    expect(interactiveIds("requests", tokens)).toEqual([]);
  });

  it("gli archi si passano per id con la chiave dell'arco (per lo stato di hover)", () => {
    expect(PROMOTE_ID).toEqual({ edges_vc: "edge_key" });
  });

  it("la finestra scelta filtra le feature che ne hanno una; le altre si vedono sempre", () => {
    expect(inWindow("arrival")).toEqual([
      "any",
      ["!", ["has", "window"]],
      ["==", ["get", "window"], "arrival"],
    ]);
    // lo applicano tutti i livelli di disegno
    for (const id of MAP_LAYER_IDS) {
      for (const window of ["arrival", "departure"] as const) {
        for (const spec of specs(id, window)) {
          expect(JSON.stringify(spec.filter), `${spec.id} ${window}`).toContain(
            JSON.stringify(inWindow(window)),
          );
        }
      }
    }
  });

  it("le classi di congestione sono quattro, in ordine", () => {
    expect(strings.map.congestion).toEqual(["Scorrevole", "Rallentata", "Intensa", "Satura"]);
  });
});

describe("editLayerSpecs (scegliere sulla mappa)", () => {
  const tokens = mapTokens();
  const specs = editLayerSpecs(tokens, ["1-2-0", "3-4-0"], ["6236"]) as unknown as {
    id: string;
    type: string;
    source: string;
    paint: Record<string, unknown>;
  }[];
  const edges = specs.find((spec) => spec.id === EDIT_EDGES_LAYER);
  const stops = specs.find((spec) => spec.id === EDIT_STOPS_LAYER);

  it("un livello per le strade e uno per le fermate, ognuno sulla sua sorgente", () => {
    expect(specs.map((spec) => [spec.id, spec.type, spec.source])).toEqual([
      [EDIT_EDGES_LAYER, "line", EDIT_EDGES_SOURCE],
      [EDIT_STOPS_LAYER, "circle", EDIT_STOPS_SOURCE],
    ]);
  });

  it("le strade scelte hanno il colore delle chiusure, il resto il grigio, il mouse l'accento", () => {
    const color = JSON.stringify(edges?.paint["line-color"]);
    expect(color).toContain(tokens.colors.accent);
    expect(color).toContain(tokens.colors.closure);
    expect(color).toContain(tokens.colors.textSecondary);
    expect(color).toContain('["in",["get","edge_key"],["literal",["1-2-0","3-4-0"]]]');
    // una strada è chiusa anche se lo è solo il suo altro senso (`reverse_key` manca nei sensi unici)
    expect(color).toContain(
      '["in",["to-string",["coalesce",["get","reverse_key"],""]],["literal",["1-2-0","3-4-0"]]]',
    );
    expect(color).toContain('["feature-state","hover"]');
  });

  it("le fermate interrotte sono nel colore d'azione, le altre grigie", () => {
    const color = JSON.stringify(stops?.paint["circle-color"]);
    expect(color).toContain('["in",["get","stop_id"],["literal",["6236"]]]');
    expect(color).toContain(tokens.colors.accent);
    expect(color).toContain(tokens.colors.textSecondary);
    expect(stops?.paint["circle-radius"]).toBe(6);
  });

  it("nessuna scelta: liste vuote, non un errore", () => {
    const none = JSON.stringify(editLayerSpecs(tokens, [], []));
    expect(none).toContain('["literal",[]]');
  });

  it("le sorgenti hanno un nome loro (non si confondono con quelle dell'analisi)", () => {
    expect(EDIT_EDGES_SOURCE).toBe("nuo-edit-edges");
    expect(EDIT_STOPS_SOURCE).toBe("nuo-edit-stops");
    expect(
      new Set([
        EDIT_EDGES_SOURCE,
        EDIT_STOPS_SOURCE,
        ...MAP_LAYER_IDS.map((id) => sourceId(API_LAYER[id])),
      ]).size,
    ).toBe(2 + new Set(MAP_LAYER_IDS.map((id) => API_LAYER[id])).size);
  });
});

describe("boundsOf", () => {
  const collection = (...geometries: unknown[]): FeatureCollection =>
    ({
      type: "FeatureCollection",
      features: geometries.map((geometry) => ({ type: "Feature", properties: {}, geometry })),
    }) as unknown as FeatureCollection;

  it("senza dati, o con una raccolta vuota, non c'è un rettangolo", () => {
    expect(boundsOf(undefined)).toBeUndefined();
    expect(boundsOf(collection())).toBeUndefined();
    expect(boundsOf(collection(null))).toBeUndefined();
  });

  it("un punto è un rettangolo di un punto", () => {
    expect(boundsOf(collection({ type: "Point", coordinates: [14.2, 40.8] }))).toEqual([
      [14.2, 40.8],
      [14.2, 40.8],
    ]);
  });

  it("contiene linee, poligoni e più feature insieme: [ovest, sud] [est, nord]", () => {
    expect(
      boundsOf(
        collection(
          {
            type: "LineString",
            coordinates: [
              [14.1, 40.9],
              [14.3, 40.85],
            ],
          },
          {
            type: "Polygon",
            coordinates: [
              [
                [14.2, 40.8],
                [14.25, 40.95],
                [14.15, 40.82],
                [14.2, 40.8],
              ],
            ],
          },
        ),
      ),
    ).toEqual([
      [14.1, 40.8],
      [14.3, 40.95],
    ]);
  });

  it("l'area dell'evento delle fixture sta dentro il riquadro della base map", () => {
    const area = boundsOf(fixture<FeatureCollection>("run_layers/event_area_it0.json"));
    expect(area).toBeDefined();
    const [[w, s], [e, n]] = area as [[number, number], [number, number]];
    expect(w).toBeGreaterThan(14.1);
    expect(e).toBeLessThan(14.35);
    expect(s).toBeGreaterThan(40.78);
    expect(n).toBeLessThan(40.92);
    expect(e).toBeGreaterThan(w);
    expect(n).toBeGreaterThan(s);
  });
});

describe("chooseIteration e afterIterations", () => {
  const view = (after: boolean, pinned?: number) => ({ after, pinned });

  it("senza iterazioni non c'è nulla da mostrare", () => {
    expect(chooseIteration([], DEFAULT_VIEW)).toBeUndefined();
  });

  it("con la sola 0 c'è solo quella, qualunque sia la scelta", () => {
    expect(chooseIteration([0], view(true))).toBe(0);
    expect(chooseIteration([0], view(false))).toBe(0);
    expect(chooseIteration([0], view(true, 2))).toBe(0);
  });

  it("«Prima» è sempre la 0", () => {
    expect(chooseIteration([0, 1, 2], view(false))).toBe(0);
    expect(chooseIteration([0, 1, 2], view(false, 2))).toBe(0);
  });

  it("«Dopo» è l'ultima, o quella scelta se c'è", () => {
    expect(chooseIteration([0, 1, 2], view(true))).toBe(2);
    expect(chooseIteration([0, 1, 2], view(true, 1))).toBe(1);
    expect(chooseIteration([0, 1], view(true, 2))).toBe(1); // non ancora prodotta: l'ultima
    expect(chooseIteration([0, 1, 2], view(true, 0))).toBe(2); // la 0 non è un «Dopo»
  });

  it("afterIterations: da 1, in ordine", () => {
    expect(afterIterations([2, 0, 1])).toEqual([1, 2]);
    expect(afterIterations([0])).toEqual([]);
    expect(afterIterations([])).toEqual([]);
  });
});

describe("dipartimenti e stati delle richieste", () => {
  it("i quattro dipartimenti hanno l'icona (il nome lo dà il registro dell'API)", () => {
    expect(Object.keys(DEPARTMENTS)).toEqual([
      "traffic_control",
      "municipal_police",
      "transport_control",
      "public_comms",
    ]);
    for (const d of Object.values(DEPARTMENTS)) {
      expect(d.icon).toBeDefined();
    }
  });

  it.each([
    ["CREATED", "normal"],
    ["SENT", "normal"],
    ["RECEIVED", "normal"],
    ["ACCEPTED", "accepted"],
    ["IN_PROGRESS", "accepted"],
    ["COMPLETED", "accepted"],
    ["REJECTED", "rejected"],
    ["boh", "normal"],
  ] as const)("%s → marker %s", (state, expected) => {
    expect(markerState(state)).toBe(expected);
  });

  it("il nome del marker di una richiesta: il bersaglio e lo stato a parole, come li scrive il backend", () => {
    const layer = fixture<FeatureCollection>("run_layers/requests_it2.json");
    const first = layer.features[0]?.properties as Record<string, unknown>;
    expect(requestMarkerLabel(first)).toBe(
      `${String(first.target_label)}: ${requestStateLabel(String(first.state))}`,
    );
    expect(requestMarkerLabel(first)).not.toMatch(/^:/); // il bersaglio c'è (era vuoto con `label`)
    expect(requestMarkerLabel({ target_label: "Via Depretis", state: "IN_PROGRESS" })).toBe(
      "Via Depretis: In corso",
    );
    // lo stato non letto si mostra com'è; senza bersaglio resta il solo stato
    expect(requestMarkerLabel({ target_label: "x", state: "BOH" })).toBe("x: BOH");
    expect(requestMarkerLabel({ label: "non è il bersaglio", state: "ACCEPTED" })).toBe(
      ": Accettata",
    );
  });

  it("ogni stato dell'API ha la sua etichetta, quella della scheda delle richieste", () => {
    const states = [
      "ACCEPTED",
      "COMPLETED",
      "CREATED",
      "IN_PROGRESS",
      "RECEIVED",
      "REJECTED",
      "SENT",
    ];
    expect(Object.keys(strings.panels.ops.state).sort()).toEqual(states.sort());
    for (const state of states) {
      expect(requestStateLabel(state)).toBe(
        (strings.panels.ops.state as Record<string, string>)[state],
      );
    }
    // uno stato sconosciuto si mostra com'è, non come un vuoto
    expect(requestStateLabel("BOH")).toBe("BOH");
    expect(requestStateLabel("")).toBe("");
  });
});
