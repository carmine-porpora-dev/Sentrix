import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { sources } from "../test/sources.ts";

// F4-REF — «nessun numero senza MeasuredValue» (principio 2), dal lato del codice: dove si formatta un
// numero e quali testi ne portano uno. L'interfaccia com'è la guarda `features/shell/numbers.test.tsx`.

const FORMAT = "lib/format.ts";

/** Chi importa che cosa da `@/lib/format`: { nome → file che lo importano }. */
function importersOfFormat(): Map<string, string[]> {
  const importers = new Map<string, string[]>();
  for (const { file, code } of sources()) {
    for (const match of code.matchAll(
      /import\s*(?:type\s*)?\{([^}]*)\}\s*from\s*"@\/lib\/format"/g,
    )) {
      for (const part of (match[1] ?? "").split(",")) {
        const name = part.replace(/\btype\b/, "").trim();
        if (name) importers.set(name, [...(importers.get(name) ?? []), file]);
      }
    }
  }
  return importers;
}

describe("i numeri del dominio si formattano in un punto solo (F4-REF)", () => {
  it("formatMeasured, formatDelta e formatNumber li usa solo MeasuredValue", () => {
    const importers = importersOfFormat();
    expect(importers.get("formatMeasured")).toEqual(["components/MeasuredValue.tsx"]);
    expect(importers.get("formatDelta")).toEqual(["components/MeasuredValue.tsx"]);
    // niente altro: né il formato di un numero né la sua scala si chiamano da fuori
    for (const name of ["formatNumber", "scaled", "decimalsFor"]) {
      expect(importers.get(name), name).toBeUndefined();
    }
  });

  it("le altre funzioni di format.ts non scrivono il valore di un Measured: unità, ora, verso", () => {
    const importers = importersOfFormat();
    expect([...importers.keys()].sort()).toEqual(
      [
        "Better",
        "Tone",
        "deltaTone",
        "displayUnit",
        "formatAsOf",
        "formatClock",
        "formatDelta",
        "formatMeasured",
        "isShortUnit",
      ].sort(),
    );
  });

  it("il formato dei numeri della lingua (toLocaleString, Intl, toFixed) sta in poche mani", () => {
    // format.ts: i Measured; draft.ts: i numeri che si digitano nel form; geo.ts: le coordinate
    const allowed = new Set([FORMAT, "features/events/draft.ts", "features/events/geo.ts"]);
    const users = sources()
      .filter(({ code }) =>
        /\.toLocaleString\(|Intl\.NumberFormat|\.toFixed\(|\.toPrecision\(/.test(code),
      )
      .map(({ file }) => file);
    expect(users.filter((file) => !allowed.has(file))).toEqual([]);
    expect(users).toContain(FORMAT);
  });
});

/** Le funzioni di `strings` (it.ts) che prendono un numero: scrivono un conteggio, un numero d'ordine o
 * un valore dell'utente dentro una frase, mai il risultato di un calcolo del motore. */
const NUMERIC_TEXTS: Record<string, string> = {
  iteration: "il numero d'ordine dell'iterazione (3 voci: barra, mappa, confronto)",
  criticalIntersection: "il numero d'ordine dell'incrocio critico",
  arcs: "quanti archi ha scelto chi compila l'Evento",
  capacityReduced: "la capacità ridotta che ha scritto chi compila l'Evento (in %)",
  stops: "quante fermate ha scelto chi compila l'Evento",
  ownZones: "quante zone ha l'Evento (dato dell'Evento)",
  ownDestinations: "quante destinazioni auto ha l'Evento (dato dell'Evento)",
  missing: "quanti campi mancano nel form",
  plan: "quante misure ha il piano",
  replacedBy: "il numero d'ordine della misura che ne ha preso il posto",
  alternatives: "quante alternative ha una richiesta rifiutata",
  acceptAll: "quante richieste in attesa accetta «Accetta tutte»",
  acceptAllFailed: "quante richieste il dipartimento non ha accettato in blocco",
  rateLimited: "i secondi di attesa che dice il server dopo troppi tentativi di accesso",
};

describe("i testi con un numero dentro (it.ts)", () => {
  it("sono tutti conteggi o numeri d'ordine, elencati qui: uno nuovo va classificato", () => {
    const text = readFileSync(path.resolve(import.meta.dirname, "../i18n/it.ts"), "utf8");
    const names = [
      ...text.matchAll(
        /(\w+):\s*\(\s*\w+:\s*number(?:\s*\|\s*undefined)?(?:\s*,\s*\w+:\s*number)?\s*\)\s*=>/g,
      ),
    ].map((match) => match[1] ?? "");
    expect(names.length).toBeGreaterThan(10); // la ricerca li trova
    expect([...new Set(names)].sort()).toEqual(Object.keys(NUMERIC_TEXTS).sort());
  });
});
