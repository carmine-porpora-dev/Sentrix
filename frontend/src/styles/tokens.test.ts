import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import postcss from "postcss";
import tailwindcss from "tailwindcss";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  OUTPUTS,
  TOKENS_JSON,
  TokenError,
  generate,
  main,
  readTokens,
  staleOutputs,
  tokensToCss,
  tokensToTheme,
} from "../../scripts/tokens-to-tailwind.ts";
import tailwindConfig from "../../tailwind.config.ts";
import { tokenTheme, tokenUtilities } from "./tailwind-theme.generated.ts";
import type { DesignTokens } from "./token-types.ts";

/** Un insieme di token piccolo ma completo, per provare le regole una per una. */
function tokens(overrides: Record<string, Record<string, string>> = {}): DesignTokens {
  return {
    name: "Prova",
    source: "test",
    extracted: "2026-11-10",
    theme: "dark",
    tokens: {
      color: { "color-bg": "#000000", "color-data-real": "#12BFA0" },
      surface: { "surface-card": "var(--color-bg)" },
      text: { "text-primary": "var(--color-bg)" },
      action: { action: "var(--color-bg)", "action-hover": "var(--color-bg)" },
      focus: { "focus-ring": "var(--color-bg)" },
      font: { "font-ui": "'Prova',sans-serif" },
      fs: { "fs-xl": "24px" },
      lh: { "lh-xl": "32px" },
      fw: { "fw-xl": "600" },
      ls: { "ls-xl": "-.01em" },
      space: { "space-8": "8px" },
      radius: { "radius-card": "10px" },
      border: { "border-hairline": "1px" },
      size: { "size-icon": "20px", "size-icon-stroke": "1.5" },
      layout: { "layout-gap": "16px" },
      breakpoint: { "breakpoint-compact": "1440px" },
      opacity: { "opacity-badge-fill": ".16" },
      motion: { "motion-duration": "150ms", "motion-easing": "ease-out" },
      transition: { "transition-base": "color var(--motion-duration)" },
      ...overrides,
    },
  };
}

describe("tokensToCss", () => {
  it("scrive una variabile per token, con il nome intero e il valore com'è", () => {
    const css = tokensToCss(tokens());
    expect(css).toContain("  --color-bg: #000000;");
    expect(css).toContain("  --surface-card: var(--color-bg);");
    expect(css).toContain("  --font-ui: 'Prova',sans-serif;");
    expect(css).toContain("  --transition-base: color var(--motion-duration);");
    expect(css.startsWith(":root {")).toBe(true);
    expect(css.match(/^ {2}--/gm)).toHaveLength(23);
  });

  it("segue l'ordine di tokens.json e dichiara la famiglia", () => {
    const css = tokensToCss(tokens());
    expect(css.indexOf("/* color */")).toBeLessThan(css.indexOf("/* surface */"));
    expect(css.indexOf("--color-bg")).toBeLessThan(css.indexOf("--color-data-real"));
  });
});

describe("tokensToTheme", () => {
  const { extend, utilities } = tokensToTheme(tokens());

  it("i colori sono il token senza `color-`, le famiglie semantiche con il loro nome", () => {
    expect(extend.colors).toEqual({
      bg: "var(--color-bg)",
      "data-real": "var(--color-data-real)",
      "surface-card": "var(--surface-card)",
      "text-primary": "var(--text-primary)",
      action: "var(--action)",
      "action-hover": "var(--action-hover)",
      "focus-ring": "var(--focus-ring)",
    });
  });

  it("i valori sono variabili CSS, mai i valori dei token", () => {
    const all = JSON.stringify(extend);
    expect(all).not.toContain("#000000");
    expect(all).not.toContain("24px");
  });

  it("corpo, interlinea, peso e spaziatura vanno insieme", () => {
    expect(extend.fontSize).toEqual({
      xl: [
        "var(--fs-xl)",
        { lineHeight: "var(--lh-xl)", fontWeight: "var(--fw-xl)", letterSpacing: "var(--ls-xl)" },
      ],
    });
  });

  it("lo spessore di un bordo che ha lo stesso nome di un colore prende il suffisso -width", () => {
    const clash = tokensToTheme(
      tokens({
        color: { "color-bg": "#000", "color-scenario-frame": "#f60" },
        border: { "border-hairline": "1px", "border-scenario-frame": "4px" },
      }),
    ).extend;
    expect(clash.borderWidth).toEqual({
      hairline: "var(--border-hairline)",
      "scenario-frame-width": "var(--border-scenario-frame)",
    });
    expect(clash.colors["scenario-frame"]).toBe("var(--color-scenario-frame)");
  });

  it("font, angoli, bordi e opacità senza il prefisso della famiglia", () => {
    expect(extend.fontFamily).toEqual({ ui: "var(--font-ui)" });
    expect(extend.borderRadius).toEqual({ card: "var(--radius-card)" });
    expect(extend.borderWidth).toEqual({ hairline: "var(--border-hairline)" });
    expect(extend.opacity).toEqual({ "badge-fill": "var(--opacity-badge-fill)" });
  });

  it("le misure hanno il nome intero del token e stanno in `spacing`", () => {
    expect(extend.spacing).toEqual({
      "space-8": "var(--space-8)",
      "layout-gap": "var(--layout-gap)",
      "size-icon": "var(--size-icon)",
    });
  });

  it("un numero senza unità (lo spessore del tratto) non è una misura", () => {
    expect(extend.strokeWidth).toEqual({ "size-icon-stroke": "var(--size-icon-stroke)" });
    expect(extend.spacing).not.toHaveProperty("size-icon-stroke");
  });

  it("il breakpoint è il valore (Tailwind non accetta var() negli schermi)", () => {
    expect(extend.screens).toEqual({ compact: "1440px" });
  });

  it("movimento e transizione", () => {
    expect(extend.transitionDuration).toEqual({ motion: "var(--motion-duration)" });
    expect(extend.transitionTimingFunction).toEqual({ motion: "var(--motion-easing)" });
    expect(utilities).toEqual({ ".transition-base": { transition: "var(--transition-base)" } });
  });
});

