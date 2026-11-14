import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { DesignTokens, Dict, TailwindTokens, TokenTheme } from "../src/styles/token-types.ts";

export class TokenError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TokenError";
  }
}

/** La famiglia di ogni token deve esistere qui: se tokens.json ne ha una nuova lo script si ferma. */
const FAMILIES = [
  "color",
  "surface",
  "text",
  "action",
  "focus",
  "font",
  "fs",
  "lh",
  "fw",
  "ls",
  "space",
  "radius",
  "border",
  "size",
  "layout",
  "breakpoint",
  "opacity",
  "motion",
  "transition",
] as const;

/** Famiglie i cui nomi sono quelli semantici interi (non hanno un prefisso da togliere). */
const SEMANTIC_COLOR_FAMILIES = ["surface", "text", "action", "focus"] as const;

function family(tokens: DesignTokens, name: string): Dict {
  return tokens.tokens[name] ?? {};
}

/** Il token deve cominciare per il prefisso della sua famiglia (e avere altro dopo). */
function assertPrefix(key: string, prefix: string, where: string): void {
  if (!key.startsWith(prefix) || key.length === prefix.length) {
    throw new TokenError(`${where}: il token «${key}» non comincia per «${prefix}»`);
  }
}

/** Il nome del token senza il prefisso della famiglia (`color-bg` → `bg`). */
function strip(key: string, prefix: string, where: string): string {
  assertPrefix(key, prefix, where);
  return key.slice(prefix.length);
}

function put(target: Dict, key: string, value: string, where: string): void {
  if (key in target) throw new TokenError(`${where}: due token finiscono su «${key}»`);
  target[key] = value;
}

const cssVar = (key: string) => `var(--${key})`;

function validate(tokens: DesignTokens): void {
  for (const [name, entries] of Object.entries(tokens.tokens)) {
    if (!(FAMILIES as readonly string[]).includes(name)) {
      throw new TokenError(
        `famiglia di token sconosciuta «${name}»: va gestita in scripts/tokens-to-tailwind.ts`,
      );
    }
    for (const [key, value] of Object.entries(entries)) {
      if (typeof value !== "string" || value.trim() === "") {
        throw new TokenError(`${name}.${key}: il valore deve essere un testo non vuoto`);
      }
    }
  }
}

/** Le variabili CSS: `:root { --<token>: <valore>; }` nell'ordine di tokens.json. */
export function tokensToCss(tokens: DesignTokens): string {
  validate(tokens);
  const lines = [":root {"];
  for (const [name, entries] of Object.entries(tokens.tokens)) {
    lines.push(`  /* ${name} */`);
    for (const [key, value] of Object.entries(entries)) lines.push(`  --${key}: ${value};`);
  }
  lines.push("}", "");
  return lines.join("\n");
}

