import type { FeatureCollection, PlannedSensor } from "@/api/types";

/** Sensori previsti (spech 11.5): la rete che il prodotto avrà, senza dati. Qui solo dove si
 * disegnano e come si raggruppano; nessun numero, nessuna misura. */
export type SensorType = PlannedSensor["type"];

/** I tipi nell'ordine in cui li elenca il riquadro «Fonti dati» (quello di spech 11.2). */
export const SENSOR_TYPES: readonly SensorType[] = [
  "gps_probe",
  "turnstile",
  "people_counter",
  "ramp_counter",
];

/** Un simbolo sulla mappa: il sensore e il punto in cui lo si disegna. */
export interface SensorMarker {
  /** Unico: un tornello vale per ogni stazione della sua linea. */
  key: string;
  sensor: PlannedSensor;
  lng: number;
  lat: number;
}

/** I vertici di una `LineString` come [lng, lat] (qualunque altra geometria: nessuno). */
function lineVertices(geometry: { [key: string]: unknown } | null): [number, number][] {
  if (geometry?.type !== "LineString" || !Array.isArray(geometry.coordinates)) return [];
  return (geometry.coordinates as unknown[]).flatMap((position) =>
    Array.isArray(position) && typeof position[0] === "number" && typeof position[1] === "number"
      ? [[position[0], position[1]] as [number, number]]
      : [],
  );
}

/** Dove si disegna ogni sensore previsto.
 *
 * - contapersone e sensori di rampa: nel punto del file (`location`);
 * - tornelli: nelle **stazioni** delle linee di `GET /api/transit/lines` della loro `route_class`
 *   (la posizione di una stazione vive in un posto solo, il feed: il file dei sensori non la
 *   ripete). Le linee sono quelle già lette dalla vista LIVE; finché non ci sono, nessun tornello;
 * - sonde GPS: nessun simbolo (coprono la rete, non hanno un posto).
 */
export function sensorMarkers(
  sensors: readonly PlannedSensor[] | undefined,
  lines: FeatureCollection | undefined,
): SensorMarker[] {
  const markers: SensorMarker[] = [];
  for (const sensor of sensors ?? []) {
    if (sensor.type === "turnstile") {
      for (const line of lines?.features ?? []) {
        const properties = line.properties ?? {};
        if (properties.route_class !== sensor.route_class) continue;
        lineVertices(line.geometry).forEach(([lng, lat], index) =>
          markers.push({
            key: `${sensor.id}:${String(properties.route_id ?? "")}:${index}`,
            sensor,
            lng,
            lat,
          }),
        );
      }
    } else if (sensor.location) {
      markers.push({
        key: sensor.id,
        sensor,
        lng: sensor.location.lon,
        lat: sensor.location.lat,
      });
    }
  }
  return markers;
}

/** I tipi presenti nell'elenco, nell'ordine di `SENSOR_TYPES` (uno per riga del riquadro «Fonti dati»). */
export function sensorTypes(sensors: readonly PlannedSensor[] | undefined): SensorType[] {
  const present = new Set((sensors ?? []).map((sensor) => sensor.type));
  return SENSOR_TYPES.filter((type) => present.has(type));
}
