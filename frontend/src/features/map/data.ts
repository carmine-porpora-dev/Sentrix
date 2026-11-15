import { useQueries } from "@tanstack/react-query";
import { useApi } from "@/api/provider";
import type { FeatureCollection, LayerName } from "@/api/types";

export const API_LAYERS: readonly LayerName[] = [
  "edges_vc",
  "closures",
  "critical_intersections",
  "stops",
  "sections",
  "event_area",
  "requests",
];

export type LayerData = Partial<Record<LayerName, FeatureCollection>>;

/** I sette livelli di un'iterazione di un run (`GET /api/runs/{id}/layers/{layer}?iteration=n`).
 * Un'iterazione è immutabile: si leggono una volta. Quelli che non ci sono ancora restano assenti. */
export function useRunLayers(runId: string | undefined, iteration: number | undefined): LayerData {
  const api = useApi();
  const enabled = runId !== undefined && iteration !== undefined;
  const results = useQueries({
    queries: API_LAYERS.map((layer) => ({
      queryKey: ["layer", runId, iteration, layer],
      queryFn: () => api.runLayer(runId as string, layer, iteration as number),
      enabled,
      staleTime: Infinity,
      retry: false,
    })),
  });
  const data: LayerData = {};
  API_LAYERS.forEach((layer, index) => {
    const found = results[index]?.data;
    if (enabled && found) data[layer] = found;
  });
  return data;
}
