import { expect, expectOnlyTokenColors, shot, test } from "./support.ts";

test("senza sessione c'è il login: password vuota rifiutata, accesso, uscita", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Accesso" })).toBeVisible();
  // Prima del login non si vede nulla dell'applicazione.
  await expect(page.getByRole("button", { name: "Analizza" })).toHaveCount(0);
  await shot(page, testInfo, "01-login");
  await expectOnlyTokenColors(page, "login");

  await page.getByRole("button", { name: "Accedi" }).click();
  await expect(page.getByRole("alert")).toHaveText("Inserisci la password.");
  await expect(page.getByRole("heading", { name: "Accesso" })).toBeVisible();

  await page.getByLabel("Password").fill("e2e");
  await page.getByRole("button", { name: "Accedi" }).click();
  await expect(page.getByRole("button", { name: "Analizza" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sentrix" })).toBeVisible();
  await expectOnlyTokenColors(page, "plancia senza run");

  // Uscire riporta al login: la sessione è finita, l'applicazione sparisce.
  await page.getByRole("button", { name: "Esci" }).click();
  await expect(page.getByRole("heading", { name: "Accesso" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Analizza" })).toHaveCount(0);
});
