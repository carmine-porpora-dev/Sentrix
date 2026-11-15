import path from "node:path";
import { build } from "vite";
import { beforeAll, describe, expect, it } from "vitest";
import { readTokens } from "../../scripts/tokens-to-tailwind.ts";

const ROOT = path.resolve(import.meta.dirname, "../..");

/** Ciò che serve del risultato di `build({ write: false })`. */
interface BuildOutput {
  output: { fileName: string; source?: string | Uint8Array }[];
}

const TRANSPARENT = "#00000000";

/** Un colore come `#rrggbbaa` minuscolo (accetta #rgb, #rgba, #rrggbb, #rrggbbaa, rgb()/rgba() con
 * virgole o spazi); `undefined` se non è nessuna di queste forme. */
function toHex8(literal: string): string | undefined {
  const text = literal.trim().toLowerCase();
  const hex = /^#([0-9a-f]{3,8})$/.exec(text)?.[1];
  if (hex) {
    if (hex.length === 3 || hex.length === 4)
      return `#${[...hex].map((c) => c + c).join("")}`.padEnd(9, "f");
    if (hex.length === 6) return `#${hex}ff`;
    if (hex.length === 8) return `#${hex}`;
    return undefined;
  }
  const fn = /^rgba?\(([^)]*)\)$/.exec(text)?.[1];
  if (!fn) return undefined;
  const parts = fn.split(/[\s,/]+/).filter(Boolean);
  if (parts.length < 3 || parts.length > 4) return undefined;
  const channels = parts.slice(0, 3).map(Number);
  const alpha =
    parts[3] === undefined
      ? 1
      : parts[3].endsWith("%")
        ? Number.parseFloat(parts[3]) / 100
        : Number(parts[3]);
  if ([...channels, alpha].some((n) => Number.isNaN(n))) return undefined;
  const byte = (n: number) =>
    Math.round(Math.min(Math.max(n, 0), 255))
      .toString(16)
      .padStart(2, "0");
  return `#${channels.map(byte).join("")}${byte(alpha * 255)}`;
}

/** I colori dichiarati dai token del designer, come `#rrggbbaa`. */
function tokenColors(): string[] {
  return Object.values(readTokens().tokens.color ?? {}).flatMap((value) => toHex8(value) ?? []);
}

/** Ogni colore scritto nel CSS (esadecimale, rgb(), rgba(), hsl(), hsla()), come [testo, #rrggbbaa]. Un
 * colore che non si sa leggere (hsl, oklch…) vale `?`: non sarà mai tra i permessi. */
