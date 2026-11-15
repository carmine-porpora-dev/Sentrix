import type { Feature, FeatureCollection, LiveFlowResponse, Measured } from "@/api/types";

/** I tratti LIVE come livello di congestione della mappa: le stesse quattro classi (`vc_class`) e gli
 * stessi colori dello scenario, così la legenda è una sola. `live: true` dice al popup che i valori
 * sono velocità e non v/c; gli id delle tre misure di ogni tratto lo mettono in grado di mostrarle
 * con la loro provenienza. Senza `window`: i tratti si vedono sempre. */
export function liveEdges(flow: LiveFlowResponse | undefined): FeatureCollection | undefined {
  if (!flow || flow.segments.length === 0) return undefined;
  const features: Feature[] = flow.segments.map((segment) => ({
    type: "Feature",
    id: segment.id,
    geometry: segment.geometry,
    properties: {
      edge_key: segment.id,
      name: segment.label,
      vc_class: segment.congestion_class,
      closed: false,
      detour: false,
      live: true,
      speed_id: segment.current_speed.id,
      free_flow_id: segment.free_flow_speed.id,
      ratio_id: segment.ratio.id,
    },
  }));
  return { type: "FeatureCollection", features };
}

/** Ogni misura dei tratti (e del riepilogo) per id: la mappa ci cerca i numeri del popup. */
export function liveMeasures(flow: LiveFlowResponse | undefined): ReadonlyMap<string, Measured> {
  const found = new Map<string, Measured>();
  for (const segment of flow?.segments ?? []) {
    for (const measured of [segment.current_speed, segment.free_flow_speed, segment.ratio]) {
      found.set(measured.id, measured);
    }
  }
  for (const measured of flow?.summary ?? []) found.set(measured.id, measured);
  return found;
}

/** Un numero del riepilogo per nome (`mean_speed`, `slowed_count`…). */
export function summaryValue(
  flow: LiveFlowResponse | undefined,
  part: string,
): Measured | undefined {
  return flow?.summary?.find((m) => m.id.endsWith(`.summary.${part}`));
}

/** Il tratto a cui appartiene la misura `speedId` (la velocità attuale del più lento): il nome si
 * legge dalla risposta, non si rifà con il testo del metodo. */
export function segmentOfSpeed(flow: LiveFlowResponse | undefined, speedId: string | undefined) {
  return flow?.segments.find((s) => s.current_speed.id === speedId);
}
