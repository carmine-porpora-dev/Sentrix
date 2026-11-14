/// <reference lib="dom" />
import { expect, test as base, type Page, type TestInfo } from "@playwright/test";
import { bar, shot as sharedShot } from "../e2e/support.ts";

export { expect } from "@playwright/test";
export {
  bar,
  expectOnlyTokenColors,
  expectWithin,
  mapRegion,
  metrics,
  settleMap,
} from "../e2e/support.ts";

/** `page` che fallisce se la pagina scrive errori in console, lancia eccezioni o riceve una risposta
 * 4xx/5xx (da qualunque indirizzo dell'applicazione). Un test che *provoca* un errore lo dichiara con
 * `allowedProblems` (un'espressione sul testo «HTTP 404 GET /percorso»). Nei percorsi normali non ce
 * ne sono: nemmeno la 404 di un'iterazione non ancora calcolata, che l'interfaccia non chiede (F7-02). */
export const test = base.extend<{ problems: string[]; allowedProblems: RegExp[] }>({
  allowedProblems: [[], { option: false }],
  problems: [
    async ({ page, allowedProblems }, use) => {
      const problems: string[] = [];
      page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
      page.on("response", (response) => {
        if (response.status() < 400) return;
        const { pathname, search } = new URL(response.url());
        problems.push(
          `HTTP ${response.status()} ${response.request().method()} ${pathname}${search}`,
        );
      });
      page.on("console", (message) => {
        if (message.type() !== "error") return;
        // «Failed to load resource» è il riflesso in console della risposta già annotata sopra
        if (message.text().startsWith("Failed to load resource")) return;
        problems.push(`console.error: ${message.text()}`);
      });
      await use(problems);
      const unexpected = problems.filter(
        (problem) => !allowedProblems.some((ok) => ok.test(problem)),
      );
      expect(unexpected, "problemi della pagina").toEqual([]);
    },
    { auto: true },
  ],
});

/** Una schermata per il report del cancello: `e2e/screenshots/real/<risoluzione>/<nome>.png`. */
export const shot = (page: Page, testInfo: TestInfo, name: string): Promise<void> =>
  sharedShot(page, testInfo, name, "real");

/** Accede con la password del lancio (`playwright.real.config.ts`). */
export async function login(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByLabel("Password").fill(process.env.E2E_PASSWORD ?? "");
  await page.getByRole("button", { name: "Accedi" }).click();
  await expect(page.getByRole("button", { name: "Analizza" })).toBeVisible();
}

/** Aspetta che il run sia arrivato in fondo: «Completato» o «Errore» nella barra superiore. */
export async function waitForRunEnd(
  page: Page,
  end: "Completato" | "Errore" = "Completato",
): Promise<void> {
  await expect(bar(page).getByText(end, { exact: true })).toBeVisible({ timeout: 150_000 });
}

/** Ciò che serve di `GET /api/runs/{id}` (i test confrontano l'interfaccia con l'API, non con numeri scritti a mano). */
export interface RunSummary {
  run: { id: string; state: string; iteration: number; replans: number; error: string | null };
  plan: { status: string }[];
  requests: {
    request: {
      action_id: string;
      state: string;
      reject_code?: string | null;
      alternative_of?: string | null;
    };
  }[];
}

interface MetricsBody {
  metrics: { id: string; value: number; unit: string; kind: string }[];
}

/** L'ultimo run dell'evento, com'è nell'API (la sessione è quella della pagina). */
export async function latestRunId(page: Page, eventId: string): Promise<string> {
  const response = await page.request.get(`/api/runs?event_id=${eventId}`);
  expect(response.ok(), "elenco dei run").toBeTruthy();
  const runs = (await response.json()) as { id: string }[];
  const first = runs[0];
  if (!first) throw new Error(`nessun run per ${eventId}`);
  return first.id;
}

interface NotificationSummary {
  state: string;
  simulation: boolean;
  recipient_id: string;
}

/** Le notifiche in uscita del run (spech 12), dall'API: attendono che ci siano (partono dopo `DONE`). */
export async function notifications(
  page: Page,
  runId: string,
  channel: "whatsapp" | "emergency_bulletin",
): Promise<NotificationSummary[]> {
  let rows: NotificationSummary[] = [];
  await expect
    .poll(
      async () => {
        const response = await page.request.get(
          `/api/runs/${runId}/notifications?channel=${channel}`,
        );
        expect(response.ok(), "notifiche del run").toBeTruthy();
        rows = (await response.json()) as NotificationSummary[];
        return rows.length;
      },
      { message: `notifiche ${channel}`, timeout: 30_000 },
    )
    .toBeGreaterThan(0);
  return rows;
}

export async function runView(page: Page, runId: string): Promise<RunSummary> {
  const response = await page.request.get(`/api/runs/${runId}`);
  expect(response.ok(), "stato del run").toBeTruthy();
  return (await response.json()) as RunSummary;
}

/** Il valore di una metrica del motore (`road.departure.veh_hours`…) a un'iterazione, dall'API. */
export async function metricValue(
  page: Page,
  runId: string,
  iteration: number,
  name: string,
): Promise<number> {
  const response = await page.request.get(`/api/runs/${runId}/metrics?iteration=${iteration}`);
  expect(response.ok(), `metriche dell'iterazione ${iteration}`).toBeTruthy();
  const body = (await response.json()) as MetricsBody;
  const found = body.metrics.find((m) => m.id === `m.${runId}.it${iteration}.${name}`);
  if (!found) throw new Error(`metrica ${name} assente all'iterazione ${iteration}`);
  return found.value;
}

/** Un numero come lo scrive l'interfaccia: intero, con il punto delle migliaia anche da quattro cifre
 * (l'italiano di `Intl` lo mette solo da cinque). */
export const whole = (value: number): string =>
  value.toLocaleString("it-IT", { maximumFractionDigits: 0, useGrouping: "always" });

/** L'effetto locale di una misura stradale (02 7), com'è nell'API: il massimo v/c sugli archi che tocca. */
export interface LocalEffect {
  actionId: string;
  before: number;
  after: number;
}

/** Tutti gli effetti locali del run, dalle metriche di ogni iterazione. */
export async function localEffects(
  page: Page,
  runId: string,
  iterations: number,
): Promise<LocalEffect[]> {
  const found = new Map<string, Partial<LocalEffect>>();
  for (let iteration = 0; iteration <= iterations; iteration++) {
    const response = await page.request.get(`/api/runs/${runId}/metrics?iteration=${iteration}`);
    expect(response.ok(), `metriche dell'iterazione ${iteration}`).toBeTruthy();
    const body = (await response.json()) as MetricsBody;
    for (const metric of body.metrics) {
      const match = /\.measure_effect\.([^.]+)\.vc_(before|after)$/.exec(metric.id);
      if (!match) continue;
      const [, actionId = "", half = ""] = match;
      found.set(actionId, { ...found.get(actionId), actionId, [half]: metric.value });
    }
  }
  return [...found.values()].filter(
    (e): e is LocalEffect => e.before !== undefined && e.after !== undefined,
  );
}
