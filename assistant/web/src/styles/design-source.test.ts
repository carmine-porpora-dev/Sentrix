import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const CSS = join(import.meta.dirname, "..", "index.css");

// Lo stadio di build dell'immagine copia solo `design/design-system/` (come lo stadio `frontend`
// del Dockerfile): se il CSS leggesse altro da `design/`, la build in Docker fallirebbe.
describe("token e font del designer", () => {
  const imports = [...readFileSync(CSS, "utf-8").matchAll(/@import\s+"([^"]+)"/g)].map((m) => m[1]);
  const fromDesign = imports.filter((path) => path.includes("design/"));

  it("il CSS importa i token e i font da design/design-system", () => {
    expect(fromDesign.map((path) => path.replace(/^(\.\.\/)+/, ""))).toEqual([
      "design/design-system/fonts/fonts.css",
      "design/design-system/tokens.css",
    ]);
  });

  it("i file esistono e stanno solo in design/design-system", () => {
    const root = resolve(import.meta.dirname, "../../../../design/design-system");
    for (const path of fromDesign) {
      const file = resolve(join(import.meta.dirname, ".."), path);
      expect(file.startsWith(root)).toBe(true);
      expect(existsSync(file)).toBe(true);
    }
  });
});
