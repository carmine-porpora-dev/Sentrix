import {
  expect,
  expectOnlyTokenColors,
  login,
  mapRegion,
  settleMap,
  shot,
  test,
} from "./support.ts";

// «Sensori previsti» (spech 11.5) sul backend vero, **senza rete né chiave TomTom**: l'elenco viene da
// `config/sensors.yaml` (nessun dato, nessun `Measured`), la posizione dei tornelli dalle stazioni delle
// linee del feed GTFS vero. In SCENARIO non si chiede nulla; in LIVE il livello è spento di default.

interface Sensor {
  id: string;
  type: "gps_probe" | "turnstile" | "people_counter" | "ramp_counter";
  status: string;
  route_class: string | null;
  location: { lat: number; lon: number } | null;
}
interface Lines {
  features: { geometry: { coordinates: unknown[] }; properties: { route_class: string } }[];
}

test("LIVE: l'elenco si chiede solo in LIVE; il livello è spento di default e disegna i posti giusti", async ({
  page,
}, testInfo) => {
  const sensorRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/sensors") sensorRequests.push(request.method());
  });
  await login(page);

  // in SCENARIO nessuna richiesta, nessun interruttore, nessun riquadro
  await page.waitForTimeout(1000);
  expect(sensorRequests).toEqual([]);
  const map = mapRegion(page);
  const toggle = map.getByRole("checkbox", { name: "Sensori previsti" });
  await expect(toggle).toHaveCount(0);

  // l'elenco del backend: quello del file, tutto «previsto», senza numeri
  const response = await page.request.get("/api/sensors");
  expect(response.status()).toBe(200);
  const sensors = (await response.json()) as Sensor[];
  sensorRequests.length = 0; // quella appena fatta è del test
  expect(sensors).toHaveLength(14);
  expect(sensors.every((s) => s.status === "planned")).toBe(true);
  expect(JSON.stringify(sensors)).not.toMatch(/"(value|unit|kind|as_of|inputs)"/);
  const count = (type: Sensor["type"]) => sensors.filter((s) => s.type === type).length;
  expect([
    count("gps_probe"),
    count("turnstile"),
    count("people_counter"),
    count("ramp_counter"),
  ]).toEqual([1, 3, 6, 4]);

  // entrando in LIVE: una sola richiesta
  await page.getByRole("radio", { name: /LIVE/ }).click();
  await expect(toggle).toBeVisible();
  await expect.poll(() => sensorRequests.length).toBe(1);
  expect(sensorRequests).toEqual(["GET"]);

  // spento di default
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  const symbols = map.getByRole("button", { name: /previsto, non attivo/ });
  await expect(symbols).toHaveCount(0);

  // «Fonti dati»: senza chiave TomTom l'ultimo dato è lo snapshot («ultimo dato disponibile», REALE);
  // i sensori propri sono previsti
  const sources = page.getByRole("region", { name: "Fonti dati" });
  await expect(sources).toBeVisible();
  const tomtom = sources.locator("li[data-source='tomtom']");
  await expect(tomtom).toContainText("Ultimo dato disponibile");
  await expect(tomtom).toContainText("REALE");
  for (const type of ["gps_probe", "turnstile", "people_counter", "ramp_counter"]) {
    const row = sources.locator(`li[data-source='${type}']`);
    await expect(row).toContainText("Previsto");
    await expect(row).not.toContainText("REALE");
  }

  // acceso: contapersone e rampe nel punto del file, i tornelli su ogni stazione delle linee vere
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  const lines = (await (await page.request.get("/api/transit/lines")).json()) as Lines;
  const stations = (routeClass: string) =>
    lines.features
      .filter((f) => f.properties.route_class === routeClass)
      .reduce((total, f) => total + f.geometry.coordinates.length, 0);
  const turnstiles = sensors
    .filter((s) => s.type === "turnstile")
    .reduce((total, s) => total + stations(s.route_class ?? ""), 0);
  expect(turnstiles).toBeGreaterThan(10); // le stazioni di L1, L6 e funicolari: non zero per sbaglio
  await expect(symbols).toHaveCount(count("people_counter") + count("ramp_counter") + turnstiles);
  // le sonde GPS non hanno un posto: nessun simbolo
  await expect(map.locator("[data-sensor='gps_probe']")).toHaveCount(0);
  await settleMap(page);
  await shot(page, testInfo, "live-03-sensori");
  await expectOnlyTokenColors(page, "LIVE con i sensori previsti");

  // il popup di un simbolo dentro la mappa visibile dice che non è attivo, senza numeri
  const box = (await map.locator("canvas.maplibregl-canvas").boundingBox())!;
  let opened = false;
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
      opened = true;
      break;
    }
  }
  expect(opened, "almeno un simbolo sta dentro la mappa visibile").toBe(true);
  const popup = page.locator(".maplibregl-popup");
  await expect(popup).toContainText("Previsto — non attivo");
  await expect(popup).toContainText("Misurerà");
  await expect(popup).toContainText("Sostituirà");
  await expect(popup.locator("[data-measured]")).toHaveCount(0);

  // spento e fuori da LIVE non resta nulla; l'elenco non si è chiesto di nuovo
  await toggle.click();
  await expect(symbols).toHaveCount(0);
  await page.getByRole("radio", { name: /SCENARIO/ }).click();
  await expect(toggle).toHaveCount(0);
  await expect(sources).toHaveCount(0);
  expect(sensorRequests).toEqual(["GET"]);
});
