import type { Feature } from "@/api/types";
import type { EdgeRef, StopRef } from "@/features/events/draft";
import type { MapMode } from "@/features/events/EventEditor";
import { EDIT_EDGES_LAYER, EDIT_STOPS_LAYER } from "@/features/map/layers";

/** Che cosa fa il clic sulla mappa quando si sta scegliendo (07 4). */
export interface PickHandlers {
  onPickCenter: (lat: number, lon: number) => void;
  onPickEdge: (edge: EdgeRef, geometry: Feature["geometry"]) => void;
  onPickStop: (stop: StopRef) => void;
}

/** Quello che serve di una feature sotto il clic. */
export interface ClickedFeature {
  layerId: string;
  properties: Record<string, unknown> | null;
  geometry: Feature["geometry"];
}

const text = (value: unknown): string => (typeof value === "string" ? value : "");
/** Il testo se c'è, altrimenti `null` (`reverse_key` è `null` per i sensi unici). */
const textOrNull = (value: unknown): string | null => text(value) || null;

/** Il clic va a chi sta scegliendo: il centro dell'area (qualunque punto), una strada (solo se si
 * clicca una strada), una fermata (solo se si clicca una fermata). Ritorna `true` se il clic è
 * stato usato; in modo `idle` non lo usa mai (si aprono i popup). */
export function routeEditorClick(
  mode: MapMode,
  at: { lng: number; lat: number },
  features: readonly ClickedFeature[],
  handlers: PickHandlers,
): boolean {
  switch (mode) {
    case "idle":
      return false;
    case "area":
      handlers.onPickCenter(at.lat, at.lng);
      return true;
    case "closures": {
      const hit = features.find(
        (f) => f.layerId === EDIT_EDGES_LAYER && text(f.properties?.edge_key),
      );
      if (hit) {
        handlers.onPickEdge(
          {
            edgeKey: text(hit.properties?.edge_key),
            reverseKey: textOrNull(hit.properties?.reverse_key),
            name: text(hit.properties?.name),
          },
          hit.geometry,
        );
      }
      return true;
    }
    case "stops": {
      const hit = features.find(
        (f) => f.layerId === EDIT_STOPS_LAYER && text(f.properties?.stop_id),
      );
      if (hit) {
        handlers.onPickStop({
          stopId: text(hit.properties?.stop_id),
          name: text(hit.properties?.name),
        });
      }
      return true;
    }
  }
}
