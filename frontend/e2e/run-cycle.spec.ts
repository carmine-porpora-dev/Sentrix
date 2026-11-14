import { readFile } from "node:fs/promises";
import {
  expect,
  expectOnlyTokenColors,
  expectWithin,
  login,
  mapRegion,
  metrics,
  settleMap,
  shot,
  test,
  waitForRunDone,
} from "./support.ts";

// Il ciclo centrale del prodotto (07 9): evento → Analizza → piano → richieste → rifiuto →
// ripianificazione → nuova simulazione → confronto tra iterazioni → esportazione.

test("dal login all'esportazione: rifiuto, ripianificazione, Prima/Dopo, iterazioni", async ({
  page,
}, testInfo) => {
  await login(page);

  // L'evento seed è già scelto: l'evento è un dato precaricato, con il suo badge.
  const picker = page.getByLabel("Evento", { exact: true });
  await expect(picker).toHaveValue("match_2027");
  await expect(page.getByText("preset", { exact: true })).toBeVisible();
  // Prima dell'analisi le metriche non hanno numeri: nessun valore inventato.
  await expect(metrics(page).getByText("Nessuna analisi")).toHaveCount(5);
  await settleMap(page);
  await shot(page, testInfo, "02-evento-seed");

  // --- Analizza: il run parte, l'Event Manager si comprime, lo stato avanza.
  await page.getByRole("button", { name: "Analizza" }).click();
  await expect(page.locator("[data-layout='rail']")).toBeVisible();
  await expect(page.getByRole("banner").getByText(/Iterazione \d di 3/)).toBeVisible();
  await expect(page.getByRole("banner").getByText("Completato", { exact: true })).toHaveCount(0);
  await shot(page, testInfo, "03-run-in-corso");

  await waitForRunDone(page);
  await expect(page.getByRole("banner").getByText("Iterazione 3 di 3")).toBeVisible();

  // --- Agenti: i quattro agenti hanno finito.
  const agents = page.getByRole("tabpanel");
  for (const name of [
    "Event & Demand Agent",
    "Traffic Agent",
    "Transit Agent",
    "Operations Agent",
  ]) {
    await expect(agents.getByText(name)).toBeVisible();
  }
  await settleMap(page);
  await shot(page, testInfo, "04-run-completato-agenti");
  await expectOnlyTokenColors(page, "agenti, run completato");

  // I controlli della mappa stanno dentro la mappa, anche a 1366 px (con il run l'Event Manager si
  // comprime e la mappa si restringe): legenda, attribuzione, Prima/Dopo, iterazioni, livelli.
  const map = mapRegion(page);
  await expectWithin(map.getByRole("group", { name: "Legenda della congestione" }), map, "legenda");
  await expectWithin(map.getByRole("link", { name: /OpenStreetMap/ }), map, "attribuzione");
  await expectWithin(map.getByRole("switch", { name: "Prima / Dopo" }), map, "Prima/Dopo");
  await expectWithin(
    map.getByRole("button", { name: "Iterazione successiva" }),
    map,
    "iterazione successiva",
  );
  await expectWithin(map.getByRole("button", { name: "Livelli mappa" }), map, "livelli mappa");

  // --- Operations: il rifiuto si vede, con il codice e il motivo, e l'alternativa che ne è nata.
  await page.getByRole("tab", { name: "Operations" }).click();
  const rejected = page.getByRole("article", { name: "act_002" });
  await expect(rejected.getByText("Rifiutata", { exact: true })).toBeVisible();
  await expect(rejected.getByText("UNAVAILABLE")).toBeVisible();
  await expect(rejected.getByText(/Pattuglie esaurite/)).toBeVisible();
  await expect(page.getByRole("button", { name: "1 alternativa" })).toBeVisible();
  const alternative = page.getByRole("article", { name: "act_004" });
  await expect(alternative.getByText("Alternativa a act_002")).toBeVisible();
  await expect(alternative.getByText("Accettata", { exact: true })).toBeVisible();
  // La misura rifiutata, nel piano, risulta sostituita da quella nuova.
  await expect(page.getByText("Sostituita dalla misura 4")).toBeVisible();
  await rejected.scrollIntoViewIfNeeded();
  await shot(page, testInfo, "05-operations-rifiuto");
  await expectOnlyTokenColors(page, "operations con il rifiuto");

  // Il tooltip di provenienza (design, schermata 12): bordo e sfondo del design, niente ombra, e colori dei token.
  await metrics(page).locator("[data-measured]:visible").first().hover();
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toHaveCSS("box-shadow", "none");
  await expectOnlyTokenColors(page, "tooltip di provenienza");
  await shot(page, testInfo, "18-tooltip-provenienza");
  await page.mouse.move(0, 0);
  await expect(tooltip).toHaveCount(0);

  // --- Prima / Dopo e iterazioni. Si parte da «Dopo», ultima iterazione: tre archi critici
  // (da sei), 4.690 ore-veicolo (da 4.820).
  const afterLast = metrics(page);
  await expect(afterLast).toContainText("4.820");
  await expect(afterLast).toContainText("4.690");
  await expect(afterLast).toContainText("−130");
  await expect(mapRegion(page).getByText("Iterazione 3", { exact: true })).toBeVisible();

  // Iterazione precedente: la ripianificazione non c'è ancora, il miglioramento è minore.
  await mapRegion(page).getByRole("button", { name: "Iterazione precedente" }).click();
  await expect(mapRegion(page).getByText("Iterazione 2", { exact: true })).toBeVisible();
  await expect(metrics(page)).toContainText("4.760");
  await expect(metrics(page)).not.toContainText("4.690");
  await expect(metrics(page)).toContainText("−60");
  await settleMap(page);
  await shot(page, testInfo, "06-iterazione-2");

  // Prima: solo la situazione di partenza, senza variazioni.
  const beforeAfter = mapRegion(page).getByRole("switch", { name: "Prima / Dopo" });
  await expect(beforeAfter).toHaveAttribute("aria-checked", "true");
  await beforeAfter.click();
  await expect(beforeAfter).toHaveAttribute("aria-checked", "false");
  await expect(metrics(page)).toContainText("4.820");
  await expect(metrics(page)).not.toContainText("4.760");
  await expect(metrics(page)).not.toContainText("−");
  await settleMap(page);
  await shot(page, testInfo, "07-prima");

  // Di nuovo «Dopo»: resta l'iterazione scelta (la 2), non salta all'ultima.
  await beforeAfter.click();
  await expect(beforeAfter).toHaveAttribute("aria-checked", "true");
  await expect(metrics(page)).toContainText("4.760");

  // Il confronto tra iterazioni (Operations) mette le colonne una accanto all'altra.
  const comparison = page.getByRole("table");
  await expect(comparison.getByRole("columnheader", { name: "Prima" })).toBeVisible();
  await expect(comparison.getByRole("columnheader", { name: "Iterazione 2" })).toBeVisible();
  await expect(comparison.getByRole("columnheader", { name: "Iterazione 3" })).toBeVisible();
  const hours = comparison.getByRole("row", { name: /Ore-veicolo/ });
  await expect(hours).toContainText("4.820");
  await expect(hours).toContainText("4.760");
  await expect(hours).toContainText("4.690");
  await page
    .getByText("Confronto iterazioni")
    .evaluate((el) => el.scrollIntoView({ block: "start" }));
  await shot(page, testInfo, "08-confronto-iterazioni");

  // --- Decisioni: il registro e le tre esportazioni.
  await page.getByRole("tab", { name: "Decisioni" }).click();
  await expect(page.getByText("Registro decisioni")).toBeVisible();
  await shot(page, testInfo, "09-decisioni");
  await expectOnlyTokenColors(page, "registro decisioni");

  const exported = async (label: string) => {
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: label }).click(),
    ]);
    const path = await download.path();
    return { name: download.suggestedFilename(), text: await readFile(path, "utf8") };
  };

  const json = await exported("Esporta JSON");
  expect(json.name).toMatch(/\.json$/);
  const document = JSON.parse(json.text) as { run: { id: string; state: string } };
  expect(document.run).toMatchObject({ id: "run_mock_match_2027", state: "DONE" });

  const metricsCsv = await exported("CSV metriche");
  expect(metricsCsv.name).toMatch(/\.csv$/);
  expect(metricsCsv.text.split("\n")[0]).toContain("id");
  expect(metricsCsv.text).toContain("road.departure.veh_hours");

  const edgesCsv = await exported("CSV archi critici");
  expect(edgesCsv.name).toMatch(/\.csv$/);
  expect(edgesCsv.text.split("\n").length).toBeGreaterThan(1);
});