describe("tokensToTheme: gli errori sono errori, non voci perse", () => {
  const fails = (overrides: Record<string, Record<string, string>>, message: RegExp) => {
    expect(() => tokensToTheme(tokens(overrides))).toThrow(TokenError);
    expect(() => tokensToTheme(tokens(overrides))).toThrow(message);
  };

  it("una famiglia sconosciuta (anche per il CSS: nessuna variabile senza classe)", () => {
    fails({ shadow: { "shadow-card": "0 0 1px #000" } }, /famiglia di token sconosciuta «shadow»/);
    expect(() => tokensToCss(tokens({ shadow: { "shadow-card": "0 0 1px #000" } }))).toThrow(
      TokenError,
    );
  });

  it("un token che non comincia per il prefisso della sua famiglia", () => {
    fails({ color: { bg: "#000" } }, /«bg» non comincia per «color-»/);
    fails({ surface: { card: "#000" } }, /«card» non comincia per «surface»/);
    fails({ radius: { card: "10px" } }, /«card» non comincia per «radius-»/);
    fails({ space: { "8": "8px" } }, /non comincia per «space-»/);
  });

  it("un prefisso senza nome dopo", () => {
    fails({ color: { "color-": "#000" } }, /non comincia per «color-»/);
  });

  it("un valore vuoto", () => {
    fails(
      { color: { "color-bg": " " } },
      /color\.color-bg: il valore deve essere un testo non vuoto/,
    );
  });

  it("due token sulla stessa classe", () => {
    fails({ color: { "color-surface-card": "#111111" } }, /due token finiscono su «surface-card»/);
  });

  it("un corpo senza interlinea, peso o spaziatura (e viceversa)", () => {
    fails({ lh: {} }, /lh: non corrisponde a fs \(mancano xl; in più -\)/);
    fails(
      { fw: { "fw-xl": "600", "fw-sm": "400" } },
      /fw: non corrisponde a fs \(mancano -; in più sm\)/,
    );
    fails({ ls: { "ls-md": "0" } }, /ls: non corrisponde a fs/);
  });

  it("un token di movimento che non conosciamo", () => {
    fails({ motion: { "motion-delay": "1s" } }, /«motion-delay» non gestito/);
  });
});

