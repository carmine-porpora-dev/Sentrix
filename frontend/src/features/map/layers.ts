import type { ExpressionSpecification, LayerSpecification } from "maplibre-gl";
import type { FeatureCollection, LayerName } from "@/api/types";
import type { MapTokens } from "@/features/map/tokens";
import type { EventWindow } from "@/features/shell/ShellProvider";

/** I livelli che l'utente accende e spegne (spec 07 5). Le deviazioni sono lo stesso livello
 * `edges_vc` filtrato su `detour=true`, ma si accendono a parte. */
export const MAP_LAYER_IDS = [
  "congestion",
  "detours",
  "closures",
  "event_area",
  "sections",
  "stops",
  "intersections",
  "requests",
] as const;
export type MapLayerId = (typeof MAP_LAYER_IDS)[number];

/** Da quale livello dell'API vengono i dati di ogni livello della mappa. */
export const API_LAYER: Record<MapLayerId, LayerName> = {
  congestion: "edges_vc",
  detours: "edges_vc",
  closures: "closures",
  event_area: "event_area",
  sections: "sections",
  stops: "stops",
  intersections: "critical_intersections",
  requests: "requests",
};

/** Il carico oltre cui una fermata o una tratta è «media» (sotto: «bassa»; sopra 1: «oltre la
 * capacità»). È la prima soglia delle classi di congestione stradale (`metrics.vc_classes` di
 * engine.yaml): per fermate e tratte la spec non ne dà una, qui si riusa quella. */
export const LOAD_MID = 0.6;
// Le misure dei livelli che i token del design non hanno: quelle di `design/map-style.md` (v1 del
// designer, scelte 2B, 3B e 5A; ne elenca i nomi dei token da aggiungere, che non ci sono). Sono
// costanti, con la fonte qui; colori e le altre misure (6 px della congestione, 2 px dei contorni)
// vengono dai token.
/** Spessore di chiusure e deviazioni (la congestione è 6 px, `size-road-line`). */
export const CLOSURE_LINE_WIDTH = 4;
export const DETOUR_LINE_WIDTH = 4;
/** Il tratteggio delle chiusure: 10 px di tratto e 8 di vuoto, in multipli dello spessore (MapLibre). */
export const CLOSURE_DASH: [number, number] = [10 / CLOSURE_LINE_WIDTH, 8 / CLOSURE_LINE_WIDTH];
/** Il tratteggio delle deviazioni (palette v0.5, 14/11, `map-style.md` 2.3): 6 px di tratto e 6 di vuoto,
 * in multipli dello spessore come quello delle chiusure. Gli estremi sono a taglio netto: con quelli
 * arrotondati i 2 px di raggio per lato mangerebbero il vuoto e il tratteggio non si leggerebbe. */
export const DETOUR_DASH: [number, number] = [6 / DETOUR_LINE_WIDTH, 6 / DETOUR_LINE_WIDTH];
/** Il disco del divieto al centro di una chiusura. */
export const CLOSURE_SYMBOL_SIZE = 24;
/** Sotto questo zoom le fermate non si disegnano: a scala di città (LIVE mostra tutta la rete del
 * TPL, migliaia di fermate) coprirebbero i tratti, che sono il dato; ingrandendo compaiono. */
export const STOP_MIN_ZOOM = 13;
/** Raggio dei cerchi delle fermate per classe di carico: basso, medio, oltre la capacità. */
export const STOP_RADIUS = 6;
export const STOP_RADIUS_MID = 9;
export const STOP_RADIUS_OVER = 13;

export type LoadClass = "low" | "mid" | "over";

/** La classe di carico di una fermata o di una tratta (stessa regola dei colori sulla mappa). */
export function loadClass(loadRatio: number | null | undefined): LoadClass {
  if (loadRatio === null || loadRatio === undefined) return "low";
  if (loadRatio > 1) return "over";
  return loadRatio >= LOAD_MID ? "mid" : "low";
}

/** Il nome della sorgente GeoJSON di un livello dell'API. */
export const sourceId = (layer: LayerName) => `nuo-${layer}`;

