import type { Event, EventInput, Zone } from "@/api/types";
import {
  RESOURCE_FIELDS,
  WINDOWS,
  paths,
  type FieldProblem,
  type ResourceField,
  type WindowId,
} from "@/features/events/paths";
import { strings } from "@/i18n/it";

type Closure = NonNullable<EventInput["closures"]>[number];
type Disruption = NonNullable<EventInput["transit_disruptions"]>[number];

/** I tipi di zona a cui l'Evento può dare una ripartizione modale propria (01 2). */
export const ZONE_TYPES: readonly Zone["type"][] = [
  "road_gate",
  "metro_gate",
  "arrival_hub",
  "near",
  "far",
];

/** Il raggio dell'area evento che propone il modello (`EventInput.area_radius_m`, 06 3): un test lo
 * confronta con l'OpenAPI. Il form non inventa altri valori di partenza. */
export const DEFAULT_RADIUS_M = 400;

export interface TimeWindowDraft {
  start: string;
  end: string;
  peak: string;
}

export interface ResourcesDraft {
  window: WindowId;
  values: Record<ResourceField, string>;
}

export interface ModalSplitDraft {
  car: string;
  transit: string;
  walk: string;
}

export interface RealMeasureDraft {
  label: string;
  measure_type: string;
  target: string;
  source_ref: string;
}

/** L'Evento come lo scrive il form: i campi che si digitano sono **testo** (un campo può essere vuoto
 * o a metà), quelli che si scelgono sulla mappa sono già dati dell'API. `draftToInput` lo
 * converte in `EventInput`; le regole di validità le applica l'API (un solo posto), il form controlla
 * solo che ogni campo sia compilato e si legga come numero. */
export interface EventDraft {
  id: string;
  name: string;
  date: string;
  description: string;
  centerLat: string;
  centerLon: string;
  centerLabel: string;
  radius: string;
  arrival: TimeWindowDraft;
  departure: TimeWindowDraft;
  attendance: { low: string; mid: string; high: string; source: string };
  /** Traffico di fondo in % della capacità, per finestra. */
  background: Record<WindowId, string>;
  closures: Closure[];
  disruptions: Disruption[];
  resources: ResourcesDraft[];
  carOccupancy: string;
  /** Per tipo di zona; tutti e tre i campi vuoti = si usano i valori predefiniti del modello. */
  modalSplit: Record<string, ModalSplitDraft>;
  realMeasures: RealMeasureDraft[];
  sources: string[];
  /** Non si modificano da qui: si conservano come sono (zone e destinazioni auto proprie). */
  zonesOverride: EventInput["zones_override"];
  carDestinations: EventInput["car_destinations"];
}

// --- numeri e orari come testo ------------------------------------------------------------------

const grouping = new Intl.NumberFormat("it-IT", {
  useGrouping: "always",
  maximumFractionDigits: 0,
});

/** Un intero come lo scrive chi lo legge: `150.000`. */
export const integerText = (value: number): string => grouping.format(value);

/** Un decimale con la virgola, senza il rumore dei calcoli in virgola mobile (0,4 × 100). */
export const decimalText = (value: number): string =>
  String(Number(value.toPrecision(12))).replace(".", ",");

/** `150.000`, `150000` → 150000; altro → `undefined` (anche `1.5`: il punto è solo delle migliaia). */
export function parseInteger(text: string): number | undefined {
  const t = text.trim();
  if (/^\d+$/.test(t)) return Number(t);
  if (/^\d{1,3}(\.\d{3})+$/.test(t)) return Number(t.replace(/\./g, ""));
  return undefined;
}

/** `2,2` o `2.2` → 2,2; altro → `undefined`. */
export function parseDecimal(text: string): number | undefined {
  const t = text.trim();
  return /^\d+([.,]\d+)?$/.test(t) ? Number(t.replace(",", ".")) : undefined;
}

/** Una coordinata (può essere negativa): `40.832`, `40,832`. */
export function parseCoordinate(text: string): number | undefined {
  const t = text.trim();
  return /^-?\d+([.,]\d+)?$/.test(t) ? Number(t.replace(",", ".")) : undefined;
}

