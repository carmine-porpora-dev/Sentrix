import type { Measured } from "@/api/types";

/** L'unità del backend → come si scrive (design: «ore-veicolo», «persone»). Vuoto = nessuna unità. */
const DISPLAY_UNIT: Record<string, string> = {
  "veic·h": "ore-veicolo",
  pax: "persone",
  n: "",
  rapporto: "%",
  testo: "",
};

/** Cifre decimali per unità (il valore non si arrotonda mai prima: solo nel testo). */
const DECIMALS: Record<string, number> = {
  "veic·h": 0,
  pax: 0,
  n: 0,
  min: 1,
  km: 1,
  rapporto: 0, // mostrato in % (128 %)
};
const DEFAULT_DECIMALS = 1;

/** I rapporti (carico = passeggeri/capacità) si mostrano in percentuale: ×100. */
const SCALE: Record<string, number> = { rapporto: 100 };

const MINUS = "−"; // U+2212, non il trattino

function formatter(decimals: number): Intl.NumberFormat {
  // `always`: «1.240» anche a quattro cifre, come il design (la regola di it-IT lo toglierebbe)
  return new Intl.NumberFormat("it-IT", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    useGrouping: "always",
  });
}

export function decimalsFor(unit: string): number {
  return DECIMALS[unit] ?? DEFAULT_DECIMALS;
}

/** Il valore nella scala di visualizzazione (un rapporto in percentuale). */
export function scaled(value: number, unit: string): number {
  return value * (SCALE[unit] ?? 1);
}

/** «1.240», «0,80», «128»: il numero con le cifre dell'unità, senza segno aggiunto e senza unità. */
export function formatNumber(value: number, unit: string): string {
  const text = formatter(decimalsFor(unit)).format(scaled(value, unit));
  // un valore piccolo che si arrotonda a zero non deve mostrare «-0»
  return text.replace(/^-(?=0(?:,0+)?$)/, "");
}

/** L'unità come si legge («ore-veicolo», «%», «min»); `""` se non ce n'è. */
export function displayUnit(unit: string): string {
  return unit in DISPLAY_UNIT ? (DISPLAY_UNIT[unit] as string) : unit;
}

/** Un'unità abbastanza corta da stare accanto a una variazione («min», «km», «pp»): «ore-veicolo» no. */
export function isShortUnit(unit: string): boolean {
  return displayUnit(unit).length <= 4;
}

export interface Shown {
  /** «1.240», o il testo di una metrica qualitativa. */
  text: string;
  unit: string;
}

/** Valore e unità di un `Measured` come si mostrano. Una metrica di testo (`itinerary_used`) resta com'è. */
export function formatMeasured(measured: Pick<Measured, "value" | "unit">): Shown {
  if (typeof measured.value === "string") return { text: measured.value, unit: "" };
  return { text: formatNumber(measured.value, measured.unit), unit: displayUnit(measured.unit) };
}

export interface ShownDelta extends Shown {
  /** `up`, `down` o `none` (la differenza si arrotonda a zero: nessuna freccia). */
  direction: "up" | "down" | "none";
}

/** Una differenza: sempre con il segno («+5,2», «−330»); un rapporto è in punti percentuali («pp»). */
export function formatDelta(delta: Pick<Measured, "value" | "unit">): ShownDelta {
  if (typeof delta.value === "string") return { text: delta.value, unit: "", direction: "none" };
  const unit = delta.unit === "rapporto" ? "pp" : displayUnit(delta.unit);
  const magnitude = formatNumber(Math.abs(delta.value), delta.unit);
  const isZero = /^0(?:,0+)?$/.test(magnitude);
  if (isZero) return { text: magnitude, unit, direction: "none" };
  const up = delta.value > 0;
  return { text: `${up ? "+" : MINUS}${magnitude}`, unit, direction: up ? "up" : "down" };
}

export type Better = "lower" | "higher" | "none";
export type Tone = "better" | "worse" | "neutral";

/** Il colore di una variazione: per tempi, ore-veicolo e carichi meno è meglio. */
export function deltaTone(direction: ShownDelta["direction"], better: Better): Tone {
  if (direction === "none" || better === "none") return "neutral";
  const improved = (direction === "down") === (better === "lower");
  return improved ? "better" : "worse";
}

const DATE_TIME = new Intl.DateTimeFormat("it-IT", {
  timeZone: "Europe/Rome",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** «gg/mm/aaaa hh:mm» nel fuso di Roma (l'istante di un dato). */
export function formatAsOf(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return DATE_TIME.format(date).replace(", ", " ");
}

const CLOCK = new Intl.DateTimeFormat("it-IT", {
  timeZone: "Europe/Rome",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** «10:00» nel fuso di Roma (l'ora di una riga del registro). */
export function formatClock(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : CLOCK.format(date);
}