const SOURCE: Record<MapLayerId, string> = {
  congestion: sourceId("edges_vc"),
  detours: sourceId("edges_vc"),
  closures: sourceId("closures"),
  event_area: sourceId("event_area"),
  sections: sourceId("sections"),
  stops: sourceId("stops"),
  intersections: sourceId("critical_intersections"),
  requests: sourceId("requests"),
};

/** Le sorgenti GeoJSON che hanno bisogno di un id di feature per lo stato `hover` (gli archi). */
export const PROMOTE_ID: Partial<Record<LayerName, string>> = { edges_vc: "edge_key" };

/** Le feature di una finestra: quelle con la proprietà `window` (gli archi di `edges_vc`, calcolati
 * per finestra) solo se è la scelta; le altre, che non ne hanno, sempre. Un filtro dello stile, non
 * un ricalcolo dei dati: cambiare finestra non rimette in gioco le sorgenti. */
export const inWindow = (window: EventWindow): ExpressionSpecification => [
  "any",
  ["!", ["has", "window"]],
  ["==", ["get", "window"], window],
];

/** Una larghezza che cresce con lo zoom fino a `px` (la misura del token). */
const zoomWidth = (px: number) =>
  ["interpolate", ["linear"], ["zoom"], 11, px * 0.35, 15, px] as unknown as number;

/** Le sorgenti e i livelli da cliccare quando si sceglie sulla mappa (Event Manager, 07 4): le
 * strade che si possono chiudere e le fermate che si possono interrompere. */
export const EDIT_EDGES_SOURCE = "nuo-edit-edges";
export const EDIT_STOPS_SOURCE = "nuo-edit-stops";
export const EDIT_EDGES_LAYER = "edit-edges-line";
export const EDIT_STOPS_LAYER = "edit-stops-circle";
/** Raggio dei cerchi delle fermate da scegliere (px): come quello delle fermate dell'analisi. */
export const EDIT_STOP_RADIUS = STOP_RADIUS;

/** I livelli di scelta: le strade e le fermate candidate in grigio, quelle già scelte colorate (strade
 * come le chiusure, fermate nel colore d'azione), l'elemento sotto il mouse in evidenza. */
export function editLayerSpecs(
  tokens: MapTokens,
  closedKeys: readonly string[],
  disruptedIds: readonly string[],
): LayerSpecification[] {
  const { colors: c, sizes } = tokens;
  const hover = ["boolean", ["feature-state", "hover"], false];
  const keys = ["literal", [...closedKeys]];
  // una strada è chiusa se lo è uno dei suoi due sensi (`reverse_key` manca nei sensi unici)
  const closed = [
    "any",
    ["in", ["get", "edge_key"], keys],
    ["in", ["to-string", ["coalesce", ["get", "reverse_key"], ""]], keys],
  ];
  const disrupted = ["in", ["get", "stop_id"], ["literal", [...disruptedIds]]];
  return [
    {
      id: EDIT_EDGES_LAYER,
      type: "line",
      source: EDIT_EDGES_SOURCE,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": [
          "case",
          hover,
          c.accent,
          closed,
          c.closure,
          c.textSecondary,
        ] as unknown as string,
        "line-width": zoomWidth(sizes.roadLine),
        "line-opacity": 0.85,
      },
    },
    {
      id: EDIT_STOPS_LAYER,
      type: "circle",
      source: EDIT_STOPS_SOURCE,
      paint: {
        "circle-color": [
          "case",
          hover,
          c.accent,
          disrupted,
          c.accent,
          c.textSecondary,
        ] as unknown as string,
        "circle-radius": EDIT_STOP_RADIUS,
        "circle-stroke-color": c.bg,
        "circle-stroke-width": sizes.outline,
      },
    },
  ];
}

/** I livelli (di cerchi, linee, riempimenti) di un livello della mappa. `requests` è fatto di marker
 * HTML, non di livelli. Le larghezze crescono con lo zoom fino alla misura del token. */
