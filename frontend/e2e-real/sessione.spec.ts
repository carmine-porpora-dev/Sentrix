import { expect, expectOnlyTokenColors, login, shot, test } from "./support.ts";

// F7-TEST: l'accesso sul backend vero (06 1): la password condivisa, il cookie di sessione, e ciò
// che senza sessione non si vede (API e tile). Nessun run.

test("login con il backend: password sbagliata, accesso, ricarica, uscita", async ({
  page,
  allowedProblems,
}, testInfo) => {
  allowedProblems.push(/^HTTP 401 POST \/api\/auth\/login$/);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Accesso" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Analizza" })).toHaveCount(0);
  await shot(page, testInfo, "sessione-01-login");
  await expectOnlyTokenColors(page, "login");

  // la password sbagliata non entra, e non dice altro che «errata»
  await page.getByLabel("Password").fill("password-sbagliata");
  await page.getByRole("button", { name: "Accedi" }).click();
  await expect(page.getByRole("alert")).toHaveText("Password errata.");
  await expect(page.getByRole("button", { name: "Analizza" })).toHaveCount(0);
  await expect(page.getByRole("alert")).not.toContainText(process.env.E2E_PASSWORD ?? "?");

  // quella giusta entra
  await login(page);
  await expect(page.getByRole("heading", { name: "Sentrix" })).toBeVisible();

  // il cookie tiene la sessione: ricaricando si resta dentro
  await page.reload();
  await expect(page.getByRole("button", { name: "Analizza" })).toBeVisible();

  // uscire chiude la sessione: l'applicazione sparisce e l'API risponde 401
  await page.getByRole("button", { name: "Esci" }).click();
  await expect(page.getByRole("heading", { name: "Accesso" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Analizza" })).toHaveCount(0);
  // la mappa, ancora montata un istante, chiede i tile con una sessione che non c'è più: 401 attesi
  allowedProblems.push(/^HTTP 401 GET \/(api|tiles)\//);
  expect((await page.request.get("/api/events")).status()).toBe(401);
});

test("senza sessione l'API e i tile non rispondono; lo stato del sistema sì", async ({
  request,
}) => {
  expect((await request.get("/api/events")).status()).toBe(401);
  expect((await request.get("/api/runs")).status()).toBe(401);
  expect((await request.get("/api/sensors")).status()).toBe(401);
  expect((await request.get("/tiles/napoli.pmtiles")).status()).toBe(401);
  const health = await request.get("/api/health");
  expect(health.status()).toBe(200);
  const body = (await health.json()) as {
    status: string;
    data: { osm: boolean; gtfs: boolean; pmtiles: boolean; gemini_key_present: boolean };
  };
  // i dati veri ci sono e nessuna chiave di servizi esterni è in uso nella prova
  expect(body.status).toBe("ok");
  expect(body.data).toMatchObject({ osm: true, gtfs: true, pmtiles: true });
  expect(body.data.gemini_key_present).toBe(false);
});