const timeText = (value: string): string => value.slice(0, 5);

/** `18:30`, `9:05` → `18:30`, `09:05`; altro → `undefined`. Gli orari si scrivono come testo (il
 * selettore del browser cambia aspetto da una lingua all'altra e tronca i valori). */
export function parseTime(text: string): string | undefined {
  const match = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec(text.trim());
  return match ? `${(match[1] as string).padStart(2, "0")}:${match[2]}` : undefined;
}

const windowDraft = (window: EventInput["arrival"]): TimeWindowDraft => ({
  start: timeText(window.start),
  end: timeText(window.end),
  peak: timeText(window.peak),
});

const emptyWindow = (): TimeWindowDraft => ({ start: "", end: "", peak: "" });
const emptySplit = (): ModalSplitDraft => ({ car: "", transit: "", walk: "" });

function emptyResources(window: WindowId): ResourcesDraft {
  return {
    window,
    values: Object.fromEntries(RESOURCE_FIELDS.map((field) => [field, ""])) as Record<
      ResourceField,
      string
    >,
  };
}

/** Un Evento nuovo: vuoto, tranne il raggio che propone il modello. Nessun altro numero inventato. */
export function emptyDraft(): EventDraft {
  return {
    id: "",
    name: "",
    date: "",
    description: "",
    centerLat: "",
    centerLon: "",
    centerLabel: "",
    radius: String(DEFAULT_RADIUS_M),
    arrival: emptyWindow(),
    departure: emptyWindow(),
    attendance: { low: "", mid: "", high: "", source: "" },
    background: { arrival: "", departure: "" },
    closures: [],
    disruptions: [],
    resources: WINDOWS.map(emptyResources),
    carOccupancy: "",
    modalSplit: Object.fromEntries(ZONE_TYPES.map((type) => [type, emptySplit()])),
    realMeasures: [],
    sources: [],
    zonesOverride: null,
    carDestinations: null,
  };
}

export function draftFromEvent(event: Event | EventInput): EventDraft {
  const override = event.modal_split_override ?? {};
  return {
    id: event.id,
    name: event.name,
    date: event.date,
    description: event.description ?? "",
    centerLat: String(event.area_center.lat),
    centerLon: String(event.area_center.lon),
    centerLabel: event.area_center.label ?? "",
    radius: String(event.area_radius_m),
    arrival: windowDraft(event.arrival),
    departure: windowDraft(event.departure),
    attendance: {
      low: integerText(event.attendance.low),
      mid: integerText(event.attendance.mid),
      high: integerText(event.attendance.high),
      source: event.attendance.source_ref ?? "",
    },
    background: {
      arrival: decimalText(event.background.arrival_peak_share * 100),
      departure: decimalText(event.background.departure_peak_share * 100),
    },
    closures: structuredClone(event.closures ?? []),
    disruptions: structuredClone(event.transit_disruptions ?? []),
    resources: event.resources.map((item) => ({
      window: item.window,
      values: Object.fromEntries(
        RESOURCE_FIELDS.map((field) => [field, String(item[field])]),
      ) as Record<ResourceField, string>,
    })),
    carOccupancy: event.car_occupancy == null ? "" : decimalText(event.car_occupancy),
    modalSplit: Object.fromEntries(
      ZONE_TYPES.map((type) => {
        const split = override[type];
        return [
          type,
          split
            ? {
              car: decimalText(split.car_pct),
              transit: decimalText(split.transit_pct),
              walk: decimalText(split.walk_pct),
            }
            : emptySplit(),
        ];
      }),
    ),
    realMeasures: (event.real_measures ?? []).map((measure) => ({
      ...measure,
    })),
    sources: [...(event.sources ?? [])],
    zonesOverride: structuredClone(event.zones_override ?? null),
    carDestinations: structuredClone(event.car_destinations ?? null),
  };
}

/** Il form è stato modificato rispetto a com'era (stessi dati = non modificato). */
export function sameDraft(a: EventDraft, b: EventDraft): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