describe("i file generati", () => {
  const source = readTokens();

  it("sono quelli che lo script produce dai token del designer (npm run tokens)", () => {
    const generated = generate(source);
    expect(
      readFileSync(OUTPUTS.css, "utf8") === generated.css,
      "tokens.generated.css è indietro: `npm run tokens`",
    ).toBe(true);
    expect(
      readFileSync(OUTPUTS.theme, "utf8") === generated.theme,
      "tailwind-theme.generated.ts è indietro: `npm run tokens`",
    ).toBe(true);
  });

  it("hanno tutti i 157 token del designer", () => {
    const count = Object.values(source.tokens).reduce(
      (n, family) => n + Object.keys(family).length,
      0,
    );
    expect(count).toBe(157);
    expect(readFileSync(OUTPUTS.css, "utf8").match(/^ {2}--/gm)).toHaveLength(157);
  });

  it("coincidono con il tokens.css del designer, variabile per variabile", () => {
    const designer = readFileSync(TOKENS_JSON.replace("tokens.json", "tokens.css"), "utf8");
    const parse = (css: string) => {
      const found = new Map<string, string>();
      for (const [, name, value] of css.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
        found.set(name as string, (value as string).replace(/\s+/g, "").toLowerCase());
      }
      return found;
    };
    const ours = parse(readFileSync(OUTPUTS.css, "utf8"));
    const theirs = parse(designer);
    expect(ours.size).toBe(157);
    expect([...theirs.keys()].sort()).toEqual([...ours.keys()].sort());
    for (const [name, value] of theirs) expect(ours.get(name), name).toBe(value);
  });

  it("i nomi colore obbligatori del design system ci sono, con il valore del designer", () => {
    const required: Record<string, string> = {
      "data-real": "#12BFA0",
      "data-estimate": "#4DA3FF",
      "data-simulated": "#F26A2E",
      "scenario-frame": "#F26A2E",
      "status-accepted": "#12BFA0",
      "status-rejected": "#EE5663",
      "status-pending": "#D4A93A",
      "delta-better": "#12BFA0",
      "delta-worse": "#EE5663",
    };
    for (const [name, hex] of Object.entries(required)) {
      expect(tokenTheme.colors[name]).toBe(`var(--color-${name})`);
      expect(source.tokens.color?.[`color-${name}`]).toBe(hex);
    }
  });

  it("il testo più piccolo è di 14 px (07 2)", () => {
    const sizes = Object.entries(source.tokens.fs ?? {}).map(
      ([name, value]) => [name, Number.parseFloat(value)] as const,
    );
    expect(sizes.length).toBeGreaterThan(0);
    for (const [name, px] of sizes) expect(px, name).toBeGreaterThanOrEqual(14);
  });
});

