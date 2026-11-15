import { readFileSync } from "node:fs";
import path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import { strings } from "@/i18n/it";
import { sources } from "../test/sources.ts";

// F7-REF: i testi che si leggono a schermo stanno in `i18n/it.ts` (07 1: un solo file). Il test legge i
// componenti (`.tsx`) con il compilatore di TypeScript e fallisce se trova un testo scritto a mano
// dentro il JSX o in un attributo che si legge (nome assistivo, suggerimento, segnaposto).

const SRC = path.resolve(import.meta.dirname, "..");
const READ_ATTRIBUTES = new Set(["aria-label", "aria-description", "title", "placeholder", "alt"]);
const LETTER = /\p{L}/u;

/** I testi scritti a mano nel JSX di un file, con la riga. */
function handWritten(file: string, text: string): string[] {
  const found: string[] = [];
  const tree = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const at = (node: ts.Node) => tree.getLineAndCharacterOfPosition(node.getStart()).line + 1;
  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node) && LETTER.test(node.text)) {
      found.push(`${file}:${at(node)}  testo nel JSX «${node.text.trim().slice(0, 40)}»`);
    }
    if (
      ts.isJsxExpression(node) &&
      !ts.isJsxAttribute(node.parent) && // quello di un attributo lo giudica la regola degli attributi
      node.expression &&
      ts.isStringLiteralLike(node.expression)
    ) {
      if (LETTER.test(node.expression.text)) {
        found.push(`${file}:${at(node)}  testo in {…} «${node.expression.text.slice(0, 40)}»`);
      }
    }
    if (ts.isJsxAttribute(node) && READ_ATTRIBUTES.has(node.name.getText())) {
      const value = node.initializer;
      const literal =
        value && ts.isJsxExpression(value) && value.expression ? value.expression : value;
      if (literal && ts.isStringLiteralLike(literal) && LETTER.test(literal.text)) {
        found.push(`${file}:${at(node)}  ${node.name.getText()} «${literal.text.slice(0, 40)}»`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(tree);
  return found;
}

describe("i testi stanno in i18n/it.ts (F7-REF)", () => {
  const components = sources().filter((source) => source.file.endsWith(".tsx"));

  it("il test legge i componenti (non passa per una cartella sbagliata)", () => {
    expect(components.length).toBeGreaterThan(40);
    expect(components.map((c) => c.file)).toContain("components/MetricCard.tsx");
  });

  it("nessun testo scritto a mano nel JSX né in aria-label, title, placeholder, alt", () => {
    const offences = components.flatMap(({ file }) =>
      handWritten(file, readFileSync(path.join(SRC, file), "utf8")),
    );
    expect(offences).toEqual([]);
  });

  it("il controllo li trova (prova su un sorgente con le violazioni)", () => {
    const bad = [
      "export const A = () => <p>Testo a mano</p>;",
      'export const B = () => <button aria-label="Chiudi" />;',
      'export const C = () => <input placeholder={"Cerca"} title="Suggerimento" />;',
      'export const D = () => <span>{"Fatto"}</span>;',
    ].join("\n");
    expect(handWritten("x.tsx", bad)).toHaveLength(5);
    const good = [
      "export const A = () => <p>{strings.a}</p>;",
      "export const B = () => <button aria-label={strings.b} />;",
      'export const C = () => <svg className="size-4" data-testid="x" role="img" />;',
      'export const D = () => <span>{1}{" "}·{" "}</span>;',
    ].join("\n");
    expect(handWritten("y.tsx", good)).toEqual([]);
  });
});

describe("un nome, un posto (F7-REF)", () => {
  it("le finestre si chiamano allo stesso modo ovunque (selettore, card, Event Manager)", () => {
    expect(strings.events.arrival).toBe(strings.metrics.windows.arrival);
    expect(strings.events.departure).toBe(strings.metrics.windows.departure);
    expect(strings.events.windowOptions.arrival).toBe(strings.metrics.windows.arrival);
    expect(strings.events.windowOptions.departure).toBe(strings.metrics.windows.departure);
  });

  it("«il server non risponde» è detto allo stesso modo dall'API, dall'accesso e dalla sessione", () => {
    expect(strings.login.network).toBe(`${strings.serverDown}. Riprova.`);
    expect(strings.session.unavailable.toLowerCase()).toContain(strings.serverDown.toLowerCase());
  });
});