/** Il tema Tailwind (`theme.extend`) e le utility che i token chiedono. */
export function tokensToTheme(tokens: DesignTokens): TailwindTokens {
  validate(tokens);
  const theme: TokenTheme = {
    colors: {},
    fontFamily: {},
    fontSize: {},
    spacing: {},
    strokeWidth: {},
    borderRadius: {},
    borderWidth: {},
    opacity: {},
    transitionDuration: {},
    transitionTimingFunction: {},
    screens: {},
  };
  const utilities: TailwindTokens["utilities"] = {};

  for (const key of Object.keys(family(tokens, "color"))) {
    put(theme.colors, strip(key, "color-", "color"), cssVar(key), "colori");
  }
  for (const name of SEMANTIC_COLOR_FAMILIES) {
    for (const key of Object.keys(family(tokens, name))) {
      if (key !== name && !key.startsWith(`${name}-`)) {
        throw new TokenError(`${name}: il token «${key}» non comincia per «${name}»`);
      }
      put(theme.colors, key, cssVar(key), "colori");
    }
  }

  for (const key of Object.keys(family(tokens, "font"))) {
    put(theme.fontFamily, strip(key, "font-", "font"), cssVar(key), "font");
  }

  // corpo, interlinea, peso e spaziatura delle lettere vanno insieme: `text-xl`
  const sizes = Object.keys(family(tokens, "fs")).map((key) => strip(key, "fs-", "fs"));
  for (const companion of ["lh", "fw", "ls"] as const) {
    const names = Object.keys(family(tokens, companion)).map((key) =>
      strip(key, `${companion}-`, companion),
    );
    const missing = sizes.filter((size) => !names.includes(size));
    const extra = names.filter((name) => !sizes.includes(name));
    if (missing.length > 0 || extra.length > 0) {
      throw new TokenError(
        `${companion}: non corrisponde a fs (mancano ${missing.join(", ") || "-"}; in più ${extra.join(", ") || "-"})`,
      );
    }
  }
  for (const size of sizes) {
    theme.fontSize[size] = [
      cssVar(`fs-${size}`),
      {
        lineHeight: cssVar(`lh-${size}`),
        fontWeight: cssVar(`fw-${size}`),
        letterSpacing: cssVar(`ls-${size}`),
      },
    ];
  }

  for (const name of ["space", "layout"] as const) {
    for (const key of Object.keys(family(tokens, name))) {
      assertPrefix(key, `${name}-`, name);
      put(theme.spacing, key, cssVar(key), "misure");
    }
  }
  for (const [key, value] of Object.entries(family(tokens, "size"))) {
    assertPrefix(key, "size-", "size");
    // un numero senza unità (lo spessore del tratto delle icone) non è una misura
    if (/^\d+(\.\d+)?$/.test(value)) put(theme.strokeWidth, key, cssVar(key), "spessori");
    else put(theme.spacing, key, cssVar(key), "misure");
  }

  for (const key of Object.keys(family(tokens, "radius"))) {
    put(theme.borderRadius, strip(key, "radius-", "radius"), cssVar(key), "angoli");
  }
  for (const key of Object.keys(family(tokens, "border"))) {
    // `border-scenario-frame` sarebbe sia lo spessore sia il colore della cornice: una classe
    // ambigua. Lo spessore prende il suffisso `-width` quando il nome è anche un colore.
    const name = strip(key, "border-", "border");
    const clash = name in theme.colors;
    put(theme.borderWidth, clash ? `${name}-width` : name, cssVar(key), "bordi");
  }
  for (const key of Object.keys(family(tokens, "opacity"))) {
    put(theme.opacity, strip(key, "opacity-", "opacity"), cssVar(key), "opacità");
  }
  for (const key of Object.keys(family(tokens, "breakpoint"))) {
    // il valore, non la variabile: i breakpoint di Tailwind non possono essere `var()`
    const value = family(tokens, "breakpoint")[key] as string;
    put(theme.screens, strip(key, "breakpoint-", "breakpoint"), value, "schermi");
  }

  for (const key of Object.keys(family(tokens, "motion"))) {
    if (key === "motion-duration") {
      put(theme.transitionDuration, "motion", cssVar(key), "movimento");
    } else if (key === "motion-easing") {
      put(theme.transitionTimingFunction, "motion", cssVar(key), "movimento");
    } else {
      throw new TokenError(
        `motion: token «${key}» non gestito (solo motion-duration e motion-easing)`,
      );
    }
  }
  for (const key of Object.keys(family(tokens, "transition"))) {
    // è la scorciatoia `transition` intera (proprietà, durata e curva): una utility, non un valore
    assertPrefix(key, "transition-", "transition");
    utilities[`.${key}`] = { transition: cssVar(key) };
  }

  return { extend: theme, utilities };
}

export function tokensToThemeModule(tokens: DesignTokens): string {
  const { extend, utilities } = tokensToTheme(tokens);
  return `import type { TailwindTokens } from "./token-types.ts";

export const tokenTheme: TailwindTokens["extend"] = ${JSON.stringify(extend, null, 2)};

export const tokenUtilities: TailwindTokens["utilities"] = ${JSON.stringify(utilities, null, 2)};
`;
}

// --- riga di comando -------------------------------------------------------------------------

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const TOKENS_JSON = path.resolve(ROOT, "..", "design", "design-system", "tokens.json");
export const OUTPUTS = {
  css: path.join(ROOT, "src", "styles", "tokens.generated.css"),
  theme: path.join(ROOT, "src", "styles", "tailwind-theme.generated.ts"),
};

export interface Paths {
  tokens: string;
  outputs: typeof OUTPUTS;
}
const DEFAULT_PATHS: Paths = { tokens: TOKENS_JSON, outputs: OUTPUTS };

export function readTokens(file: string = TOKENS_JSON): DesignTokens {
  return JSON.parse(readFileSync(file, "utf8")) as DesignTokens;
}

export function generate(tokens: DesignTokens): Record<keyof typeof OUTPUTS, string> {
  return { css: tokensToCss(tokens), theme: tokensToThemeModule(tokens) };
}

/** I file generati che mancano o che non sono quelli che i token producono. */
export function staleOutputs(
  generated: Record<keyof typeof OUTPUTS, string>,
  outputs: typeof OUTPUTS = OUTPUTS,
): (keyof typeof OUTPUTS)[] {
  return (Object.keys(outputs) as (keyof typeof OUTPUTS)[]).filter((kind) => {
    try {
      return readFileSync(outputs[kind], "utf8") !== generated[kind];
    } catch {
      return true;
    }
  });
}

/** `--check` = solo verifica. Esce con 0 se va bene, 1 per un errore nei token o file non aggiornati. */
export function main(argv: string[], paths: Paths = DEFAULT_PATHS): number {
  const check = argv.includes("--check");
  let generated: Record<keyof typeof OUTPUTS, string>;
  try {
    generated = generate(readTokens(paths.tokens));
  } catch (error) {
    console.error(`Errore: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  }
  const stale = staleOutputs(generated, paths.outputs);
  if (check) {
    if (stale.length === 0) {
      console.log("Token: file generati aggiornati");
      return 0;
    }
    const files = stale.map((kind) => path.basename(paths.outputs[kind]));
    console.error(`Non aggiornati: ${files.join(", ")}. Esegui \`npm run tokens\`.`);
    return 1;
  }
  for (const kind of stale) writeFileSync(paths.outputs[kind], generated[kind]);
  console.log("Token: file generati scritti");
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