describe("Tailwind usa i token", () => {
  async function compile(classes: string): Promise<string> {
    const config = { ...tailwindConfig, content: [{ raw: classes, extension: "html" }] };
    const result = await postcss([tailwindcss(config)]).process("@tailwind utilities;", {
      from: undefined,
    });
    return result.css.replace(/\s+/g, " ");
  }

  it("tailwind.config.ts prende tutto il tema dal file generato", () => {
    const theme = tailwindConfig.theme as {
      colors: Record<string, unknown>;
      extend: Record<string, unknown>;
    };
    const extend = theme.extend;
    // i colori sono `theme.colors` (sostituisce la palette di Tailwind), non `extend`: sono quelli del designer
    expect(extend.colors).toBeUndefined();
    for (const [name, value] of Object.entries(tokenTheme.colors ?? {})) {
      expect(theme.colors[name], name).toBe(value);
    }
    expect(extend.fontSize).toBe(tokenTheme.fontSize);
    expect(extend.spacing).toBe(tokenTheme.spacing);
    expect(Object.keys(tokenUtilities)).toEqual([".transition-base"]);
  });

  it.each([
    ["bg-bg", "background-color: var(--color-bg)"],
    ["bg-data-real", "background-color: var(--color-data-real)"],
    ["text-data-simulated", "color: var(--color-data-simulated)"],
    ["border-scenario-frame", "border-color: var(--color-scenario-frame)"],
    ["bg-surface-card", "background-color: var(--surface-card)"],
    ["text-text-secondary", "color: var(--color-text-secondary)"],
    ["font-ui", "font-family: var(--font-ui)"],
    ["font-mono", "font-family: var(--font-mono)"],
    ["rounded-card", "border-radius: var(--radius-card)"],
    ["w-size-sidebar-width", "width: var(--size-sidebar-width)"],
    ["h-size-topbar-height", "height: var(--size-topbar-height)"],
    ["p-space-16", "padding: var(--space-16)"],
    ["gap-layout-gap", "gap: var(--layout-gap)"],
    ["w-layout-event-manager", "width: var(--layout-event-manager)"],
    ["opacity-badge-fill", "opacity: var(--opacity-badge-fill)"],
    ["duration-motion", "transition-duration: var(--motion-duration)"],
    ["ease-motion", "transition-timing-function: var(--motion-easing)"],
    ["transition-base", "transition: var(--transition-base)"],
    ["stroke-size-icon-stroke", "stroke-width: var(--size-icon-stroke)"],
  ])("%s → %s", async (className, declaration) => {
    expect(await compile(className)).toContain(declaration);
  });

  it("la cornice SCENARIO: lo spessore ha il suffisso -width, il colore no (nessuna classe ambigua)", async () => {
    const width = await compile("border-scenario-frame-width");
    expect(width).toContain("border-width: var(--border-scenario-frame)");
    expect(width).not.toContain("border-color");
    const color = await compile("border-scenario-frame");
    expect(color).toContain("border-color: var(--color-scenario-frame)");
    expect(color).not.toContain("border-width");
  });

  it("i corpi del testo portano interlinea, peso e spaziatura del designer", async () => {
    expect(await compile("text-kpi")).toContain(
      "font-size: var(--fs-kpi); line-height: var(--lh-kpi); letter-spacing: var(--ls-kpi); font-weight: var(--fw-kpi)",
    );
    // `text-xs` non è più i 12 px di Tailwind: è il corpo minimo del designer (14 px)
    expect(await compile("text-xs")).toContain("font-size: var(--fs-xs)");
  });

  it("sotto i 1440 px c'è il layout compatto (`max-compact:`), da 1440 `compact:`", async () => {
    expect(await compile("compact:w-full")).toContain("@media (min-width: 1440px)");
    expect(await compile("max-compact:w-full")).toMatch(
      /@media not all and \(min-width: 1440px\)|@media \(max-width: 1439/,
    );
  });

  it("la palette di Tailwind non esiste: restano i token, il trasparente e poco altro (F4-REF)", async () => {
    for (const name of [
      "bg-white",
      "text-red-500",
      "border-gray-300",
      "bg-black",
      "text-slate-400",
    ]) {
      expect(await compile(name), name).not.toContain("color");
    }
    expect(await compile("bg-transparent")).toContain("background-color: transparent");
    expect(await compile("border-transparent")).toContain("border-color: transparent");
    expect(await compile("text-current")).toContain("color: currentColor");
    // le sole voci oltre ai token: il trasparente e simili, e il grigio che legge il segnaposto del reset
    const colors = (tailwindConfig.theme as { colors: Record<string, unknown> }).colors;
    const extra = Object.keys(colors).filter((name) => !(name in (tokenTheme.colors ?? {})));
    expect(extra.sort()).toEqual(["current", "gray", "inherit", "transparent"]);
    expect(colors.gray).toEqual({ 400: "var(--color-text-secondary)" });
  });
});

describe("riga di comando", () => {
  const dirs: string[] = [];
  afterEach(() => {
    vi.restoreAllMocks();
    for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
  });

  function workspace(content: DesignTokens | string = tokens()) {
    const dir = mkdtempSync(path.join(tmpdir(), "tokens-"));
    dirs.push(dir);
    const file = path.join(dir, "tokens.json");
    writeFileSync(file, typeof content === "string" ? content : JSON.stringify(content));
    return {
      tokens: file,
      outputs: { css: path.join(dir, "tokens.css"), theme: path.join(dir, "theme.ts") },
    };
  }
  const read = (file: string) => readFileSync(file, "utf8");

  it("senza --check scrive i due file", () => {
    const paths = workspace();
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    expect(main([], paths)).toBe(0);
    expect(log).toHaveBeenCalledWith("Token: file generati scritti");
    const generated = generate(tokens());
    expect(read(paths.outputs.css)).toBe(generated.css);
    expect(read(paths.outputs.theme)).toBe(generated.theme);
  });

  it("--check non scrive niente: i file mancanti sono «non aggiornati»", () => {
    const paths = workspace();
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(main(["--check"], paths)).toBe(1);
    expect(error).toHaveBeenCalledWith(
      "Non aggiornati: tokens.css, theme.ts. Esegui `npm run tokens`.",
    );
    expect(staleOutputs(generate(tokens()), paths.outputs)).toEqual(["css", "theme"]);
  });

  it("--check con i file aggiornati esce con 0; con uno solo indietro lo nomina", () => {
    const paths = workspace();
    vi.spyOn(console, "log").mockImplementation(() => undefined);
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    main([], paths);
    expect(main(["--check"], paths)).toBe(0);
    writeFileSync(paths.outputs.theme, "export const x = 1;\n");
    expect(main(["--check"], paths)).toBe(1);
    expect(error).toHaveBeenCalledWith("Non aggiornati: theme.ts. Esegui `npm run tokens`.");
    expect(read(paths.outputs.theme)).toBe("export const x = 1;\n");
  });

  it("riscrive solo ciò che è cambiato", () => {
    const paths = workspace();
    vi.spyOn(console, "log").mockImplementation(() => undefined);
    main([], paths);
    writeFileSync(paths.outputs.css, "/* a mano */");
    main([], paths);
    expect(read(paths.outputs.css)).toBe(generate(tokens()).css);
  });

  it("un errore nei token esce con 1, scrive il messaggio e nessun file", () => {
    const paths = workspace(tokens({ shadow: { "shadow-card": "0" } }));
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(main([], paths)).toBe(1);
    expect(error).toHaveBeenCalledWith(
      expect.stringMatching(/^Errore: famiglia di token sconosciuta «shadow»/),
    );
    expect(staleOutputs(generate(tokens()), paths.outputs)).toEqual(["css", "theme"]);
  });

  it("un tokens.json illeggibile esce con 1", () => {
    const paths = workspace("{ non è json");
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(main(["--check"], paths)).toBe(1);
    expect(error).toHaveBeenCalledWith(expect.stringMatching(/^Errore: /));
  });
});
