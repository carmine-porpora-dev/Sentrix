import { useMemo } from "react";
import type { FeatureCollection, LiveFlowResponse, Measured } from "@/api/types";
import { bboxParam } from "@/features/events/geo";
import { useLiveFlow, useLiveNetwork } from "@/features/live/queries";
import { liveEdges, liveMeasures } from "@/features/live/layers";
import { boundsOf, type Bounds } from "@/features/map/layers";
import type { LayerData } from "@/features/map/data";

/** Un po' di margine attorno ai tratti per chiedere le fermate (gradi). */
const STOP_MARGIN_DEG = 0.01;

const retag = (
  collection: FeatureCollection | undefined,
  extra: Record<string, unknown>,
): FeatureCollection | undefined =>
  collection && {
    ...collection,
    features: collection.features.map((f) => ({
      ...f,
      properties: { ...(f.properties ?? {}), ...extra },
    })),
  };

// cinque decimali (~1 m): niente 40.830999999999996 nell'indirizzo, e due viste uguali chiedono lo stesso
const round = (n: number) => Math.round(n * 1e5) / 1e5;

export const bboxOf = (bounds: Bounds | undefined, margin = STOP_MARGIN_DEG): string | undefined =>
  bounds &&
  bboxParam([
    [round(bounds[0][0] - margin), round(bounds[0][1] - margin)],
    [round(bounds[1][0] + margin), round(bounds[1][1] + margin)],
  ]);

export interface LiveMap {
  flow: LiveFlowResponse | undefined;
  data: LayerData;
  bounds: Bounds | undefined;
  measuredFor: (id: string) => Measured | undefined;
}

/** Ciò che la mappa mostra in LIVE: i tratti TomTom (livello di congestione, per classe), le linee e
 * le fermate del TPL senza carico (un carico nullo è il neutro: gli orari sono programmati, non un
 * dato in tempo reale), e le misure con cui il popup dice le velocità. */
export function useLiveMap(live: boolean): LiveMap {
  const flow = useLiveFlow(live).data;
  const edges = useMemo(() => liveEdges(flow), [flow]);
  const bounds = useMemo(() => boundsOf(edges), [edges]);
  const network = useLiveNetwork(live, bboxOf(bounds));
  const data = useMemo<LayerData>(() => {
    const out: LayerData = {};
    if (edges) out.edges_vc = edges;
    const sections = retag(network.lines, { load_ratio: null });
    if (sections) out.sections = sections;
    const stops = retag(network.stops, { load_ratio: null, closed: false });
    if (stops) out.stops = stops;
    return out;
  }, [edges, network.lines, network.stops]);
  const measures = useMemo(() => liveMeasures(flow), [flow]);
  return { flow, data, bounds, measuredFor: (id) => measures.get(id) };
}
