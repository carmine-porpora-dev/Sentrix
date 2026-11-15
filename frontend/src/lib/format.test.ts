import { describe, expect, it } from "vitest";
import {
  decimalsFor,
  deltaTone,
  displayUnit,
  formatAsOf,
  formatDelta,
  formatMeasured,
  formatNumber,
  scaled,
} from "@/lib/format";

describe("formatNumber", () => {
  it.each([
    [1240, "veic·h", "1.240"],
    [858.457, "veic·h", "858"],
    [150000, "pax", "150.000"],
    [0, "n", "0"],
    [12, "n", "12"],
    [12.03, "min", "12,0"],
    [33.5, "min", "33,5"],
    [6.412, "km", "6,4"],
    [1.28, "rapporto", "128"],
    [0.96, "rapporto", "96"],
    [1.12, "rapporto", "112"],
    [2.5, "mbit", "2,5"],
  ])("%s %s → %s", (value, unit, text) => {
    expect(formatNumber(value, unit)).toBe(text);
  });

  it("il raggruppamento c'è anche a quattro cifre (il design scrive 1.240)", () => {
    expect(formatNumber(1240, "n")).toBe("1.240");
    expect(formatNumber(999, "n")).toBe("999");
    expect(formatNumber(1_000_000, "n")).toBe("1.000.000");
  });

  it("un numero che si arrotonda a zero non ha il segno meno", () => {
    expect(formatNumber(-0.004, "min")).toBe("0,0");
    expect(formatNumber(-0.2, "n")).toBe("0");
    expect(formatNumber(-0.5, "min")).toBe("-0,5");
  });

  it("il rapporto è mostrato in percentuale ma il valore non cambia", () => {
    expect(scaled(1.28, "rapporto")).toBeCloseTo(128, 9);
    expect(scaled(7, "min")).toBe(7);
    expect(decimalsFor("rapporto")).toBe(0);
    expect(decimalsFor("sconosciuta")).toBe(1);
  });
});

describe("displayUnit", () => {
  it.each([
    ["veic·h", "ore-veicolo"],
    ["pax", "persone"],
    ["n", ""],
    ["rapporto", "%"],
    ["min", "min"],
    ["km", "km"],
    ["testo", ""],
    ["veic/h", "veic/h"],
  ])("%s → «%s»", (unit, shown) => {
    expect(displayUnit(unit)).toBe(shown);
  });
});

describe("formatMeasured", () => {
  it("valore e unità", () => {
    expect(formatMeasured({ value: 1240, unit: "veic·h" })).toEqual({
      text: "1.240",
      unit: "ore-veicolo",
    });
    expect(formatMeasured({ value: 1.28, unit: "rapporto" })).toEqual({ text: "128", unit: "%" });
    expect(formatMeasured({ value: 7, unit: "n" })).toEqual({ text: "7", unit: "" });
  });

  it("una metrica di testo resta com'è", () => {
    expect(formatMeasured({ value: "itinerario 1: A → B", unit: "testo" })).toEqual({
      text: "itinerario 1: A → B",
      unit: "",
    });
  });
});

describe("formatDelta", () => {
  it("segno sempre presente, meno vero (U+2212)", () => {
    expect(formatDelta({ value: -330, unit: "veic·h" })).toEqual({
      text: "−330",
      unit: "ore-veicolo",
      direction: "down",
    });
    expect(formatDelta({ value: 5.2, unit: "min" })).toEqual({
      text: "+5,2",
      unit: "min",
      direction: "up",
    });
    expect(formatDelta({ value: -4, unit: "n" })).toEqual({
      text: "−4",
      unit: "",
      direction: "down",
    });
  });

  it("i rapporti sono punti percentuali", () => {
    expect(formatDelta({ value: -0.32, unit: "rapporto" })).toEqual({
      text: "−32",
      unit: "pp",
      direction: "down",
    });
    expect(formatDelta({ value: 0.05, unit: "rapporto" })).toEqual({
      text: "+5",
      unit: "pp",
      direction: "up",
    });
  });

  it("zero e differenze che si arrotondano a zero non hanno segno né freccia", () => {
    expect(formatDelta({ value: 0, unit: "n" })).toEqual({
      text: "0",
      unit: "",
      direction: "none",
    });
    expect(formatDelta({ value: -0.004, unit: "min" })).toEqual({
      text: "0,0",
      unit: "min",
      direction: "none",
    });
    expect(formatDelta({ value: 0.003, unit: "rapporto" })).toEqual({
      text: "0",
      unit: "pp",
      direction: "none",
    });
  });

  it("il testo non ha direzione", () => {
    expect(formatDelta({ value: "cambiato", unit: "testo" }).direction).toBe("none");
  });
});

describe("deltaTone", () => {
  it("dove meno è meglio, scendere è meglio e salire è peggio", () => {
    expect(deltaTone("down", "lower")).toBe("better");
    expect(deltaTone("up", "lower")).toBe("worse");
  });

  it("dove più è meglio è il contrario", () => {
    expect(deltaTone("up", "higher")).toBe("better");
    expect(deltaTone("down", "higher")).toBe("worse");
  });

  it("nessuna variazione o nessun verso: neutro", () => {
    expect(deltaTone("none", "lower")).toBe("neutral");
    expect(deltaTone("up", "none")).toBe("neutral");
    expect(deltaTone("down", "none")).toBe("neutral");
  });
});

describe("formatAsOf", () => {
  it("giorno, mese, anno e ora nel fuso di Roma", () => {
    expect(formatAsOf("2026-11-09T10:00:50+01:00")).toBe("09/11/2026 10:00");
    expect(formatAsOf("2026-11-09T09:00:50Z")).toBe("09/11/2026 10:00");
    expect(formatAsOf("2026-07-10T21:40:00+02:00")).toBe("10/07/2026 21:40");
  });

  it("l'ora legale: lo stesso istante UTC d'estate è un'ora più avanti", () => {
    expect(formatAsOf("2026-07-10T19:40:00Z")).toBe("10/07/2026 21:40");
  });

  it("mezzanotte è 00:00, non 24:00", () => {
    expect(formatAsOf("2026-11-09T00:00:00+01:00")).toBe("09/11/2026 00:00");
  });

  it("un testo che non è una data resta com'è", () => {
    expect(formatAsOf("ieri")).toBe("ieri");
  });
});