// --- dalla bozza all'API ------------------------------------------------------------------------

export type DraftResult = { ok: true; input: EventInput } | { ok: false; problems: FieldProblem[] };

/** Il corpo di POST/PUT, o l'elenco dei campi non compilati o non leggibili. Non applica le regole
 * dell'Evento (picco nella finestra, livelli in ordine, quote che sommano a 100…): sono dell'API,
 * che le restituisce per campo. */
export function draftToInput(draft: EventDraft): DraftResult {
  const copy = strings.events.problems;
  const problems: FieldProblem[] = [];
  const need = (path: string, text: string): string => {
    if (text.trim() === "") problems.push({ path, message: copy.required });
    return text;
  };
  const number = (
    path: string,
    text: string,
    parse: (text: string) => number | undefined,
    message: string,
  ): number => {
    if (text.trim() === "") {
      problems.push({ path, message: copy.required });
      return 0;
    }
    const value = parse(text);
    if (value === undefined) {
      problems.push({ path, message });
      return 0;
    }
    return value;
  };
  const integer = (path: string, text: string) => number(path, text, parseInteger, copy.integer);
  const decimal = (path: string, text: string) => number(path, text, parseDecimal, copy.decimal);
  const coordinate = (path: string, text: string) =>
    number(path, text, parseCoordinate, copy.decimal);
  const time = (window: WindowId, field: "start" | "end" | "peak") => {
    const path = paths.window(window, field);
    const text = need(path, draft[window][field]);
    const parsed = parseTime(text);
    if (text.trim() !== "" && parsed === undefined) problems.push({ path, message: copy.time });
    return `${parsed ?? "00:00"}:00`; // i secondi: come li scrive l'API
  };

  const id = need(paths.id, draft.id);
  const name = need(paths.name, draft.name);
  const date = need(paths.date, draft.date);
  const lat = coordinate(paths.centerLat, draft.centerLat);
  const lon = coordinate(paths.centerLon, draft.centerLon);
  const radius = integer(paths.radius, draft.radius);
  const arrival = {
    start: time("arrival", "start"),
    end: time("arrival", "end"),
    peak: time("arrival", "peak"),
  };
  const departure = {
    start: time("departure", "start"),
    end: time("departure", "end"),
    peak: time("departure", "peak"),
  };
  const attendance = {
    low: integer(paths.attendance("low"), draft.attendance.low),
    mid: integer(paths.attendance("mid"), draft.attendance.mid),
    high: integer(paths.attendance("high"), draft.attendance.high),
    source_ref: draft.attendance.source.trim() === "" ? null : draft.attendance.source,
  };
  const background = {
    arrival_peak_share: decimal(paths.background("arrival"), draft.background.arrival) / 100,
    departure_peak_share: decimal(paths.background("departure"), draft.background.departure) / 100,
  };

  draft.closures.forEach((item, index) => need(paths.closure(index, "label"), item.label));
  draft.disruptions.forEach((item, index) => need(paths.disruption(index, "label"), item.label));
  const resources = draft.resources.map((item, index) => ({
    window: item.window,
    ...(Object.fromEntries(
      RESOURCE_FIELDS.map((field) => [
        field,
        integer(paths.resource(index, field), item.values[field]),
      ]),
    ) as Record<ResourceField, number>),
  }));
  const carOccupancy =
    draft.carOccupancy.trim() === "" ? null : decimal(paths.carOccupancy, draft.carOccupancy);

  const split: Record<string, { car_pct: number; transit_pct: number; walk_pct: number }> = {};
  for (const type of ZONE_TYPES) {
    const row = draft.modalSplit[type] ?? emptySplit();
    if (row.car.trim() === "" && row.transit.trim() === "" && row.walk.trim() === "") continue;
    split[type] = {
      car_pct: decimal(paths.modalSplit(type, "car"), row.car),
      transit_pct: decimal(paths.modalSplit(type, "transit"), row.transit),
      walk_pct: decimal(paths.modalSplit(type, "walk"), row.walk),
    };
  }

  const realMeasures = draft.realMeasures.map((item, index) => ({
    label: need(paths.realMeasure(index, "label"), item.label),
    measure_type: need(paths.realMeasure(index, "measure_type"), item.measure_type),
    target: need(paths.realMeasure(index, "target"), item.target),
    source_ref: need(paths.realMeasure(index, "source_ref"), item.source_ref),
  }));

  if (problems.length > 0) return { ok: false, problems };
  return {
    ok: true,
    input: {
      id,
      name,
      date,
      description: draft.description.trim() === "" ? null : draft.description,
      area_center: {
        lat,
        lon,
        label: draft.centerLabel.trim() === "" ? null : draft.centerLabel,
      },
      area_radius_m: radius,
      arrival,
      departure,
      attendance,
      closures: draft.closures,
      transit_disruptions: draft.disruptions,
      background,
      resources,
      car_destinations: draft.carDestinations ?? null,
      zones_override: draft.zonesOverride ?? null,
      modal_split_override: Object.keys(split).length > 0 ? split : null,
      car_occupancy: carOccupancy,
      real_measures: realMeasures,
      sources: draft.sources.filter((source) => source.trim() !== ""),
    },
  };
}

