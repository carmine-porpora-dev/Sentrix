import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { readTokens } from "../../scripts/tokens-to-tailwind.ts";

const SRC = path.resolve(import.meta.dirname, "..");
const FONTS = path.join(SRC, "assets", "fonts");
const DESIGN_FONTS = path.resolve(SRC, "../../design/design-system/fonts");
const css = readFileSync(path.join(SRC, "styles", "fonts.css"), "utf8");

interface Face {
  family: string;
  weight: number;
  display: string;
  file: string;
}

/** Le dichiarazioni `@font-face` di `fonts.css`. */
function faces(): Face[] {
  return Array.from(css.matchAll(/@font-face\s*\{([^}]*)\}/g), (match) => {
    const body = match[1] as string;
    const pick = (property: string) =>
      new RegExp(`${property}:\\s*([^;]+);`).exec(body)?.[1]?.trim() ?? "";
    return {
      family: pick("font-family").replace(/["']/g, ""),
      weight: Number(pick("font-weight")),
      display: pick("font-display"),
      file: /url\("\.\.\/assets\/fonts\/([^"]+)"\)/.exec(body)?.[1] ?? "",
    };
  });
}

describe("i font del design system (F4-08)", () => {
  it("sette facce: Plus Jakarta Sans 400/500/600/700 e Geist Mono 500/600/700", () => {
    expect(faces().map((f) => `${f.family} ${f.weight}`)).toEqual([
      "Plus Jakarta Sans 400",
      "Plus Jakarta Sans 500",
      "Plus Jakarta Sans 600",
      "Plus Jakarta Sans 700",
      "Geist Mono 500",
      "Geist Mono 600",
      "Geist Mono 700",
    ]);
  });

  it("ogni faccia punta a un file che c'è, col nome della sua famiglia e del suo peso", () => {
    const present = new Set(readdirSync(FONTS));
    for (const face of faces()) {
      expect(present.has(face.file), face.file).toBe(true);
      expect(face.file).toBe(`${face.family.replace(/ /g, "")}-${face.weight}-normal.woff2`);
    }
  });

  it("nessun file in più, nessuno senza dichiarazione", () => {
    expect(readdirSync(FONTS).sort()).toEqual(
      faces()
        .map((f) => f.file)
        .sort(),
    );
  });

  it("i file sono quelli del designer, byte per byte (se il designer li cambia, qui si vede)", () => {
    for (const name of readdirSync(FONTS)) {
      const ours = readFileSync(path.join(FONTS, name));
      const theirs = readFileSync(path.join(DESIGN_FONTS, name));
      expect(ours.equals(theirs), name).toBe(true);
    }
  });

  it("le famiglie sono le prime dei token --font-ui e --font-mono", () => {
    const { tokens } = readTokens();
    const first = (value: string) => (value.split(",")[0] as string).replace(/["']/g, "").trim();
    const families = new Set(faces().map((f) => f.family));
    expect(families).toEqual(
      new Set([first(tokens.font["font-ui"] as string), first(tokens.font["font-mono"] as string)]),
    );
  });

  it("nessuna richiesta esterna: tutti gli url sono relativi; font-display swap (il testo si vede subito)", () => {
    expect(css).not.toMatch(/https?:\/\//);
    expect(css).not.toMatch(/url\(\s*["']?\//);
    for (const face of faces()) expect(face.display).toBe("swap");
  });

  it("il testo della licenza (OFL 1.1) e i due copyright stanno in public/licenses/OFL.txt", () => {
    const licence = readFileSync(path.resolve(SRC, "../public/licenses/OFL.txt"), "utf8");
    expect(licence).toContain("SIL OPEN FONT LICENSE Version 1.1");
    expect(licence).toContain("Copyright 2020 The Plus Jakarta Sans Project Authors");
    expect(licence).toContain("Copyright 2024 The Geist Project Authors");
    expect(licence).toContain("PERMISSION & CONDITIONS");
    expect(licence).toContain("DISCLAIMER");
  });
});
