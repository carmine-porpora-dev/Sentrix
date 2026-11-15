import { describe, expect, it } from "vitest";
import { parseAnswer, parseInline, type Segment } from "@/lib/answer";

const text = (value: string): Segment => ({ type: "text", value });
const number = (value: string): Segment => ({ type: "number", value });
const chip = (kind: "strada" | "linea" | "fermata" | "luogo", label: string): Segment => ({
  type: "chip",
  kind,
  label,
});

describe("parseInline", () => {
  it("lascia il testo semplice com'è", () => {
    expect(parseInline("Dimmi da dove parti.")).toEqual([text("Dimmi da dove parti.")]);
  });

  it("riconosce i quattro tipi di chip", () => {
    expect(
      parseInline(
        "[[strada:Via Tasso]] [[linea:Linea 1]] [[fermata:Piazza Vittoria]] [[luogo:Mergellina]]",
      ),
    ).toEqual([
      chip("strada", "Via Tasso"),
      text(" "),
      chip("linea", "Linea 1"),
      text(" "),
      chip("fermata", "Piazza Vittoria"),
      text(" "),
      chip("luogo", "Mergellina"),
    ]);
  });

  it("non scambia per numeri le cifre dentro un'etichetta di chip", () => {
    expect(parseInline("[[linea:Linea 2]]")).toEqual([chip("linea", "Linea 2")]);
  });

  it("mette in evidenza orari e quantità con unità", () => {
    expect(parseInline("Parti alle 13:30, circa 10,2 min e 6.79 km, 1158 m, 2 h, 30%.")).toEqual([
      text("Parti alle "),
      number("13:30"),
      text(", circa "),
      number("10,2 min"),
      text(" e "),
      number("6.79 km"),
      text(", "),
      number("1158 m"),
      text(", "),
      number("2 h"),
      text(", "),
      number("30%"),
      text("."),
    ]);
  });

  it("riconosce il numero esplicito tra doppi asterischi", () => {
    expect(parseInline("a circa **8 min** a piedi")).toEqual([
      text("a circa "),
      number("8 min"),
      text(" a piedi"),
    ]);
  });

  it("non tratta come numeri le cifre dentro una parola o senza unità", () => {
    expect(parseInline("Via 4 Novembre, il 26 settembre, 3 mesi, L1")).toEqual([
      text("Via 4 Novembre, il 26 settembre, 3 mesi, L1"),
    ]);
  });

  it("un orario non scambia un decimale per un'ora", () => {
    expect(parseInline("v/c 1,62")).toEqual([text("v/c 1,62")]);
  });

  it("una chip senza chiusura resta testo", () => {
    expect(parseInline("[[strada:Via Tasso")).toEqual([text("[[strada:Via Tasso")]);
  });
});

describe("parseAnswer", () => {
  it("un testo vuoto non ha blocchi", () => {
    expect(parseAnswer("")).toEqual([]);
    expect(parseAnswer("  \n \n")).toEqual([]);
  });

  it("separa i paragrafi con una riga vuota e tiene gli a capo semplici", () => {
    const blocks = parseAnswer("Prima riga\nseconda riga\n\nAltro paragrafo");
    expect(blocks).toEqual([
      { type: "paragraph", segments: [text("Prima riga\nseconda riga")] },
      { type: "paragraph", segments: [text("Altro paragrafo")] },
    ]);
  });

  it("raccoglie i passi numerati in un elenco e non si fida dei numeri scritti", () => {
    const blocks = parseAnswer("Ecco:\n\n3. Vai dritto\n7) Gira a [[strada:Via Foria]]\n\nFine.");
    expect(blocks).toEqual([
      { type: "paragraph", segments: [text("Ecco:")] },
      {
        type: "steps",
        items: [[text("Vai dritto")], [text("Gira a "), chip("strada", "Via Foria")]],
      },
      { type: "paragraph", segments: [text("Fine.")] },
    ]);
  });

  it("i passi separati da una riga vuota restano un solo elenco", () => {
    const blocks = parseAnswer("1. Uno\n\n2. Due");
    expect(blocks).toEqual([{ type: "steps", items: [[text("Uno")], [text("Due")]] }]);
  });

  it("un numero decimale a inizio riga non è un passo", () => {
    const blocks = parseAnswer("10.2 min è il tempo stimato");
    expect(blocks).toEqual([
      { type: "paragraph", segments: [number("10.2 min"), text(" è il tempo stimato")] },
    ]);
  });

  it("accetta gli a capo di Windows", () => {
    expect(parseAnswer("Uno\r\n\r\nDue")).toHaveLength(2);
  });
});