function colorLiterals(css: string): [string, string][] {
  const found =
    css.match(/#[0-9a-fA-F]{3,8}\b|(?:rgba?|hsla?|oklch|oklab|lab|lch|color)\([^)]*\)/g) ?? [];
  return found.map((literal) => [literal, toHex8(literal) ?? "?"]);
}

describe("la build usa i token (F4-02)", () => {
  let css = "";
  let fonts: string[] = [];

  beforeAll(async () => {
    const result = (await build({
      root: ROOT,
      logLevel: "silent",
      mode: "production",
      build: { write: false, minify: false },
    })) as BuildOutput;
    // due fogli: quello dell'interfaccia (con i token) e quello di MapLibre, nel chunk della mappa
    const sheets = result.output
      .filter((file) => file.fileName.endsWith(".css"))
      .map((file) => String(file.source));
    expect(sheets).toHaveLength(2);
    const own = sheets.filter((sheet) => sheet.includes("--surface-card:"));
    expect(own).toHaveLength(1);
    css = own[0] ?? "";
    fonts = result.output.map((file) => file.fileName).filter((name) => name.endsWith(".woff2"));
  }, 60_000);

  it("il CSS ha tutte le variabili dei token, con i valori del designer", () => {
    const tokens = readTokens().tokens;
    for (const [family, entries] of Object.entries(tokens)) {
      for (const [key, value] of Object.entries(entries)) {
        const declared = new RegExp(
          `--${key}:\\s*${value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/,/g, ",\\s*")}\\s*;`,
          "i",
        );
        expect(css, `${family}.${key}`).toMatch(declared);
      }
    }
  });

  it("le classi che l'interfaccia usa puntano ai token", () => {
    expect(css).toMatch(/\.bg-surface-card\s*\{\s*background-color:\s*var\(--surface-card\)/);
    expect(css).toMatch(/\.h-size-control-height\s*\{\s*height:\s*var\(--size-control-height\)/);
    expect(css).toMatch(/\.rounded-card\s*\{\s*border-radius:\s*var\(--radius-card\)/);
    expect(css).toMatch(/\.text-danger\s*\{\s*color:\s*var\(--color-danger\)/);
  });

  it("il corpo della pagina è il fondo, il testo e il font del designer", () => {
    expect(css).toMatch(/body\s*\{[^}]*background-color:\s*var\(--surface-screen\)[^}]*\}/);
    expect(css).toMatch(/body\s*\{[^}]*font-family:\s*var\(--font-ui\)[^}]*\}/);
    expect(css).toMatch(/body\s*\{[^}]*color:\s*var\(--text-primary\)[^}]*\}/);
    expect(css).toMatch(
      /:focus-visible\s*\{[^}]*outline:\s*var\(--border-control\)\s+solid\s+var\(--focus-ring\)/,
    );
  });

  it("le colonne del guscio (F4-03): compatte sotto 1440 px, intere da 1440, binario e pannello largo", () => {
    const flat = css.replace(/\s+/g, " ");
    expect(flat).toContain(
      "grid-template-columns: var(--layout-event-manager-compact) minmax(0,1fr) var(--layout-right-panel-compact)",
    );
    expect(flat).toContain(
      "grid-template-columns: var(--layout-event-manager-rail) minmax(0,1fr) var(--layout-right-panel-wide)",
    );
    // le colonne intere stanno dentro la media query dei 1440 px (nessun'altra le attiva)
    const full =
      ".compact\\:grid-cols-\\[var\\(--layout-event-manager\\)_minmax\\(0\\2c 1fr\\)_var\\(--layout-right-panel\\)\\]";
    const at = flat.indexOf(full);
    expect(at).toBeGreaterThan(0);
    const before = flat.slice(flat.lastIndexOf("@media", at), at);
    expect(before).toMatch(
      /^@media \((?:min-width: ?1440px|width ?>= ?1440px)\) \{(?:[^{}]|\{[^{}]*\})*$/,
    );
    expect(flat.slice(at, at + 400)).toContain(
      "grid-template-columns: var(--layout-event-manager) minmax(0,1fr) var(--layout-right-panel)",
    );
  });

  it("il colore predefinito dei bordi è quello del designer (non il grigio di Tailwind)", () => {
    // il reset di base (preflight) scrive `border: 0 solid <colore>` su tutto
    expect(css).toMatch(
      /\*,\s*::?before,\s*::?after\s*\{[^}]*border-color:\s*var\(--color-border\)/,
    );
  });

  it("nel CSS dell'interfaccia non c'è nessun colore che non sia dei token (F4-REF)", () => {
    const allowed = new Set([...tokenColors(), TRANSPARENT]);
    const found = colorLiterals(css);
    expect(found.length).toBeGreaterThan(20); // la ricerca trova i colori: non è vuota per un errore
    const outside = [...new Set(found.map(([literal, hex]) => (allowed.has(hex) ? "" : literal)))];
    expect(outside.filter(Boolean)).toEqual([]);
  });

  it("il popup della mappa ha lo stile del tooltip del design, non il bianco di MapLibre (F4-05)", () => {
    const popup = css.match(
      /\.maplibregl-popup\.nuo-popup \.maplibregl-popup-content\s*\{([^}]*)\}/,
    )?.[1];
    expect(popup).toBeDefined();
    expect(popup).toContain("background-color: var(--color-surface-2)");
    expect(popup).toContain("border-color: var(--color-border-tooltip)");
    expect(popup).toContain("border-radius: var(--radius-tooltip)");
    expect(popup).toContain("color: var(--text-primary)");
    // la punta ha lo stesso colore del fondo, da qualunque lato sia ancorato il popup
    for (const side of ["top", "bottom", "left", "right"]) {
      expect(css).toMatch(
        new RegExp(
          `popup-anchor-${side}\\.nuo-popup \\.maplibregl-popup-tip\\s*\\{[^}]*var\\(--color-surface-2\\)`,
        ),
      );
    }
  });

  it("i font sono nella build: sette @font-face, file hashati accanto, nessun indirizzo esterno", () => {
    const faces = css.match(/@font-face\s*\{[^}]*\}/g) ?? [];
    expect(faces).toHaveLength(7);
    for (const face of faces) {
      expect(face).toMatch(/url\(["']?\/assets\/[\w.-]+\.woff2["']?\)/);
      expect(face).not.toMatch(/https?:/);
    }
    expect(fonts).toHaveLength(7);
  });

  it("il tema provvisorio di shadcn non c'è più", () => {
    for (const name of ["background", "foreground", "primary", "card", "muted", "ring", "radius"]) {
      expect(css, `--${name}`).not.toMatch(new RegExp(`(^|[;{\\s])--${name}\\s*:`));
    }
  });
});