export function layerSpecs(
  id: MapLayerId,
  tokens: MapTokens,
  window: EventWindow,
): LayerSpecification[] {
  const { colors: c, sizes, opacity } = tokens;
  const here = inWindow(window);
  const width = zoomWidth;
  const load = ["get", "load_ratio"];
  // Senza capacità (o a fermata chiusa) il motore non dà un rapporto: `load_ratio` è `null`. Un
  // confronto con `null` è un errore dell'espressione e MapLibre ripiega sul nero, invisibile sul
  // fondo e fuori dalla legenda: chi non ha rapporto ha il colore neutro e il raggio più piccolo.
  const hasLoad = ["==", ["typeof", load], "number"];
  const loadColor = [
    "case",
    ["!", hasLoad],
    c.borderStrong,
    [">", load, 1],
    c.stopOver,
    [">=", load, LOAD_MID],
    c.stopMid,
    c.stopLow,
  ] as unknown as string;
  const line = { "line-cap": "round" as const, "line-join": "round" as const };
  switch (id) {
    case "congestion":
      return [
        {
          id: `${id}-line`,
          type: "line",
          source: SOURCE[id],
          filter: ["all", ["!=", ["get", "closed"], true], ["!=", ["get", "detour"], true], here],
          layout: line,
          paint: {
            "line-color": [
              "match",
              ["get", "vc_class"],
              0,
              c.congestion[0],
              1,
              c.congestion[1],
              2,
              c.congestion[2],
              3,
              c.congestion[3],
              c.congestion[0],
            ] as unknown as string,
            "line-width": width(sizes.roadLine),
            "line-opacity": [
              "case",
              ["boolean", ["feature-state", "hover"], false],
              opacity.congestionHover,
              opacity.congestionRest,
            ] as unknown as number,
          },
        },
      ];
    case "detours":
      return [
        {
          id: `${id}-line`,
          type: "line",
          source: SOURCE[id],
          filter: ["all", ["==", ["get", "detour"], true], here],
          layout: { "line-cap": "butt", "line-join": "round" },
          paint: {
            "line-color": c.detour,
            "line-width": width(DETOUR_LINE_WIDTH),
            "line-dasharray": DETOUR_DASH,
            "line-opacity": opacity.congestionHover,
          },
        },
      ];
    case "closures":
      return [
        {
          id: `${id}-line`,
          type: "line",
          source: SOURCE[id],
          filter: here,
          layout: { "line-cap": "butt", "line-join": "round" },
          paint: {
            "line-color": c.closure,
            "line-width": width(CLOSURE_LINE_WIDTH),
            "line-dasharray": CLOSURE_DASH,
          },
        },
      ];
    case "event_area":
      return [
        {
          id: `${id}-fill`,
          type: "fill",
          source: SOURCE[id],
          filter: here,
          paint: { "fill-color": c.eventArea, "fill-opacity": opacity.eventAreaFill },
        },
        {
          id: `${id}-line`,
          type: "line",
          source: SOURCE[id],
          filter: here,
          paint: { "line-color": c.eventArea, "line-width": sizes.outline },
        },
      ];
    case "sections":
      return [
        {
          id: `${id}-line`,
          type: "line",
          source: SOURCE[id],
          filter: here,
          layout: line,
          paint: { "line-color": loadColor, "line-width": width(sizes.roadLine) },
        },
      ];
    case "stops":
      return [
        {
          id: `${id}-circle`,
          type: "circle",
          source: SOURCE[id],
          filter: ["all", ["!=", ["get", "closed"], true], here],
          minzoom: STOP_MIN_ZOOM,
          paint: {
            "circle-color": loadColor,
            "circle-radius": [
              "case",
              ["!", hasLoad],
              STOP_RADIUS,
              [">", load, 1],
              STOP_RADIUS_OVER,
              [">=", load, LOAD_MID],
              STOP_RADIUS_MID,
              STOP_RADIUS,
            ] as unknown as number,
            "circle-stroke-color": c.bg,
            "circle-stroke-width": sizes.outline,
          },
        },
      ];
    case "intersections":
      return [
        {
          id: `${id}-circle`,
          type: "circle",
          source: SOURCE[id],
          filter: here,
          paint: {
            "circle-color": c.congestion[2],
            "circle-radius": sizes.node / 2,
            "circle-stroke-color": c.bg,
            "circle-stroke-width": sizes.outline,
          },
        },
      ];
    case "requests":
      return [];
  }
}

/** Gli id dei livelli cliccabili (per i popup) di un livello della mappa. */
export function interactiveIds(id: MapLayerId, tokens: MapTokens): string[] {
  return layerSpecs(id, tokens, "departure")
    .filter((spec) => spec.type !== "fill")
    .map((spec) => spec.id);
}

