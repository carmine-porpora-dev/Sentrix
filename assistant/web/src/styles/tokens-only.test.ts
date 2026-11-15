import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
const TOKEN_FILE = "assistant-tokens.css";

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sources(path);
    return /\.(ts|tsx|css)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

const files = sources(SRC).filter((path) => !path.endsWith(TOKEN_FILE));

describe("colori e icone", () => {
  it("nel codice non c'è nessun colore scritto a mano: solo token", () => {
    const offenders = files.filter((path) => {
      const content = readFileSync(path, "utf-8");
      return /#[0-9a-fA-F]{3,8}\b/.test(content) || /\brgba?\(\s*\d/.test(content);
    });
    expect(offenders).toEqual([]);
  });

  it("nessun testo sotto i 14px, tranne il numero del passo (13px, da design)", () => {
    const small = files.flatMap((path) => {
      const found = readFileSync(path, "utf-8").match(/text-\[(\d+)px\]/g) ?? [];
      return found.filter((match) => match !== "text-[13px]");
    });
    expect(small).toEqual([]);
  });

  it("l'icona di invio non è mai la freccia in su", () => {
    const offenders = files.filter((path) => /ArrowUp|arrow-up/.test(readFileSync(path, "utf-8")));
    expect(offenders).toEqual([]);
  });
});
