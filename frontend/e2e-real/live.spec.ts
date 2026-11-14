import {
  bar,
  expect,
  expectOnlyTokenColors,
  expectWithin,
  login,
  mapRegion,
  metrics,
  shot,
  test,
  waitForRunEnd,
} from "./support.ts";

// F8-TEST: la vista LIVE sul backend vero, **senza rete e senza chiave TomTom** (08 7): l'ultimo dato
// noto viene dallo snapshot su disco (preparato da `backend.ts`) e LIVE lo dice: chip giallo, motivo,
// ora, «Dati parziali». I numeri sono quelli che il backend calcola dai tratti (`summary`). Nessuna
// chiamata a TomTom: non c'è la chiave, e il test lo verifica dallo stato del sistema.

interface Flow {
  mode: string;
  degraded_reason: string | null;
  segments: { id: string; label: string; congestion_class: number; fetched_at: string }[];
  summary: { id: string; value: number; kind: string }[];
}

const live = (page: import("@playwright/test").Page) => page.getByRole("radio", { name: /LIVE/ });

test("LIVE senza rete né chiave: ultimo dato noto, chip, numeri del backend, e il resto vive", async ({
  page,
}, testInfo) => {
  const flowRequests: Record<string, string>[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/live/flow") {
      flowRequests.push(request.headers());
    }
  });
  await login(page);

  // il sistema dice che la chiave TomTom non c'è: nessuna chiamata a TomTom è possibile
  const health = (await (await page.request.get("/api/health")).json()) as {
    data: { tomtom_key_present: boolean };
  };
  expect(health.data.tomtom_key_present).toBe(false);

  await live(page).click();
  await expect(live(page)).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("scenario-frame")).toHaveCount(0);
  await expect(bar(page).getByText("SIMULAZIONE", { exact: true })).toHaveCount(0);

  // la richiesta viene dalla vista LIVE (`X-View: live`), e ne parte una sola per tutta l'interfaccia
  await expect.poll(() => flowRequests.length).toBeGreaterThan(0);
  expect(flowRequests.every((headers) => headers["x-view"] === "live")).toBe(true);
  const fetched = flowRequests.length;
  expect(fetched).toBe(1);

  // lo snapshot: i tratti ci sono, con il motivo e l'ora
  const flow = (await (
    await page.request.get("/api/live/flow", { headers: { "x-view": "live" } })
  ).json()) as Flow;
  expect(flow.mode).toBe("snapshot");
  expect(flow.degraded_reason).toBe("tomtom_key_missing");
  expect(flow.segments).toHaveLength(14);
  expect(flow.summary.map((m) => m.id.split(".").pop())).toEqual([
    "mean_speed",
    "mean_ratio",
    "slowed_count",
    "slowest_speed",
    "covered_count",
  ]);

  // il chip «Fonte non disponibile: TomTom» e il suo popover (clic, Esc)
  const chip = bar(page).getByRole("button", { name: "Fonte non disponibile: TomTom" });
  await expect(chip).toBeVisible();
  // sta a destra, subito a sinistra del selettore (design 02), non accanto al nome del prodotto
  const chipBox = await chip.boundingBox();
  const selectorBox = await page.getByRole("radiogroup", { name: "Modalità" }).boundingBox();
  const titleBox = await bar(page).getByRole("heading", { level: 1 }).boundingBox();
  if (!chipBox || !selectorBox || !titleBox)
    throw new Error("chip, selettore o titolo senza riquadro");
  expect(chipBox.x).toBeGreaterThan(titleBox.x + titleBox.width);
  expect(chipBox.x + chipBox.width).toBeLessThanOrEqual(selectorBox.x);
  expect(selectorBox.x - (chipBox.x + chipBox.width)).toBeLessThan(40);
  await chip.click();
  const popover = page.getByRole("dialog", { name: "Fonte non disponibile: TomTom" });
  await expect(popover).toContainText("Non disponibile. Si usano gli ultimi dati noti.");
  await expect(popover).toContainText("Manca la chiave di TomTom.");
  await expect(popover).toContainText(/Ultimo dato alle \d{2}:\d{2}/);
  await shot(page, testInfo, "live-01-chip");
  await page.keyboard.press("Escape");
  await expect(popover).toHaveCount(0);

  // la fascia ha i numeri dei tratti (non quelli della simulazione), uguali a quelli dell'API
  const strip = metrics(page);
  for (const label of [
    "Velocità media",
    "Rispetto al flusso libero",
    "Tratti rallentati",
    "Tratto più lento",
    "Tratti con un dato",
  ]) {
    await expect(strip).toContainText(label);
  }
  await expect(strip).not.toContainText("Ore-veicolo");
  const mean = flow.summary.find((m) => m.id.endsWith("mean_speed"));
  await expect(strip).toContainText(
    (mean?.value ?? 0).toLocaleString("it-IT", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    }),
  );
  await expect(strip).toContainText("14"); // tratti con un dato
  await expect(strip.getByText("STIMA")).toHaveCount(4);
  await expect(strip.getByText("REALE")).toHaveCount(1);

  // entrando in LIVE la scheda attiva è Operations (design 01); con dati non aggiornati non dice
  // «nessuna criticità» ma «Dati parziali»
  await expect(page.getByRole("tab", { name: "Operations" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByText("Dati parziali")).toBeVisible();
  await expect(page.getByText("Nessuna criticità")).toHaveCount(0);

  // la mappa: la base, la legenda delle classi e, senza i controlli dell'analisi, il resto dell'interfaccia
  const map = mapRegion(page);
  await expect(map.locator("canvas.maplibregl-canvas")).toBeVisible();
  const legend = map.getByRole("group", { name: "Legenda della congestione" });
  await expect(legend).toBeVisible();
  await expectWithin(legend, map, "legenda");
  await expect(map.getByRole("button", { name: "Livelli mappa" })).toHaveCount(0);
  await page.waitForTimeout(2000); // solo per lo screenshot: i tratti e i tile finiscono di disegnarsi
  await shot(page, testInfo, "live-02-snapshot");
  await expectOnlyTokenColors(page, "LIVE con lo snapshot");

  // tornando a SCENARIO la vista è quella di sempre (e nessuna richiesta nuova a LIVE)
  await page.getByRole("radio", { name: /SCENARIO/ }).click();
  await expect(page.getByTestId("scenario-frame")).toBeAttached();
  await expect(metrics(page)).toContainText("Nessuna analisi");
  await expect(chip).toHaveCount(0);
  expect(flowRequests.length).toBe(fetched);
});

