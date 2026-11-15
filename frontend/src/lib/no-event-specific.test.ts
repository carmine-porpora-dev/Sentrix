import { describe, expect, it } from "vitest";
import { offences, sources } from "../test/sources.ts";

// F7-REF, principio 4: l'Evento è un dato. Nessun sorgente dell'interfaccia nomina un evento
// precaricato né confronta l'Evento con un nome o un id (`if (event.id === …)`). Gli eventi
// demo sono dati dell'API (e le fixture); i test e le prove e2e possono nominarli.

const SEED_EVENT = /match_2027|regate_sep_2026|Match 2027|Regate settembre|Regate\b/;
const COMPARES_EVENT = /\bevent(?:\??\.|\.)(?:id|name)\s*[!=]==?\s*["'`]/;

describe("nessun codice dedicato a un singolo evento (F7-REF, principio 4)", () => {
  it("il test legge i sorgenti", () => {
    expect(sources().length).toBeGreaterThan(60);
  });

  it("nessun sorgente nomina un evento precaricato", () => {
    expect(offences(SEED_EVENT)).toEqual([]);
  });

  it("nessun sorgente confronta l'id o il nome dell'Evento con un valore scritto a mano", () => {
    expect(offences(COMPARES_EVENT)).toEqual([]);
  });

  it("le regole trovano le violazioni (prova)", () => {
    for (const bad of ['if (event.id === "match_2027") {', "return <p>Match 2027</p>;"]) {
      expect(SEED_EVENT.test(bad) || COMPARES_EVENT.test(bad)).toBe(true);
    }
    expect(COMPARES_EVENT.test('if (event.id === "x") {')).toBe(true);
    expect(COMPARES_EVENT.test("if (event.id === eventId) {")).toBe(false);
  });
});
