import {
  expect,
  expectOnlyTokenColors,
  login,
  settleMap,
  shot,
  test,
  waitForRunDone,
} from "./support.ts";

// LIVE e SCENARIO (07 2): in SCENARIO cornice, banner SIMULAZIONE e avviso; in LIVE spariscono, la
// fascia ha i numeri dei tratti TomTom e la mappa i tratti colorati per classe (F8-03): i risultati
// di una simulazione non si mescolano ai dati reali.

test("LIVE e SCENARIO: cornice, banner, avviso e livelli seguono la modalità", async ({
  page,
}, testInfo) => {
  await login(page);
  const live = page.getByRole("radio", { name: /LIVE/ });
  const scenario = page.getByRole("radio", { name: /SCENARIO/ });
  const frame = page.getByTestId("scenario-frame");
  const banner = page.getByRole("banner").getByText("SIMULAZIONE", { exact: true });
  const disclaimer = page.getByText(/Nessuna azione inviata a sistemi reali/);
  const map = page.getByRole("region", { name: "Mappa" });
  const legend = map.getByRole("group", { name: "Legenda della congestione" });
  const layers = map.getByRole("button", { name: "Livelli mappa" });

  // Si parte da SCENARIO (funziona offline, non chiama fonti esterne).
  await expect(scenario).toHaveAttribute("aria-checked", "true");
  await expect(live).toHaveAttribute("aria-checked", "false");
  await expect(frame).toBeAttached();
  await expect(banner).toBeVisible();
  await expect(disclaimer).toBeVisible();

  // Con un run finito, la mappa mostra i suoi livelli (legenda della congestione).
  await page.getByRole("button", { name: "Analizza" }).click();
  await waitForRunDone(page);
  await expect(legend).toBeVisible();
  await expect(layers).toBeVisible();
  await page.waitForTimeout(1500); // solo per lo screenshot: i tile finiscono di disegnarsi
  await shot(page, testInfo, "10-scenario");

  await live.click();
  await expect(live).toHaveAttribute("aria-checked", "true");
  await expect(scenario).toHaveAttribute("aria-checked", "false");
  await expect(frame).toHaveCount(0);
  await expect(banner).toHaveCount(0);
  await expect(disclaimer).toHaveCount(0);
  // In LIVE la mappa ha i tratti TomTom (la stessa legenda delle quattro classi) e non i controlli
  // dell'analisi; la fascia ha i numeri dei tratti, non quelli della simulazione.
  await expect(legend).toBeVisible();
  await expect(layers).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Metriche" })).toContainText("Velocità media");
  await expect(page.getByRole("region", { name: "Metriche" })).not.toContainText("Ore-veicolo");
  await expect(page.getByText("Nessuna azione inviata a sistemi reali")).toHaveCount(0);
  await expect(map.locator("canvas.maplibregl-canvas")).toBeVisible();
  await page.waitForTimeout(1500);
  await shot(page, testInfo, "11-live");
  await expectOnlyTokenColors(page, "modalità LIVE");

  // Tornando a SCENARIO il run è ancora lì.
  await scenario.click();
  await expect(frame).toBeAttached();
  await expect(banner).toBeVisible();
  await expect(legend).toBeVisible();
});

