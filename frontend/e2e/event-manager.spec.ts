import { expect, expectOnlyTokenColors, login, shot, test } from "./support.ts";

// L'Event Manager nel browser vero: i due eventi preset, e la scelta del centro cliccando sulla
// mappa reale (MapLibre + PMTiles), che i test di componente non possono fare (jsdom non ha WebGL).

const REGATE = "Regate preliminari settembre 2026";

test("si passa da un evento preset all'altro: i campi seguono l'evento", async ({
  page,
}, testInfo) => {
  await login(page);
  const picker = page.getByLabel("Evento", { exact: true });
  const name = page.getByLabel("Nome evento");
  await expect(picker).toHaveValue("match_2027");
  await expect(name).toHaveValue("Match 2027 — serata di regata");

  await picker.selectOption({ label: REGATE });
  await expect(name).toHaveValue(REGATE);
  await expect(page.getByText("preset", { exact: true })).toBeVisible();
  await shot(page, testInfo, "12-evento-regate");
});

test("«Evento nuovo»: mancano campi, Analizza aspetta; il centro si sceglie sulla mappa", async ({
  page,
}, testInfo) => {
  await login(page);
  await page.getByRole("button", { name: "Nuovo evento" }).click();
  await expect(page.getByLabel("Nome evento")).toHaveValue("");
  await expect(page.getByText(/Manc(a|ano) \d+ camp/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Analizza" })).toBeDisabled();

  const lat = page.getByLabel("Latitudine");
  const lon = page.getByLabel("Longitudine");
  await expect(lat).toHaveValue("");

  // Il centro: «Scegli il centro sulla mappa» e un clic sulla mappa.
  const map = page.getByRole("region", { name: "Mappa" });
  await expect(page.getByText("Caricamento della mappa…")).toHaveCount(0);
  await expect(map.locator("canvas.maplibregl-canvas")).toBeVisible();
  await page.getByRole("button", { name: "Scegli il centro sulla mappa" }).click();
  await expect(page.getByText("Clicca il centro sulla mappa…")).toBeVisible();
  await page.waitForTimeout(1500); // i tile finiscono di disegnarsi (per lo screenshot)
  await shot(page, testInfo, "13-scelta-del-centro");

  const box = await map.boundingBox();
  if (!box) throw new Error("la mappa non ha dimensioni");
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);

  // Il clic è su Napoli: coordinate vere, non un valore qualsiasi.
  await expect(lat).not.toHaveValue("");
  const latitude = Number(await lat.inputValue());
  const longitude = Number(await lon.inputValue());
  expect(latitude).toBeGreaterThan(40.7);
  expect(latitude).toBeLessThan(41.0);
  expect(longitude).toBeGreaterThan(14.0);
  expect(longitude).toBeLessThan(14.5);
  // La scelta è finita: il messaggio d'attesa non c'è più.
  await expect(page.getByText("Clicca il centro sulla mappa…")).toHaveCount(0);
  await shot(page, testInfo, "14-centro-scelto");
  await expectOnlyTokenColors(page, "evento nuovo: campi, segnaposto, centro scelto");
});
