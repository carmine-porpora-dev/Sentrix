/// <reference lib="dom" />
// (la funzione che gira nella pagina, `expectOnlyTokenColors`, usa le API del browser)
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { expect, test as base, type Locator, type Page, type TestInfo } from "@playwright/test";
import { readTokens } from "../scripts/tokens-to-tailwind.ts";

/** Il file PMTiles che il backend serve in produzione (`/tiles/napoli.pmtiles`, dietro la sessione). */
const TILES_FILE = path.resolve(import.meta.dirname, "../../data/tiles/napoli.pmtiles");
const SCREENSHOTS = path.resolve(import.meta.dirname, "screenshots");

/** Serve i tile dal file locale con le richieste a intervallo (`Range`) che pmtiles usa: i test e2e
 * non hanno il backend. Senza il file i test non hanno senso (mappa vuota): si ferma subito. */
async function serveTiles(page: Page): Promise<void> {
  if (!existsSync(TILES_FILE)) {
    throw new Error(
      `Manca ${TILES_FILE}: la base map dei test e2e. Si crea con lo script dati (F0-04).`,
    );
  }
  const bytes = readFileSync(TILES_FILE);
  await page.route("**/tiles/napoli.pmtiles", async (route) => {
    const range = /^bytes=(\d+)-(\d*)$/.exec(route.request().headers().range ?? "");
    if (!range) {
      await route.fulfill({
        status: 200,
        body: bytes,
        headers: { "accept-ranges": "bytes", "content-type": "application/octet-stream" },
      });
      return;
    }
    const start = Number(range[1]);
    const end = Math.min(range[2] ? Number(range[2]) : bytes.length - 1, bytes.length - 1);
    await route.fulfill({
      status: 206,
      body: bytes.subarray(start, end + 1),
      headers: {
        "accept-ranges": "bytes",
        "content-type": "application/octet-stream",
        "content-range": `bytes ${start}-${end}/${bytes.length}`,
      },
    });
  });
}

/** `page` con i tile locali, e un test che fallisce se la pagina scrive errori in console o lancia
 * eccezioni (un errore silenzioso dell'interfaccia non deve passare per un test verde). */
export const test = base.extend<{ errors: string[] }>({
  errors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(`console.error: ${message.text()}`);
      });
      await serveTiles(page);
      await use(errors);
      expect(errors, "errori della pagina").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

/** Le tre regioni che quasi ogni prova guarda: la barra in alto, la fascia delle metriche, la mappa. */
export const bar = (page: Page) => page.getByRole("banner");
export const metrics = (page: Page) => page.getByRole("region", { name: "Metriche" });
export const mapRegion = (page: Page) => page.getByRole("region", { name: "Mappa" });

/** La mappa carica i tile e disegna: non c'è un segnale da attendere, e uno screenshot a metà
 * disegno non dice nulla. Solo per gli screenshot (mai dentro un'asserzione). */
export async function settleMap(page: Page): Promise<void> {
  await expect(page.getByText("Caricamento della mappa…")).toHaveCount(0);
  await expect(mapRegion(page).locator("canvas.maplibregl-canvas")).toBeVisible();
  await page.waitForTimeout(1500);
}

/** Una schermata per il report del cancello: `e2e/screenshots/<sottocartella>/<risoluzione>/<nome>.png`
 * (la sottocartella separa le prove sul backend vero, `real`, da quelle sul mock). */
export async function shot(
  page: Page,
  testInfo: TestInfo,
  name: string,
  subfolder = "",
): Promise<void> {
  const dir = path.join(SCREENSHOTS, subfolder, testInfo.project.name);
  mkdirSync(dir, { recursive: true });
  await page.screenshot({ path: path.join(dir, `${name}.png`) });
}

/** Accede con una password qualsiasi (il mock accetta ogni password non vuota). */
export async function login(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByLabel("Password").fill("e2e");
  await page.getByRole("button", { name: "Accedi" }).click();
  await expect(page.getByRole("button", { name: "Analizza" })).toBeVisible();
}

/** Aspetta che il run del mock sia arrivato in fondo alla sua sequenza. Il run avanza di un fotogramma
 * a ogni lettura (1 s): il chip nella barra superiore dice «Completato». */
export async function waitForRunDone(page: Page): Promise<void> {
  await expect(page.getByRole("banner").getByText("Completato", { exact: true })).toBeVisible({
    timeout: 40_000,
  });
}

/** `inner` sta tutto dentro `outer`: un controllo tagliato dal bordo (succede alle risoluzioni
 * piccole, quando un pannello si restringe) è un difetto che un test sul solo testo non vede. */
export async function expectWithin(inner: Locator, outer: Locator, what: string): Promise<void> {
  const [a, b] = await Promise.all([inner.boundingBox(), outer.boundingBox()]);
  if (!a || !b) throw new Error(`${what}: non ha dimensioni (non è visibile?)`);
  const slack = 1; // arrotondamenti dei pixel
  expect(a.x, `${what}: sfora a sinistra`).toBeGreaterThanOrEqual(b.x - slack);
  expect(a.y, `${what}: sfora in alto`).toBeGreaterThanOrEqual(b.y - slack);
  expect(a.x + a.width, `${what}: sfora a destra`).toBeLessThanOrEqual(b.x + b.width + slack);
  expect(a.y + a.height, `${what}: sfora in basso`).toBeLessThanOrEqual(b.y + b.height + slack);
}