export type Bounds = [[number, number], [number, number]];

function extend(bounds: Bounds | undefined, lon: number, lat: number): Bounds {
  if (!bounds)
    return [
      [lon, lat],
      [lon, lat],
    ];
  return [
    [Math.min(bounds[0][0], lon), Math.min(bounds[0][1], lat)],
    [Math.max(bounds[1][0], lon), Math.max(bounds[1][1], lat)],
  ];
}

function walk(coordinates: unknown, visit: (lon: number, lat: number) => void): void {
  if (!Array.isArray(coordinates)) return;
  if (typeof coordinates[0] === "number" && typeof coordinates[1] === "number") {
    visit(coordinates[0], coordinates[1]);
    return;
  }
  for (const item of coordinates) walk(item, visit);
}

/** Il punto a metà di una linea, misurata lungo il suo percorso (non la media degli estremi: una
 * curva ha il centro sulla curva). Le lunghezze sono in metri approssimati (la longitudine pesa il
 * coseno della latitudine): a scala di città basta. `undefined` per meno di due punti. */
export function lineCenter(
  coordinates: readonly (readonly number[])[],
): [number, number] | undefined {
  const points = coordinates.filter((p) => typeof p[0] === "number" && typeof p[1] === "number");
  if (points.length < 2) return undefined;
  const scale = Math.cos((((points[0] as readonly number[])[1] as number) * Math.PI) / 180);
  const length = (a: readonly number[], b: readonly number[]) =>
    Math.hypot(((b[0] as number) - (a[0] as number)) * scale, (b[1] as number) - (a[1] as number));
  let total = 0;
  for (let i = 1; i < points.length; i++)
    total += length(points[i - 1] as readonly number[], points[i] as readonly number[]);
  let left = total / 2;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1] as readonly number[];
    const b = points[i] as readonly number[];
    const step = length(a, b);
    if (left <= step) {
      const t = step === 0 ? 0 : left / step;
      return [
        (a[0] as number) + ((b[0] as number) - (a[0] as number)) * t,
        (a[1] as number) + ((b[1] as number) - (a[1] as number)) * t,
      ];
    }
    left -= step;
  }
  return [points.at(-1)?.[0] as number, points.at(-1)?.[1] as number];
}

export interface ClosureSymbol {
  id: string;
  center: [number, number];
  /** Le proprietà della prima feature che ha dato il simbolo (per il popup). */
  properties: Record<string, unknown>;
}

/** Due centri che coincidono entro 1e-6° (circa 0,1 m) sono lo stesso posto. */
const CENTER_KEY_SCALE = 1e6;

/** I simboli di divieto delle chiusure della finestra: uno per posto, al centro della linea. Due sensi di
 * marcia dello stesso tratto hanno la stessa linea (una chiusura chiude entrambi): un solo simbolo. */
export function closureSymbols(
  collection: FeatureCollection | undefined,
  window: EventWindow,
): ClosureSymbol[] {
  const symbols = new Map<string, ClosureSymbol>();
  for (const feature of collection?.features ?? []) {
    const properties = (feature.properties ?? {}) as Record<string, unknown>;
    if (properties.window !== undefined && properties.window !== window) continue;
    const geometry = feature.geometry as { type?: string; coordinates?: unknown } | null;
    if (geometry?.type !== "LineString" || !Array.isArray(geometry.coordinates)) continue;
    const center = lineCenter(geometry.coordinates as number[][]);
    if (!center) continue;
    const key = `${Math.round(center[0] * CENTER_KEY_SCALE)},${Math.round(center[1] * CENTER_KEY_SCALE)}`;
    if (!symbols.has(key)) symbols.set(key, { id: String(feature.id ?? key), center, properties });
  }
  return [...symbols.values()];
}

/** Il rettangolo [[ovest, sud], [est, nord]] che contiene le geometrie di una raccolta; `undefined`
 * se è vuota. */
export function boundsOf(collection: FeatureCollection | undefined): Bounds | undefined {
  let bounds: Bounds | undefined;
  for (const feature of collection?.features ?? []) {
    walk((feature.geometry as { coordinates?: unknown } | null)?.coordinates, (lon, lat) => {
      bounds = extend(bounds, lon, lat);
    });
  }
  return bounds;
}