// «Sensori previsti» (spech 11.5): in LIVE la legenda ha un livello spento di default; acceso, i
// simboli grigi a contorno tratteggiato dicono che i sensori non sono ancora attivi (nessun dato); il
// riquadro «Fonti dati» della scheda Operations dice TomTom attivo (REALE) e i sensori previsti. In
// SCENARIO nulla di tutto questo c'è.
test("LIVE: «Sensori previsti» spenti di default, simboli e popup «Previsto — non attivo», «Fonti dati»", async ({
  page,
}, testInfo) => {
  await login(page);
  const live = page.getByRole("radio", { name: /LIVE/ });
  const scenario = page.getByRole("radio", { name: /SCENARIO/ });
  const map = page.getByRole("region", { name: "Mappa" });
  const toggle = map.getByRole("checkbox", { name: "Sensori previsti" });
  const symbols = map.getByRole("button", { name: /previsto, non attivo/ });
  const sources = page.getByRole("region", { name: "Fonti dati" });

  // in SCENARIO nulla cambia: né interruttore, né riquadro
  await expect(toggle).toHaveCount(0);
  await expect(sources).toHaveCount(0);

  await live.click();
  await expect(live).toHaveAttribute("aria-checked", "true");

  // spento di default: nessun simbolo
  await expect(toggle).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(symbols).toHaveCount(0);

  // «Fonti dati»: TomTom attivo (REALE); sonde GPS, tornelli, contapersone e sensori Tangenziale previsti
  await expect(sources).toBeVisible();
  const tomtom = sources.locator("li[data-source='tomtom']");
  await expect(tomtom).toContainText("TomTom");
  await expect(tomtom).toContainText("Attivo");
  await expect(tomtom).toContainText("REALE");
  for (const [type, name] of [
    ["gps_probe", "Sonde GPS"],
    ["turnstile", "Tornelli e validatori"],
    ["people_counter", "Contapersone"],
    ["ramp_counter", "Sensori Tangenziale"],
  ] as const) {
    const row = sources.locator(`li[data-source='${type}']`);
    await expect(row).toContainText(name);
    await expect(row).toContainText("Previsto");
    await expect(row).not.toContainText("REALE");
  }

  // acceso: i simboli compaiono (contapersone, rampe, tornelli sulle stazioni), grigi e tratteggiati
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await expect.poll(() => symbols.count()).toBeGreaterThan(0);
  const dashed = await map
    .locator("[data-sensor='people_counter'], [data-sensor='ramp_counter']")
    .first()
    .evaluate((el) => {
      const style = getComputedStyle(el);
      return { line: style.borderTopStyle, width: parseFloat(style.borderTopWidth) };
    });
  expect(dashed.line).toBe("dashed");
  expect(dashed.width).toBeGreaterThan(0);
  // colori solo dai token, con i simboli, l'interruttore e il riquadro a schermo. (Prima del popup: il
  // CSS di MapLibre dà a ogni popup, anche in SCENARIO, un'ombra `rgba(0,0,0,.1)` che non è un token;
  // è com'era, e non sta ai sensori cambiarlo.)
  await expectOnlyTokenColors(page, "LIVE con sensori previsti");

  // il popup di un simbolo che si vede nella mappa
  const box = (await map.locator("canvas.maplibregl-canvas").boundingBox())!;
  let clicked = false;
  for (const symbol of await symbols.all()) {
    const rect = await symbol.boundingBox();
    if (
      rect &&
      rect.x > box.x + 40 &&
      rect.y > box.y + 80 &&
      rect.x + rect.width < box.x + box.width - 40 &&
      rect.y + rect.height < box.y + box.height - 80
    ) {
      await symbol.click();
      clicked = true;
      break;
    }
  }
  expect(clicked, "almeno un simbolo sta dentro la mappa visibile").toBe(true);
  const popup = page.locator(".maplibregl-popup");
  await expect(popup).toBeVisible();
  await expect(popup).toContainText("Previsto — non attivo");
  await expect(popup).toContainText("Misurerà");
  await expect(popup).toContainText("Sostituirà");
  await expect(popup.locator("[data-measured]")).toHaveCount(0); // nessun numero
  await settleMap(page);
  await shot(page, testInfo, "19-live-sensori");

  // si spegne, e tornando a SCENARIO non resta nulla
  await toggle.click();
  await expect(symbols).toHaveCount(0);
  await scenario.click();
  await expect(toggle).toHaveCount(0);
  await expect(sources).toHaveCount(0);
  await expect(symbols).toHaveCount(0);
});