test("«Analizza» in LIVE porta a SCENARIO e il run si vede", async ({ page }, testInfo) => {
  await login(page);
  await live(page).click();
  await expect(page.getByTestId("scenario-frame")).toHaveCount(0);
  await page.getByRole("button", { name: "Analizza" }).click();
  // un run è una simulazione: la vista torna SCENARIO (cornice, banner) e i risultati sono lì
  await expect(page.getByRole("radio", { name: /SCENARIO/ })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await expect(page.getByTestId("scenario-frame")).toBeAttached();
  await expect(bar(page).getByText("SIMULAZIONE", { exact: true })).toBeVisible();
  await expect(metrics(page)).not.toContainText("Tratti rallentati");
  await waitForRunEnd(page);
  await expect(metrics(page)).toContainText("Ore-veicolo");
  await shot(page, testInfo, "live-03-analizza-da-live");
});

test("LIVE rilegge i tratti ogni minuto", async ({ page }, testInfo) => {
  // l'intervallo non dipende dalla risoluzione: una volta sola (il test dura più di un minuto)
  test.skip(testInfo.project.name !== "1920x1080", "una risoluzione basta");
  const reads: number[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/live/flow") reads.push(Date.now());
  });
  await login(page);
  await live(page).click();
  await expect.poll(() => reads.length).toBe(1);
  // la seconda lettura arriva da sola, dopo circa un minuto (60 s: `LIVE_POLL_MS`), una sola per tutti
  await expect.poll(() => reads.length, { timeout: 90_000, intervals: [2_000] }).toBe(2);
  const gap = ((reads[1] ?? 0) - (reads[0] ?? 0)) / 1000;
  expect(gap).toBeGreaterThan(55);
  expect(gap).toBeLessThan(75);
  // fuori da LIVE non si legge più: tornando a SCENARIO la lettura si ferma
  await page.getByRole("radio", { name: /SCENARIO/ }).click();
  await page.waitForTimeout(5_000);
  expect(reads.length).toBe(2);
});