type Rgba = [number, number, number, number];

/** Un colore scritto come `#rgb(a)`, `#rrggbb(aa)`, `rgb()` o `rgba()` (virgole o spazi), come [r, g, b, a]. */
function parseColor(text: string): Rgba | undefined {
  const value = text.trim().toLowerCase();
  const hex = /^#([0-9a-f]{3,8})$/.exec(value)?.[1];
  if (hex && [3, 4, 6, 8].includes(hex.length)) {
    const full = hex.length <= 4 ? [...hex].map((c) => c + c).join("") : hex;
    const byte = (i: number) => Number.parseInt(full.slice(i, i + 2), 16);
    return [byte(0), byte(2), byte(4), full.length === 8 ? byte(6) / 255 : 1];
  }
  const fn = /^rgba?\(([^)]*)\)$/.exec(value)?.[1];
  if (!fn) return undefined;
  const parts = fn
    .split(/[\s,/]+/)
    .filter(Boolean)
    .map(Number);
  if (parts.length < 3 || parts.some(Number.isNaN)) return undefined;
  return [parts[0] ?? 0, parts[1] ?? 0, parts[2] ?? 0, parts[3] ?? 1];
}

const sameColor = (a: Rgba, b: Rgba) =>
  a[0] === b[0] && a[1] === b[1] && a[2] === b[2] && Math.abs(a[3] - b[3]) < 0.01;

/** I colori del designer (`tokens.json`), più il trasparente. */
const TOKEN_COLORS: Rgba[] = [
  ...Object.values(readTokens().tokens.color ?? {})
    .map(parseColor)
    .filter((color): color is Rgba => color !== undefined),
  [0, 0, 0, 0],
];

/** Tutti i colori che il browser calcola per la pagina com'è adesso (testo, sfondo, bordi, contorno,
 * tratto e riempimento delle icone, ombre, segnaposto): ognuno deve essere un token (F4-REF). Guarda
 * i valori reali, quindi anche gli stili del browser e di MapLibre che nel sorgente non si leggono. */
export async function expectOnlyTokenColors(page: Page, when: string): Promise<void> {
  // Un colore a metà di una transizione (per esempio un pulsante di scheda appena cliccato) non è
  // un colore della pagina: si legge a transizioni finite. Le animazioni senza fine (un indicatore
  // di attesa) non si aspettano, non finirebbero mai.
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((animation) => animation.effect?.getComputedTiming().endTime !== Infinity)
        .map((animation) => animation.finished.catch(() => undefined)),
    ),
  );
  const used = await page.evaluate(() => {
    const properties = [
      "color",
      "backgroundColor",
      "borderTopColor",
      "borderRightColor",
      "borderBottomColor",
      "borderLeftColor",
      "outlineColor",
      "textDecorationColor",
      "caretColor",
      "fill",
      "stroke",
    ] as const;
    const found = new Map<string, string>();
    const note = (property: string, value: string, element: Element, pseudo = "") => {
      const colors =
        value.match(
          /rgba?\([^)]*\)|#[0-9a-fA-F]{3,8}\b|\b(?:hsla?|oklch|oklab|lab|lch|color|color-mix)\([^)]*\)/g,
        ) ?? [];
      for (const color of colors) {
        const key = `${property}${pseudo}: ${color}`;
        if (!found.has(key)) {
          const text = (element.textContent ?? "").trim().slice(0, 30);
          found.set(
            key,
            `<${element.tagName.toLowerCase()} class="${String(element.getAttribute("class") ?? "").slice(0, 50)}"> «${text}»`,
          );
        }
      }
    };
    for (const element of document.querySelectorAll("body, body *")) {
      const style = getComputedStyle(element);
      for (const property of properties) {
        // `fill` vale nero su ogni elemento HTML (è il valore iniziale), ma disegna solo negli SVG
        if ((property === "fill" || property === "stroke") && !(element instanceof SVGElement)) {
          continue;
        }
        note(property, style[property], element);
      }
      note("backgroundImage", style.backgroundImage, element);
      note("boxShadow", style.boxShadow, element);
      if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
        note("placeholder", getComputedStyle(element, "::placeholder").color, element);
      }
      if (element instanceof HTMLInputElement && element.type === "range") {
        // la traccia e il pollice del cursore sono parti dell'elemento (si leggono come pseudo-elementi)
        for (const part of ["::-webkit-slider-runnable-track", "::-webkit-slider-thumb"]) {
          const partStyle = getComputedStyle(element, part);
          note("backgroundColor", partStyle.backgroundColor, element, part);
          note("backgroundImage", partStyle.backgroundImage, element, part);
        }
      }
    }
    return [...found.entries()];
  });
  const outside = used.filter(([key]) => {
    const color = parseColor(key.slice(key.indexOf(": ") + 2));
    return !color || !TOKEN_COLORS.some((token) => sameColor(color, token));
  });
  expect(
    outside.map(([key, where]) => `${key}  ←  ${where}`),
    `colori che non sono dei token (${when})`,
  ).toEqual([]);
}
