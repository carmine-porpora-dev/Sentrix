export type WindowId = "arrival" | "departure";
export const WINDOWS: readonly WindowId[] = ["arrival", "departure"];

export const paths = {
  id: "id",
  name: "name",
  date: "date",
  description: "description",
  centerLat: "area_center.lat",
  centerLon: "area_center.lon",
  centerLabel: "area_center.label",
  radius: "area_radius_m",
  window: (window: WindowId, field: "start" | "end" | "peak") => `${window}.${field}`,
  attendance: (field: "low" | "mid" | "high" | "source_ref") => `attendance.${field}`,
  background: (window: WindowId) => `background.${window}_peak_share`,
  closure: (index: number, field: "label" | "source_ref" | "edge_keys") =>
    `closures.${index}.${field}`,
  disruption: (index: number, field: "label" | "window" | "source_ref") =>
    `transit_disruptions.${index}.${field}`,
  resource: (index: number, field: ResourceField) => `resources.${index}.${field}`,
  carOccupancy: "car_occupancy",
  modalSplit: (zoneType: string, field: "car" | "transit" | "walk") =>
    `modal_split_override.${zoneType}.${field}_pct`,
  realMeasure: (index: number, field: "label" | "measure_type" | "target" | "source_ref") =>
    `real_measures.${index}.${field}`,
  source: (index: number) => `sources.${index}`,
} as const;

/** I numeri delle risorse di un dipartimento per finestra (D19), con i nomi dell'API. */
export const RESOURCE_FIELDS = [
  "municipal_police_patrols_total",
  "municipal_police_patrols_committed",
  "traffic_control_signal_changes_max",
  "transport_control_reserve_buses",
  "transport_control_hour_extensions",
] as const;
export type ResourceField = (typeof RESOURCE_FIELDS)[number];

/** Un errore su un campo, dell'API o del form: dove e che cosa. */
export interface FieldProblem {
  path: string;
  message: string;
}

/** Gli errori per campo: percorso → messaggi (più errori sullo stesso campo si leggono insieme). */
export type FieldErrors = ReadonlyMap<string, string>;

export function errorMap(problems: readonly FieldProblem[]): FieldErrors {
  const map = new Map<string, string>();
  for (const { path, message } of problems) {
    const known = map.get(path);
    map.set(path, known === undefined || known === message ? message : `${known}; ${message}`);
  }
  return map;
}