// --- scelte sulla mappa -------------------------------------------------------------------------

/** Il centro dell'area evento scelto con un clic: coordinate a 5 decimali (~1 m); l'etichetta del
 * luogo, che era del centro di prima, si svuota. */
export function withCenter(draft: EventDraft, lat: number, lon: number): EventDraft {
  return { ...draft, centerLat: lat.toFixed(5), centerLon: lon.toFixed(5), centerLabel: "" };
}

export interface EdgeRef {
  edgeKey: string;
  /** L'altro senso di marcia della stessa strada, se c'è: si chiude e si riapre insieme. */
  reverseKey: string | null;
  /** Il nome della strada (OSM), se c'è. */
  name: string;
}

/** Le chiavi degli archi chiusi dall'Evento. */
export const closedEdgeKeys = (draft: EventDraft): Set<string> =>
  new Set(draft.closures.flatMap((closure) => closure.edge_keys ?? []));

/** I due sensi di una strada (o l'unico, se è a senso unico). */
export const edgeKeysOf = (edge: EdgeRef): string[] =>
  edge.reverseKey === null ? [edge.edgeKey] : [edge.edgeKey, edge.reverseKey];

/** Un clic su una strada: se è chiusa (anche in un solo senso) la riapre in entrambi i sensi,
 * altrimenti la chiude in entrambi. Le strade con lo stesso nome stanno in una sola chiusura; una
 * chiusura senza più archi sparisce (non resta con i soli nomi, che farebbero chiudere tutta la
 * strada al risolutore). */
export function toggleEdge(draft: EventDraft, edge: EdgeRef): EventDraft {
  const keys = edgeKeysOf(edge);
  const closed = closedEdgeKeys(draft);
  if (keys.some((key) => closed.has(key))) {
    // anche se due chiusure la contengono: una strada riaperta non resta chiusa da un'altra
    const closures = draft.closures.flatMap((closure) => {
      const before = closure.edge_keys ?? [];
      const edge_keys = before.filter((key) => !keys.includes(key));
      if (edge_keys.length === before.length) return [closure];
      return edge_keys.length > 0 ? [{ ...closure, edge_keys }] : [];
    });
    return { ...draft, closures };
  }
  const label = edge.name.trim() === "" ? edge.edgeKey : edge.name;
  const same = draft.closures.findIndex((closure) => closure.label === label);
  if (same >= 0) {
    return {
      ...draft,
      closures: draft.closures.map((closure, index) =>
        index === same
          ? { ...closure, edge_keys: [...(closure.edge_keys ?? []), ...keys] }
          : closure,
      ),
    };
  }
  const added: Closure = {
    label,
    street_names: [],
    bbox: null,
    edge_keys: keys,
    mode: "closed",
    capacity_factor: 0,
    source_ref: null,
  };
  return { ...draft, closures: [...draft.closures, added] };
}

export interface StopRef {
  stopId: string;
  name: string;
}

