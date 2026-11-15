import type { Feature, FeatureCollection } from "@/api/types";
import {
  CIRCLE_STEPS,
  EDIT_BBOX_GRID_DEG,
  EDIT_BBOX_MARGIN_DEG,
  METERS_PER_DEGREE,
} from "@/features/map/config";
import type { Bounds } from "@/features/map/layers";
import { parseCoordinate, parseInteger, type EventDraft } from "@/features/events/draft";

const collection = (features: Feature[]): FeatureCollection => ({
  type: "FeatureCollection",
  features,
});

/** Il cerchio dell'area evento come poligono GeoJSON. Solo da disegnare: la mappa lo mostra mentre
 * si sceglie centro e raggio; il perimetro dei calcoli è del backend (layer `event_area`). */
export function circleFeature(lat: number, lon: number, radiusM: number): Feature {
  const dLat = radiusM / METERS_PER_DEGREE;
  const dLon = radiusM / (METERS_PER_DEGREE * Math.cos((lat * Math.PI) / 180));
  const ring: number[][] = [];
  for (let step = 0; step <= CIRCLE_STEPS; step++) {
    const angle = (2 * Math.PI * (step % CIRCLE_STEPS)) / CIRCLE_STEPS;
    ring.push([
      Number((lon + dLon * Math.cos(angle)).toFixed(6)),
      Number((lat + dLat * Math.sin(angle)).toFixed(6)),
    ]);
  }
  return {
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [ring] },
    properties: { kind: "draft_area" },
  };
}

/** L'area evento della bozza, se centro e raggio si leggono. */
export function draftArea(draft: EventDraft): FeatureCollection | undefined {
  const lat = parseCoordinate(draft.centerLat);
  const lon = parseCoordinate(draft.centerLon);
  const radius = parseInteger(draft.radius);
  if (lat === undefined || lon === undefined || radius === undefined || radius < 1)
    return undefined;
  return collection([circleFeature(lat, lon, radius)]);
}

/** Le linee delle chiusure della bozza: gli archi che le chiusure nominano, con la geometria che si
 * conosce (l'anteprima del risolutore per l'Evento salvato, le strade della mappa per i clic
 * nuovi). Un arco senza geometria nota non si disegna: compare quando l'Evento si salva. */
export function closureLines(
  closedKeys: ReadonlySet<string>,
  ...sources: (FeatureCollection | undefined)[]
): FeatureCollection {
  const seen = new Set<string>();
  const features: Feature[] = [];
  for (const source of sources) {
    for (const feature of source?.features ?? []) {
      const key = feature.properties?.edge_key;
      const back = feature.properties?.reverse_key;
      if (typeof key !== "string" || seen.has(key)) continue;
      // una strada è chiusa se lo è uno dei suoi due sensi
      if (!closedKeys.has(key) && !(typeof back === "string" && closedKeys.has(back))) continue;
      if (feature.properties?.kind !== undefined && feature.properties.kind !== "closure") continue;
      seen.add(key);
      features.push(feature);
    }
  }
  return collection(features);
}

/** Le fermate interrotte tra quelle note. */
export function disruptedPoints(
  disruptedIds: ReadonlySet<string>,
  stops: FeatureCollection | undefined,
): FeatureCollection {
  return collection(
    (stops?.features ?? []).filter((feature) => {
      const id = feature.properties?.stop_id;
      return typeof id === "string" && disruptedIds.has(id);
    }),
  );
}

// --- il rettangolo da chiedere per strade e fermate ---------------------------------------------

/** `ovest,sud,est,nord` come lo vuole l'API (06 4). */
export const bboxParam = (bounds: Bounds): string =>
  `${bounds[0][0]},${bounds[0][1]},${bounds[1][0]},${bounds[1][1]}`;

// Sulle righe della griglia la divisione in virgola mobile può dare 4079,9999… invece di 4080:
// senza una tolleranza arrotondare un valore già «a griglia» lo farebbe scendere di un passo.
const GRID_EPSILON = 1e-9;
const snapDown = (value: number) =>
  Number((Math.floor(value / EDIT_BBOX_GRID_DEG + GRID_EPSILON) * EDIT_BBOX_GRID_DEG).toFixed(4));
const snapUp = (value: number) =>
  Number((Math.ceil(value / EDIT_BBOX_GRID_DEG - GRID_EPSILON) * EDIT_BBOX_GRID_DEG).toFixed(4));

/** Il rettangolo allargato alla griglia: due viste vicine danno lo stesso. */
export function snapBounds(bounds: Bounds): Bounds {
  return [
    [snapDown(bounds[0][0]), snapDown(bounds[0][1])],
    [snapUp(bounds[1][0]), snapUp(bounds[1][1])],
  ];
}

/** Il rettangolo attorno all'area evento (centro ± raggio ± margine), se si legge. */
export function areaBounds(draft: EventDraft): Bounds | undefined {
  const lat = parseCoordinate(draft.centerLat);
  const lon = parseCoordinate(draft.centerLon);
  if (lat === undefined || lon === undefined) return undefined;
  const dLat = EDIT_BBOX_MARGIN_DEG;
  const dLon = EDIT_BBOX_MARGIN_DEG / Math.cos((lat * Math.PI) / 180);
  return [
    [lon - dLon, lat - dLat],
    [lon + dLon, lat + dLat],
  ];
}
