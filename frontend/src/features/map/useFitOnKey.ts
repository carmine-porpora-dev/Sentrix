import { useEffect, useRef, type RefObject } from "react";
import type { Bounds } from "@/features/map/layers";

/** Quello che serve della mappa (`MapRef` di react-map-gl): portare la vista su un rettangolo. */
export interface Fittable {
  fitBounds: (
    bounds: Bounds,
    options: { padding: number; maxZoom: number; duration: number },
  ) => void;
}

/** Porta la mappa su `bounds` ogni volta che cambia `key` (il run) e solo allora: i dati di una
 * nuova iterazione dello stesso run non la spostano sotto le mani di chi la sta guardando. Aspetta
 * che la mappa sia `ready` (react-map-gl la crea dopo il primo montaggio: prima il riferimento è
 * vuoto) e che ci sia un rettangolo (la chiave non conta finché non c'è dove andare). */
export function useFitOnKey(
  map: RefObject<Fittable | null>,
  bounds: Bounds | undefined,
  key: string | undefined,
  options: { padding: number; maxZoom: number; duration: number },
  ready: boolean,
): void {
  const latest = useRef({ bounds, options });
  useEffect(() => {
    latest.current = { bounds, options };
  });
  useEffect(() => {
    const { bounds: target, options: fit } = latest.current;
    if (ready && key !== undefined && target) map.current?.fitBounds(target, fit);
  }, [key, ready, map]);
}
