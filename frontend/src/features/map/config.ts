import type { Bounds } from "@/features/map/layers";

/** Il riquadro della base map (`docs/spec/00-data-sources.md` 2.3: ovest, sud, est, nord): fuori non ci
 * sono tessere, quindi la mappa non esce da qui. */
export const NAPOLI_BOUNDS: Bounds = [
  [14.1, 40.78],
  [14.35, 40.92],
];
export const MAX_ZOOM = 15; // quello della base map
export const FIT_PADDING = 80;
/** «Vista presentazione» (07 5): la mappa inclinata. 60° è il massimo di MapLibre. */
export const PRESENTATION_PITCH = 55;
/** Di quanto sta sopra il punto un popup (px): quello di una feature sul disegno, quello di un marker
 * sopra il marker (52 px di altezza di `MapMarker`: cerchio 44 + punta 8) più un po' di respiro. */
export const POPUP_OFFSET = { feature: 8, marker: 56 } as const;

/** Quanti punti ha il cerchio dell'area evento che si disegna nel form e i metri per grado di latitudine
 * (una sfera: basta per un cerchio di centinaia di metri). Solo geometria da disegnare, nessun numero
 * dell'analisi. */
export const CIRCLE_STEPS = 64;
export const METERS_PER_DEGREE = 111_320;
/** Strade e fermate da cliccare si chiedono per il rettangolo visibile arrotondato a questa griglia
 * (gradi): spostando di poco la mappa non si rifà la richiesta. */
export const EDIT_BBOX_GRID_DEG = 0.01;
/** Margine attorno all'area evento per le strade e le fermate, finché non si conosce la vista. */
export const EDIT_BBOX_MARGIN_DEG = 0.02;
/** Raggio dell'area evento che si sceglie con il cursore (m): solo i limiti del cursore, l'API accetta
 * qualunque raggio ≥ 1. */
export const RADIUS_SLIDER = { min: 100, max: 1500, step: 50 } as const;

/** Lo zoom minimo a cui la mappa va su un punto che l'interfaccia le chiede di mostrare (quello di una
 * strada: sotto il massimo della base map). */
export const FOCUS_ZOOM = 15;