/** Gli id delle fermate interrotte dall'Evento. */
export const disruptedStopIds = (draft: EventDraft): Set<string> =>
  new Set(draft.disruptions.flatMap((item) => item.stop_ids ?? []));

/** Un clic su una fermata: se è interrotta la riapre, altrimenti la interrompe. Le banchine con lo
 * stesso nome (Arco Mirelli: 6236 e 6237) stanno in una sola interruzione, che parte da «entrambe
 * le finestre»; una interruzione senza più fermate sparisce. */
export function toggleStop(draft: EventDraft, stop: StopRef): EventDraft {
  if (disruptedStopIds(draft).has(stop.stopId)) {
    const disruptions = draft.disruptions.flatMap((item) => {
      const stop_ids = (item.stop_ids ?? []).filter((id) => id !== stop.stopId);
      if (stop_ids.length === (item.stop_ids ?? []).length) return [item];
      return stop_ids.length > 0 ? [{ ...item, stop_ids }] : [];
    });
    return { ...draft, disruptions };
  }
  const same = draft.disruptions.findIndex((item) => item.stop_name === stop.name);
  if (same >= 0) {
    return {
      ...draft,
      disruptions: draft.disruptions.map((item, index) =>
        index === same ? { ...item, stop_ids: [...(item.stop_ids ?? []), stop.stopId] } : item,
      ),
    };
  }
  const added: Disruption = {
    label: strings.events.disruptionLabel(stop.name),
    stop_name: stop.name,
    stop_ids: [stop.stopId],
    window: "both",
    source_ref: null,
  };
  return { ...draft, disruptions: [...draft.disruptions, added] };
}

/** Un nome leggibile per l'identificativo di un Evento nuovo: minuscole, cifre e `_`, iniziale
 * lettera (come vuole l'API, `Slug`); se esiste già se ne cerca uno libero (`_2`, `_3`…). */
export function slugFromName(name: string, taken: ReadonlySet<string>): string {
  const base = name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (base === "") return "";
  const slug = /^[a-z]/.test(base) ? base : `evento_${base}`;
  if (!taken.has(slug)) return slug;
  for (let n = 2; ; n++) if (!taken.has(`${slug}_${n}`)) return `${slug}_${n}`;
}

// --- i campi che il form mostra -----------------------------------------------------------------

/** I percorsi dei campi che il form mostra per questa bozza. Un errore dell'API su un percorso che non
 * è qui (`closures.0.edge_keys`, un errore sull'intero oggetto…) non ha un campo accanto: si legge
 * nel riepilogo in cima al form. */
export function renderedPaths(draft: EventDraft): Set<string> {
  const out = new Set<string>([
    paths.id,
    paths.name,
    paths.date,
    paths.description,
    paths.centerLat,
    paths.centerLon,
    paths.centerLabel,
    paths.radius,
    paths.carOccupancy,
  ]);
  for (const window of WINDOWS) {
    for (const field of ["start", "end", "peak"] as const) out.add(paths.window(window, field));
    out.add(paths.background(window));
  }
  for (const field of ["low", "mid", "high", "source_ref"] as const)
    out.add(paths.attendance(field));
  draft.closures.forEach((_, i) => {
    out.add(paths.closure(i, "label"));
    out.add(paths.closure(i, "source_ref"));
  });
  draft.disruptions.forEach((_, i) => {
    for (const field of ["label", "window", "source_ref"] as const)
      out.add(paths.disruption(i, field));
  });
  draft.resources.forEach((_, i) => {
    for (const field of RESOURCE_FIELDS) out.add(paths.resource(i, field));
  });
  for (const type of ZONE_TYPES) {
    for (const field of ["car", "transit", "walk"] as const) out.add(paths.modalSplit(type, field));
  }
  draft.realMeasures.forEach((_, i) => {
    for (const field of ["label", "measure_type", "target", "source_ref"] as const) {
      out.add(paths.realMeasure(i, field));
    }
  });
  draft.sources.forEach((_, i) => out.add(paths.source(i)));
  return out;
}
